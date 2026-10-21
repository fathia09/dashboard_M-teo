import contextlib
import datetime
import json
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

import src.api_client
from src.api_client import (
    AIR_LABELS,
    AIR_QUALITY_URL,
    DEFAULT_CITIES,
    GEOCODING_URL,
    REQUEST_TIMEOUT,
    WEATHER_LABELS,
    WEATHER_URL,
    WeatherAPIClient,
)


# --------------------------------------------------
# OUTILS ET FIXTURES
# --------------------------------------------------

TIMES = ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"]


def make_data():
    """Petit jeu de données météo + air (3 heures) aux valeurs connues."""
    return {
        "weather": {
            "hourly": {
                "time": list(TIMES),
                "temperature_2m": [10.0, 12.0, 14.0],
                "relative_humidity_2m": [50, 60, 70],
                "surface_pressure": [1000.0, 1001.0, 1002.0],
                "wind_speed_10m": [5.0, 10.0, 15.0],
            }
        },
        "air_quality": {
            "hourly": {
                "time": list(TIMES),
                "pm2_5": [5.0, 10.0, 15.0],
                "pm10": [10.0, 20.0, 30.0],
                "nitrogen_dioxide": [20.0, 30.0, 40.0],
                "ozone": [50.0, 60.0, 70.0],
                "sulphur_dioxide": [1.0, 2.0, 3.0],
                "carbon_monoxide": [200.0, 300.0, 400.0],
                "us_aqi": [20, 30, 40],
            }
        },
    }


def make_response(payload=None, error=None):
    """Fausse réponse `requests` : .json() et .raise_for_status()."""
    response = MagicMock()
    response.json.return_value = payload
    if error is not None:
        response.raise_for_status.side_effect = error
    return response


def insert_raw_cache(client, key, response, timestamp):
    """Écrit directement une ligne dans le cache (pour simuler l'âge/corruption)."""
    with contextlib.closing(sqlite3.connect(client.db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, response, timestamp) "
            "VALUES (?, ?, ?)",
            (key, response, timestamp),
        )
        conn.commit()


@pytest.fixture
def client(tmp_path):
    """Client avec cache SQLite temporaire et session HTTP simulée."""
    instance = WeatherAPIClient(db_path=str(tmp_path / "cache.db"))
    instance.session = MagicMock()
    yield instance
    instance.close()


GEOCODE_OK = {
    "results": [
        {
            "name": "Paris",
            "country": "France",
            "country_code": "FR",
            "latitude": 48.85,
            "longitude": 2.35,
        }
    ]
}


# --------------------------------------------------
# 1. INITIALISATION ET CACHE SQLITE
# --------------------------------------------------

class TestCache:

    def test_init_creates_table(self, client):
        with contextlib.closing(sqlite3.connect(client.db_path)) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        assert ("api_cache",) in tables

    def test_init_raises_if_db_unreachable(self, tmp_path):
        bad_path = tmp_path / "dossier_inexistant" / "cache.db"
        with pytest.raises(sqlite3.Error):
            WeatherAPIClient(db_path=str(bad_path))

    def test_set_then_get_roundtrip(self, client):
        payload = {"a": 1, "b": [1, 2, 3], "c": "é"}
        client._set_cached_data("k", payload)
        assert client._get_cached_data("k") == payload

    def test_get_unknown_key_returns_none(self, client):
        assert client._get_cached_data("absent") is None

    def test_set_overwrites_existing_key(self, client):
        client._set_cached_data("k", {"v": 1})
        client._set_cached_data("k", {"v": 2})
        assert client._get_cached_data("k") == {"v": 2}

    def test_expired_entry_returns_none(self, client):
        old = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
        insert_raw_cache(client, "k", json.dumps({"v": 1}), old)
        assert client._get_cached_data("k") is None

    def test_ttl_zero_expires_immediately(self, tmp_path):
        short = WeatherAPIClient(
            db_path=str(tmp_path / "ttl.db"), cache_ttl_minutes=0
        )
        short._set_cached_data("k", {"v": 1})
        assert short._get_cached_data("k") is None
        short.close()

    def test_fresh_entry_is_returned(self, client):
        recent = (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat()
        insert_raw_cache(client, "k", json.dumps({"v": 1}), recent)
        assert client._get_cached_data("k") == {"v": 1}

    def test_corrupted_json_returns_none(self, client):
        insert_raw_cache(
            client, "k", "{pas du json", datetime.datetime.now().isoformat()
        )
        assert client._get_cached_data("k") is None

    def test_invalid_timestamp_returns_none(self, client):
        insert_raw_cache(client, "k", json.dumps({"v": 1}), "pas une date")
        assert client._get_cached_data("k") is None

    def test_set_with_non_serializable_data_does_not_raise(self, client):
        # Une panne du cache ne doit jamais masquer une réponse API valide.
        client._set_cached_data("k", {"objet": object()})
        assert client._get_cached_data("k") is None


# --------------------------------------------------
# 2. GÉOCODAGE
# --------------------------------------------------

class TestGeocoding:

    @pytest.mark.parametrize("city", ["", "   ", "\t\n"])
    def test_empty_city_raises_value_error(self, client, city):
        with pytest.raises(ValueError, match="obligatoire"):
            client.geocode_city(city)
        client.session.get.assert_not_called()

    def test_success_returns_location(self, client):
        client.session.get.return_value = make_response(GEOCODE_OK)

        place = client.geocode_city("Paris")

        assert place == {
            "name": "Paris",
            "country": "France",
            "country_code": "FR",
            "latitude": 48.85,
            "longitude": 2.35,
        }

    def test_request_parameters(self, client):
        client.session.get.return_value = make_response(GEOCODE_OK)

        client.geocode_city("  Paris  ", country_code="fr")

        client.session.get.assert_called_once_with(
            GEOCODING_URL,
            params={
                "name": "Paris",
                "count": 10,
                "language": "fr",
                "format": "json",
                "countryCode": "FR",
            },
            timeout=REQUEST_TIMEOUT,
        )

    def test_no_country_code_param_by_default(self, client):
        client.session.get.return_value = make_response(GEOCODE_OK)
        client.geocode_city("Paris")
        params = client.session.get.call_args.kwargs["params"]
        assert "countryCode" not in params

    def test_second_call_uses_cache(self, client):
        client.session.get.return_value = make_response(GEOCODE_OK)

        first = client.geocode_city("Paris")
        second = client.geocode_city("  paris ")  # même clé après strip/lower

        assert first == second
        assert client.session.get.call_count == 1

    def test_country_code_is_part_of_cache_key(self, client):
        client.session.get.return_value = make_response(GEOCODE_OK)

        client.geocode_city("Paris")
        client.geocode_city("Paris", country_code="FR")

        assert client.session.get.call_count == 2

    def test_missing_name_falls_back_to_query(self, client):
        client.session.get.return_value = make_response(
            {"results": [{"latitude": 1.0, "longitude": 2.0}]}
        )
        place = client.geocode_city("Ville inconnue")
        assert place["name"] == "Ville inconnue"
        assert place["country"] == ""
        assert place["country_code"] == ""

    @pytest.mark.parametrize("payload", [{}, {"results": []}])
    def test_no_result_raises_runtime_error(self, client, payload):
        # Le ValueError interne est converti en RuntimeError.
        client.session.get.return_value = make_response(payload)
        with pytest.raises(RuntimeError, match="coordonnées"):
            client.geocode_city("Nullepart")

    def test_missing_coordinates_raises_runtime_error(self, client):
        client.session.get.return_value = make_response(
            {"results": [{"name": "X"}]}
        )
        with pytest.raises(RuntimeError, match="coordonnées"):
            client.geocode_city("X")

    def test_network_error_raises_runtime_error(self, client):
        client.session.get.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(RuntimeError, match="rechercher la ville"):
            client.geocode_city("Paris")

    def test_http_error_raises_runtime_error(self, client):
        client.session.get.return_value = make_response(
            error=requests.exceptions.HTTPError("500")
        )
        with pytest.raises(RuntimeError, match="rechercher la ville"):
            client.geocode_city("Paris")

    def test_failure_is_not_cached(self, client):
        client.session.get.side_effect = requests.exceptions.Timeout()
        with pytest.raises(RuntimeError):
            client.geocode_city("Paris")

        client.session.get.side_effect = None
        client.session.get.return_value = make_response(GEOCODE_OK)
        assert client.geocode_city("Paris")["name"] == "Paris"


# --------------------------------------------------
# 3. APPELS AUX API MÉTÉO ET AIR
# --------------------------------------------------

class TestRawFetchers:

    def test_fetch_weather_parameters(self, client):
        client.session.get.return_value = make_response({"ok": True})

        result = client._fetch_weather(48.85, 2.35)

        assert result == {"ok": True}
        args, kwargs = client.session.get.call_args
        assert args[0] == WEATHER_URL
        assert kwargs["timeout"] == REQUEST_TIMEOUT
        params = kwargs["params"]
        assert params["latitude"] == 48.85
        assert params["longitude"] == 2.35
        assert params["forecast_days"] == 7
        assert params["timezone"] == "auto"
        for variable in WEATHER_LABELS:
            assert variable in params["hourly"].split(",")

    def test_fetch_air_quality_parameters(self, client):
        client.session.get.return_value = make_response({"ok": True})

        result = client._fetch_air_quality(48.85, 2.35)

        assert result == {"ok": True}
        args, kwargs = client.session.get.call_args
        assert args[0] == AIR_QUALITY_URL
        params = kwargs["params"]
        assert params["forecast_days"] == 7
        assert params["timezone"] == "auto"
        for variable in AIR_LABELS:
            assert variable in params["hourly"].split(",")

    def test_fetchers_call_raise_for_status(self, client):
        response = make_response({})
        client.session.get.return_value = response
        client._fetch_weather(0, 0)
        client._fetch_air_quality(0, 0)
        assert response.raise_for_status.call_count == 2


# --------------------------------------------------
# 4. METÉO + AIR (cache, validation, erreurs, mode simulé)
# --------------------------------------------------

class TestFetchWeatherAndAirQuality:

    @pytest.mark.parametrize(
        "lat, lon",
        [(91, 0), (-91, 0), (90.0001, 0), (0, 181), (0, -181), (0, 180.5)],
    )
    def test_out_of_range_coordinates_raise(self, client, lat, lon):
        with pytest.raises(ValueError):
            client.fetch_weather_and_air_quality(lat, lon)

    def test_validation_also_applies_in_mock_mode(self, client):
        with pytest.raises(ValueError):
            client.fetch_weather_and_air_quality(100, 0, mock_mode=True)

    @pytest.mark.parametrize("lat, lon", [(90, 180), (-90, -180), (0, 0)])
    def test_boundary_coordinates_are_accepted(self, client, lat, lon):
        result = client.fetch_weather_and_air_quality(lat, lon, mock_mode=True)
        assert set(result) == {"weather", "air_quality"}

    def test_success_combines_both_apis(self, client):
        with patch.object(client, "_fetch_weather", return_value={"w": 1}), \
             patch.object(client, "_fetch_air_quality", return_value={"a": 2}):
            result = client.fetch_weather_and_air_quality(48.85, 2.35)

        assert result == {"weather": {"w": 1}, "air_quality": {"a": 2}}

    def test_result_is_cached(self, client):
        with patch.object(client, "_fetch_weather", return_value={"w": 1}) as w, \
             patch.object(client, "_fetch_air_quality", return_value={"a": 2}) as a:
            first = client.fetch_weather_and_air_quality(48.85, 2.35)
            second = client.fetch_weather_and_air_quality(48.85, 2.35)

        assert first == second
        assert w.call_count == 1
        assert a.call_count == 1

    def test_cache_key_rounds_to_four_decimals(self, client):
        with patch.object(client, "_fetch_weather", return_value={"w": 1}) as w, \
             patch.object(client, "_fetch_air_quality", return_value={"a": 2}):
            client.fetch_weather_and_air_quality(48.85661, 2.35221)
            client.fetch_weather_and_air_quality(48.85659, 2.35219)

        assert w.call_count == 1

    def test_different_coordinates_are_not_shared(self, client):
        with patch.object(client, "_fetch_weather", return_value={"w": 1}) as w, \
             patch.object(client, "_fetch_air_quality", return_value={"a": 2}):
            client.fetch_weather_and_air_quality(48.85, 2.35)
            client.fetch_weather_and_air_quality(45.76, 4.83)

        assert w.call_count == 2

    def test_mock_mode_makes_no_network_call_and_skips_cache(self, client):
        result = client.fetch_weather_and_air_quality(48.8566, 2.3522, mock_mode=True)

        client.session.get.assert_not_called()
        assert "hourly" in result["weather"]
        assert client._get_cached_data("weather_air:48.8566:2.3522") is None

    def test_mock_mode_ignores_existing_cache(self, client):
        client._set_cached_data("weather_air:48.8566:2.3522", {"cache": True})
        result = client.fetch_weather_and_air_quality(48.8566, 2.3522, mock_mode=True)
        assert "cache" not in result

    def test_timeout_raises_runtime_error(self, client):
        client.session.get.side_effect = requests.exceptions.Timeout()
        with pytest.raises(RuntimeError, match="trop de temps"):
            client.fetch_weather_and_air_quality(48.85, 2.35)

    def test_http_error_raises_runtime_error(self, client):
        client.session.get.return_value = make_response(
            error=requests.exceptions.HTTPError("429")
        )
        with pytest.raises(RuntimeError, match="erreur HTTP"):
            client.fetch_weather_and_air_quality(48.85, 2.35)

    def test_connection_error_raises_runtime_error(self, client):
        client.session.get.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(RuntimeError, match="Impossible de contacter"):
            client.fetch_weather_and_air_quality(48.85, 2.35)

    def test_invalid_data_raises_runtime_error(self, client):
        with patch.object(client, "_fetch_weather", side_effect=ValueError("bad")):
            with pytest.raises(RuntimeError, match="invalides"):
                client.fetch_weather_and_air_quality(48.85, 2.35)

    def test_failure_is_not_cached(self, client):
        client.session.get.side_effect = requests.exceptions.Timeout()
        with pytest.raises(RuntimeError):
            client.fetch_weather_and_air_quality(48.85, 2.35)
        assert client._get_cached_data("weather_air:48.8500:2.3500") is None


# --------------------------------------------------
# 5. VILLES PAR DÉFAUT
# --------------------------------------------------

class TestFetchDefaultCities:

    def test_default_cities_in_mock_mode(self, client):
        results = client.fetch_default_cities(mock_mode=True)

        assert set(results) == set(DEFAULT_CITIES)
        assert len(results) == 5
        for data in results.values():
            assert "error" not in data
            assert "weather" in data and "air_quality" in data

    def test_one_failure_does_not_block_others(self, client):
        cities = {
            "Valide": {"lat": 45.0, "lon": 5.0},
            "LatitudeInvalide": {"lat": 200.0, "lon": 0.0},
            "SansCoordonnees": {},
        }

        results = client.fetch_default_cities(cities, mock_mode=True)

        assert "weather" in results["Valide"]
        assert "error" in results["LatitudeInvalide"]
        assert "error" in results["SansCoordonnees"]

    def test_network_failure_gives_error_entries(self, client):
        client.session.get.side_effect = requests.exceptions.ConnectionError()

        results = client.fetch_default_cities({"Paris": DEFAULT_CITIES["Paris"]})

        assert results["Paris"] == {
            "error": "Données indisponibles pour cette ville."
        }


# --------------------------------------------------
# 6. TRANSFORMATION EN DATAFRAME
# --------------------------------------------------

class TestPrepareCityDataframe:

    def test_columns_and_shape(self):
        df = WeatherAPIClient.prepare_city_dataframe(make_data())

        assert len(df) == 3
        assert df.columns[0] == "Date et heure"
        for label in list(WEATHER_LABELS.values()) + list(AIR_LABELS.values()):
            assert label in df.columns

    def test_datetime_column_is_converted(self):
        df = WeatherAPIClient.prepare_city_dataframe(make_data())
        assert pd.api.types.is_datetime64_any_dtype(df["Date et heure"])
        assert df["Date et heure"].iloc[0] == pd.Timestamp("2026-01-01 00:00")

    def test_values_are_preserved(self):
        df = WeatherAPIClient.prepare_city_dataframe(make_data())
        assert df["Température (°C)"].tolist() == [10.0, 12.0, 14.0]
        assert df["PM2.5 (µg/m³)"].tolist() == [5.0, 10.0, 15.0]

    def test_error_entry_raises_value_error(self):
        with pytest.raises(ValueError, match="indisponible"):
            WeatherAPIClient.prepare_city_dataframe({"error": "indisponible"})

    @pytest.mark.parametrize(
        "data",
        [{}, {"weather": {}}, {"weather": {"hourly": {"time": []}}}],
    )
    def test_no_hourly_data_raises_value_error(self, data):
        with pytest.raises(ValueError, match="Aucune donnée horaire"):
            WeatherAPIClient.prepare_city_dataframe(data)

    def test_missing_air_quality_keeps_weather_only(self):
        data = make_data()
        del data["air_quality"]

        df = WeatherAPIClient.prepare_city_dataframe(data)

        assert "Température (°C)" in df.columns
        assert "PM2.5 (µg/m³)" not in df.columns
        assert len(df) == 3

    def test_column_with_wrong_length_is_skipped(self):
        data = make_data()
        data["weather"]["hourly"]["wind_speed_10m"] = [1.0]  # 1 valeur pour 3 heures

        df = WeatherAPIClient.prepare_city_dataframe(data)

        assert "Vent (km/h)" not in df.columns
        assert "Température (°C)" in df.columns

    def test_left_merge_keeps_weather_rows_without_air(self):
        data = make_data()
        data["air_quality"]["hourly"]["time"] = TIMES[:2]
        for key in AIR_LABELS:
            data["air_quality"]["hourly"][key] = data["air_quality"]["hourly"][key][:2]

        df = WeatherAPIClient.prepare_city_dataframe(data)

        assert len(df) == 3
        assert pd.isna(df["PM2.5 (µg/m³)"].iloc[2])
        assert df["PM2.5 (µg/m³)"].iloc[1] == 10.0


# --------------------------------------------------
# 7. STATISTIQUES
# --------------------------------------------------

class TestCalculateSummary:

    def test_mean_min_max(self):
        df = WeatherAPIClient.prepare_city_dataframe(make_data())

        summary = WeatherAPIClient.calculate_summary(df)

        assert summary["Température (°C)"] == {
            "moyenne": 12.0,
            "minimum": 10.0,
            "maximum": 14.0,
        }

    def test_datetime_column_is_excluded(self):
        df = WeatherAPIClient.prepare_city_dataframe(make_data())
        assert "Date et heure" not in WeatherAPIClient.calculate_summary(df)

    def test_missing_values_are_ignored(self):
        df = pd.DataFrame({"Date et heure": TIMES, "x": [10.0, None, 30.0]})
        assert WeatherAPIClient.calculate_summary(df)["x"] == {
            "moyenne": 20.0,
            "minimum": 10.0,
            "maximum": 30.0,
        }

    def test_all_missing_or_non_numeric_columns_are_skipped(self):
        df = pd.DataFrame({
            "Date et heure": TIMES,
            "vide": [None, None, None],
            "texte": ["a", "b", "c"],
            "ok": [1, 2, 3],
        })
        summary = WeatherAPIClient.calculate_summary(df)
        assert list(summary) == ["ok"]

    def test_values_are_rounded_to_two_decimals(self):
        df = pd.DataFrame({"Date et heure": TIMES, "x": [1.0, 1.0, 2.0]})
        assert WeatherAPIClient.calculate_summary(df)["x"]["moyenne"] == 1.33

    def test_empty_dataframe_gives_empty_summary(self):
        assert WeatherAPIClient.calculate_summary(pd.DataFrame()) == {}


# --------------------------------------------------
# 8. VUE D'ENSEMBLE PAR VILLE
# --------------------------------------------------

class TestOverview:

    @staticmethod
    def _data_around_now():
        """Trois heures : passé, maintenant, futur (la valeur du milieu est 2)."""
        now = datetime.datetime.now()
        times = [
            (now - datetime.timedelta(hours=3)).isoformat(),
            now.isoformat(),
            (now + datetime.timedelta(hours=3)).isoformat(),
        ]
        data = make_data()
        data["weather"]["hourly"]["time"] = times
        data["air_quality"]["hourly"]["time"] = times
        data["weather"]["hourly"]["temperature_2m"] = [1.0, 2.0, 3.0]
        data["air_quality"]["hourly"]["pm2_5"] = [10.0, 20.0, 30.0]
        return data

    def test_uses_value_nearest_to_now(self, client):
        overview = client.build_city_overview({"Paris": self._data_around_now()})

        assert overview.loc[0, "Ville"] == "Paris"
        assert overview.loc[0, "Température (°C)"] == 2.0
        assert overview.loc[0, "PM2.5 (µg/m³)"] == 20.0

    def test_one_row_per_city(self, client):
        data = self._data_around_now()
        overview = client.build_city_overview({"A": data, "B": data, "C": data})
        assert overview["Ville"].tolist() == ["A", "B", "C"]

    def test_error_city_gets_error_row(self, client):
        overview = client.build_city_overview({
            "Paris": self._data_around_now(),
            "Lyon": {"error": "Données indisponibles pour cette ville."},
        })

        lyon = overview[overview["Ville"] == "Lyon"].iloc[0]
        assert lyon["Erreur"] == "Données indisponibles pour cette ville."
        assert pd.isna(lyon["Température (°C)"])

    def test_missing_air_data_gives_empty_values(self, client):
        data = self._data_around_now()
        del data["air_quality"]

        overview = client.build_city_overview({"Paris": data})

        assert overview.loc[0, "Température (°C)"] == 2.0
        assert pd.isna(overview.loc[0, "PM2.5 (µg/m³)"])

    def test_empty_input_gives_empty_dataframe(self, client):
        assert client.build_city_overview({}).empty


class TestNearestTimeIndex:

    def test_empty_list_returns_none(self):
        assert WeatherAPIClient._nearest_time_index([]) is None

    def test_picks_closest_time(self):
        now = datetime.datetime.now()
        times = [
            (now - datetime.timedelta(hours=3)).isoformat(),
            now.isoformat(),
            (now + datetime.timedelta(hours=3)).isoformat(),
        ]
        assert WeatherAPIClient._nearest_time_index(times) == 1

    def test_picks_closest_when_all_in_the_past(self):
        now = datetime.datetime.now()
        times = [
            (now - datetime.timedelta(hours=10)).isoformat(),
            (now - datetime.timedelta(hours=2)).isoformat(),
            (now - datetime.timedelta(hours=5)).isoformat(),
        ]
        assert WeatherAPIClient._nearest_time_index(times) == 1

    def test_invalid_entries_are_skipped_but_indexes_preserved(self):
        times = ["pas une date", datetime.datetime.now().isoformat()]
        assert WeatherAPIClient._nearest_time_index(times) == 1

    def test_all_invalid_returns_zero(self):
        assert WeatherAPIClient._nearest_time_index(["foo", "bar"]) == 0

    def test_timezone_aware_strings_are_supported(self):
        now = datetime.datetime.now().isoformat() + "+02:00"
        far = (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat()
        assert WeatherAPIClient._nearest_time_index([far, now]) == 1


class TestValueAt:

    def test_returns_value(self):
        assert WeatherAPIClient._value_at({"x": [1, 2, 3]}, "x", 1) == 2

    def test_none_index_returns_none(self):
        assert WeatherAPIClient._value_at({"x": [1, 2, 3]}, "x", None) is None

    def test_index_out_of_range_returns_none(self):
        assert WeatherAPIClient._value_at({"x": [1]}, "x", 5) is None

    def test_missing_key_returns_none(self):
        assert WeatherAPIClient._value_at({}, "x", 0) is None


# --------------------------------------------------
# 9. EXPORTS CSV ET PDF
# --------------------------------------------------

class TestExportCsv:

    def test_returns_utf8_sig_bytes(self, client):
        content = client.export_csv(make_data(), "Paris")

        assert isinstance(content, bytes)
        assert content.startswith(b"\xef\xbb\xbf")  # BOM pour Excel

    def test_header_and_separator(self, client):
        text = client.export_csv(make_data(), "Paris").decode("utf-8-sig")
        header = text.splitlines()[0]

        assert header.startswith("Ville;Date et heure;")
        assert "Température (°C)" in header
        assert "PM2.5 (µg/m³)" in header

    def test_one_row_per_hour_with_city_name(self, client):
        text = client.export_csv(make_data(), "Zürich").decode("utf-8-sig")
        lines = text.splitlines()

        assert len(lines) == 1 + 3  # en-tête + 3 heures
        assert all(line.startswith("Zürich;") for line in lines[1:])

    def test_default_city_name(self, client):
        text = client.export_csv(make_data()).decode("utf-8-sig")
        assert text.splitlines()[1].startswith("Ville inconnue;")

    def test_full_mock_week_is_exported(self, client):
        data = client._generate_mock_data(45.0, 5.0)
        text = client.export_csv(data, "Lyon").decode("utf-8-sig")
        assert len(text.splitlines()) == 1 + 24 * 7

    def test_error_data_raises_value_error(self, client):
        with pytest.raises(ValueError):
            client.export_csv({"error": "indisponible"}, "Paris")

    def test_can_be_read_back_by_pandas(self, client):
        import io

        content = client.export_csv(make_data(), "Paris")
        df = pd.read_csv(io.BytesIO(content), sep=";", encoding="utf-8-sig")

        assert len(df) == 3
        assert df["Température (°C)"].tolist() == [10.0, 12.0, 14.0]


class TestExportPdf:

    def test_returns_valid_pdf(self, client):
        pytest.importorskip("reportlab")
        pdf = client.export_pdf(make_data(), "Paris")

        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1000

    def test_full_mock_week_more_than_24_rows(self, client):
        pytest.importorskip("reportlab")
        data = client._generate_mock_data(45.0, 5.0)
        pdf = client.export_pdf(data, "Lyon")
        assert pdf.startswith(b"%PDF")

    def test_error_data_raises_value_error(self, client):
        pytest.importorskip("reportlab")
        with pytest.raises(ValueError):
            client.export_pdf({"error": "indisponible"}, "Paris")

    def test_missing_reportlab_gives_clear_message(self, client, monkeypatch):
        monkeypatch.setitem(sys.modules, "reportlab", None)
        monkeypatch.setitem(sys.modules, "reportlab.lib", None)

        with pytest.raises(RuntimeError, match="pip install reportlab"):
            client.export_pdf(make_data(), "Paris")


# --------------------------------------------------
# 10. DONNÉES SIMULÉES
# --------------------------------------------------

class TestMockData:

    @pytest.fixture
    def mock_data(self, client):
        return client._generate_mock_data(48.85, 2.35)

    def test_structure(self, mock_data):
        assert set(mock_data) == {"weather", "air_quality"}
        assert mock_data["weather"]["latitude"] == 48.85
        assert mock_data["air_quality"]["longitude"] == 2.35
        assert mock_data["weather"]["timezone"] == "auto"

    def test_contains_all_expected_variables(self, mock_data):
        for key in WEATHER_LABELS:
            assert key in mock_data["weather"]["hourly"]
        for key in AIR_LABELS:
            assert key in mock_data["air_quality"]["hourly"]

    def test_seven_days_of_hourly_data(self, mock_data):
        hourly = mock_data["weather"]["hourly"]
        assert len(hourly["time"]) == 24 * 7

    def test_all_series_have_same_length(self, mock_data):
        expected = len(mock_data["weather"]["hourly"]["time"])
        for section in ("weather", "air_quality"):
            for values in mock_data[section]["hourly"].values():
                assert len(values) == expected

    def test_times_are_hourly_ascending_and_end_now(self, mock_data):
        times = [
            datetime.datetime.fromisoformat(t)
            for t in mock_data["weather"]["hourly"]["time"]
        ]

        assert times == sorted(times)
        assert all(
            (b - a) == datetime.timedelta(hours=1)
            for a, b in zip(times, times[1:])
        )
        assert times[-1].minute == 0
        assert abs(datetime.datetime.now() - times[-1]) < datetime.timedelta(hours=1, minutes=1)

    def test_value_ranges(self, mock_data):
        w = mock_data["weather"]["hourly"]
        a = mock_data["air_quality"]["hourly"]

        assert all(5 <= v <= 35 for v in w["temperature_2m"])
        assert all(30 <= v < 95 for v in w["relative_humidity_2m"])
        assert all(990 <= v <= 1030 for v in w["surface_pressure"])
        assert all(0 <= v <= 30 for v in w["wind_speed_10m"])
        assert all(2 <= v <= 40 for v in a["pm2_5"])
        assert all(5 <= v <= 60 for v in a["pm10"])
        assert all(0 <= v <= 150 for v in a["us_aqi"])

    def test_data_is_json_serializable(self, mock_data):
        # Indispensable pour le cache SQLite (pas de types numpy).
        json.dumps(mock_data)

    def test_mock_data_compatible_with_dataframe_builder(self, mock_data):
        df = WeatherAPIClient.prepare_city_dataframe(mock_data)
        assert len(df) == 24 * 7
        assert df.notna().all().all()


# --------------------------------------------------
# 11. FERMETURE
# --------------------------------------------------

def test_close_closes_the_http_session(client):
    client.close()
    client.session.close.assert_called_once()


def test_module_exposes_official_urls():
    assert src.api_client.GEOCODING_URL.startswith("https://geocoding-api.open-meteo.com")
    assert src.api_client.WEATHER_URL.startswith("https://api.open-meteo.com")
    assert src.api_client.AIR_QUALITY_URL.startswith("https://air-quality-api.open-meteo.com")