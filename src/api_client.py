import csv
import datetime
import io
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

CACHE_DB = "data_cache.db"
CACHE_TTL_MINUTES = 30


# Liens officiels des API Open-Meteo (conservés).
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"




REQUEST_TIMEOUT = 10

DEFAULT_CITIES = {
    "Paris": {"lat": 48.8566, "lon": 2.3522},
    "Lyon": {"lat": 45.7640, "lon": 4.8357},
    "Marseille": {"lat": 43.2965, "lon": 5.3698},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Madrid": {"lat": 40.4168, "lon": -3.7038},
}

WEATHER_LABELS = {
    "temperature_2m": "Température (°C)",
    "relative_humidity_2m": "Humidité (%)",
    "surface_pressure": "Pression (hPa)",
    "wind_speed_10m": "Vent (km/h)",
}

AIR_LABELS = {
    "pm2_5": "PM2.5 (µg/m³)",
    "pm10": "PM10 (µg/m³)",
    "nitrogen_dioxide": "Dioxyde d'azote",
    "ozone": "Ozone",
    "sulphur_dioxide": "Dioxyde de soufre",
    "carbon_monoxide": "Monoxyde de carbone",
    "us_aqi": "Indice AQI américain",
}


# --------------------------------------------------
# 2. CLIENT API
# --------------------------------------------------

class WeatherAPIClient:
    """Gère les API, le géocodage, le cache et les erreurs."""

    def __init__(
        self,
        db_path: str = CACHE_DB,
        cache_ttl_minutes: int = CACHE_TTL_MINUTES,
    ):
        self.db_path = db_path
        self.cache_ttl_minutes = cache_ttl_minutes
        self.session = requests.Session()
        self._init_db()

    # --------------------------------------------------
    # 3. INITIALISATION DU CACHE SQLITE
    # --------------------------------------------------

    def _init_db(self) -> None:
        """Crée la table qui stocke les réponses des API."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_cache (
                        key TEXT PRIMARY KEY,
                        response TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                    """
                )
            logging.info("Cache SQLite initialisé.")
        except sqlite3.Error:
            logging.exception("Impossible d'initialiser le cache SQLite.")
            raise

    # --------------------------------------------------
    # 4. LECTURE DU CACHE
    # --------------------------------------------------

    def _get_cached_data(self, key: str) -> Optional[Dict[str, Any]]:
        """Retourne les données en cache si elles sont encore valides."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT response, timestamp
                    FROM api_cache
                    WHERE key = ?
                    """,
                    (key,),
                ).fetchone()

            if row is None:
                return None

            response_json, timestamp_text = row
            timestamp = datetime.datetime.fromisoformat(timestamp_text)
            age = datetime.datetime.now() - timestamp
            ttl = datetime.timedelta(minutes=self.cache_ttl_minutes)

            if age >= ttl:
                logging.info("Cache expiré : %s", key)
                return None

            logging.info("Cache utilisé : %s", key)
            return json.loads(response_json)

        except (
            sqlite3.Error,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            logging.exception("Erreur lors de la lecture du cache.")
            return None

    # --------------------------------------------------
    # 5. ÉCRITURE DANS LE CACHE
    # --------------------------------------------------

    def _set_cached_data(self, key: str, data: Dict[str, Any]) -> None:
        """Enregistre une réponse JSON dans SQLite."""
        try:
            response_json = json.dumps(data)
            timestamp = datetime.datetime.now().isoformat()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_cache
                    (key, response, timestamp)
                    VALUES (?, ?, ?)
                    """,
                    (key, response_json, timestamp),
                )

            logging.info("Données mises en cache : %s", key)

        except (sqlite3.Error, TypeError, ValueError):
            # Une panne du cache ne doit pas masquer une réponse API obtenue.
            logging.exception("Impossible d'enregistrer le cache.")

    # --------------------------------------------------
    # 6. GÉOCODAGE : NOM DE VILLE -> COORDONNÉES
    # --------------------------------------------------

    def geocode_city(
        self,
        city: str,
        country_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recherche une ville et retourne son nom, pays et coordonnées."""
        city = city.strip()

        if not city:
            raise ValueError("Le nom de la ville est obligatoire.")

        cache_key = f"geocode:{city.lower()}:{country_code or ''}"
        cached = self._get_cached_data(cache_key)

        if cached is not None:
            return cached

        params = {
            "name": city,
            "count": 10,
            "language": "fr",
            "format": "json",
        }

        if country_code:
            params["countryCode"] = country_code.upper()

        try:
            response = self.session.get(
                GEOCODING_URL,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])

            if not results:
                raise ValueError(f"Aucune ville trouvée pour : {city}")

            place = results[0]
            location = {
                "name": place.get("name", city),
                "country": place.get("country", ""),
                "country_code": place.get("country_code", ""),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
            }

            self._set_cached_data(cache_key, location)
            return location

        except requests.exceptions.RequestException as exc:
            logging.exception("Erreur HTTP pendant le géocodage.")
            raise RuntimeError(
                f"Impossible de rechercher la ville {city}."
            ) from exc
        except (KeyError, ValueError) as exc:
            logging.exception("Réponse de géocodage invalide.")
            raise RuntimeError(
                f"Impossible d'obtenir les coordonnées de {city}."
            ) from exc

    # --------------------------------------------------
    # 7. RÉCUPÉRATION MÉTÉO
    # --------------------------------------------------

    def _fetch_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """Récupère les données météo horaires sur sept jours."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": (
                "temperature_2m,"
                "relative_humidity_2m,"
                "surface_pressure,"
                "wind_speed_10m"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        }

        response = self.session.get(
            WEATHER_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    


    # --------------------------------------------------
    # 8. RÉCUPÉRATION QUALITÉ DE L'AIR
    # --------------------------------------------------

    def _fetch_air_quality(self, lat: float, lon: float) -> Dict[str, Any]:
        """Récupère les données horaires de qualité de l'air sur sept jours."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": (
                "pm10,"
                "pm2_5,"
                "nitrogen_dioxide,"
                "ozone,"
                "sulphur_dioxide,"
                "carbon_monoxide,"
                "us_aqi"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        }

        response = self.session.get(
            AIR_QUALITY_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    # --------------------------------------------------
    # 9. RÉCUPÉRATION MÉTÉO + QUALITÉ DE L'AIR
    # --------------------------------------------------

    def fetch_weather_and_air_quality(
        self,
        lat: float,
        lon: float,
        mock_mode: bool = False,
    ) -> Dict[str, Any]:
        """Retourne météo + qualité de l'air, avec cache et mode simulé."""
        if not -90 <= lat <= 90:
            raise ValueError("La latitude doit être comprise entre -90 et 90.")

        if not -180 <= lon <= 180:
            raise ValueError("La longitude doit être comprise entre -180 et 180.")

        cache_key = f"weather_air:{lat:.4f}:{lon:.4f}"

        if mock_mode:
            return self._generate_mock_data(lat, lon)

        cached = self._get_cached_data(cache_key)
        if cached is not None:
            return cached

        try:
            weather_data = self._fetch_weather(lat, lon)
            air_data = self._fetch_air_quality(lat, lon)

            result = {
                "weather": weather_data,
                "air_quality": air_data,
            }
            self._set_cached_data(cache_key, result)
            return result

        except requests.exceptions.Timeout as exc:
            logging.warning("Délai d'attente dépassé pour les API.")
            raise RuntimeError(
                "Les API mettent trop de temps à répondre."
            ) from exc
        except requests.exceptions.HTTPError as exc:
            logging.exception("Erreur HTTP renvoyée par une API.")
            raise RuntimeError(
                "Une API a refusé la requête ou renvoyé une erreur HTTP."
            ) from exc
        except requests.exceptions.RequestException as exc:
            logging.exception("Erreur réseau pendant la récupération.")
            raise RuntimeError(
                "Impossible de contacter les API. Vérifie ta connexion."
            ) from exc
        except ValueError as exc:
            logging.exception("Réponse API invalide.")
            raise RuntimeError(
                "Les données reçues des API sont invalides."
            ) from exc

    # --------------------------------------------------
    # 10. RÉCUPÉRATION DES CINQ VILLES PAR DÉFAUT
    # --------------------------------------------------

    def fetch_default_cities(
        self,
        cities: Optional[Dict[str, Dict[str, float]]] = None,
        mock_mode: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Récupère les données de toutes les villes fournies.
        Retourne un dictionnaire {nom_ville: données}.
        Une erreur pour une ville n'empêche pas les autres de charger.
        """
        cities = cities or DEFAULT_CITIES
        results: Dict[str, Dict[str, Any]] = {}

        for city, coordinates in cities.items():
            try:
                results[city] = self.fetch_weather_and_air_quality(
                    lat=coordinates["lat"],
                    lon=coordinates["lon"],
                    mock_mode=mock_mode,
                )
            except (RuntimeError, ValueError, KeyError):
                logging.exception("Impossible de récupérer les données de %s.", city)
                results[city] = {"error": "Données indisponibles pour cette ville."}

        return results

    # --------------------------------------------------
    # 11. TRANSFORMATION DES DONNÉES EN DATAFRAME
    # --------------------------------------------------

    @staticmethod
    def prepare_city_dataframe(data: Dict[str, Any]) -> pd.DataFrame:
        """Fusionne les données horaires météo et qualité de l'air."""
        if "error" in data:
            raise ValueError(data["error"])

        weather_hourly = data.get("weather", {}).get("hourly", {})
        air_hourly = data.get("air_quality", {}).get("hourly", {})

        times = weather_hourly.get("time", [])
        if not times:
            raise ValueError("Aucune donnée horaire météo disponible.")

        weather_df = pd.DataFrame({"Date et heure": times})

        for key, label in WEATHER_LABELS.items():
            values = weather_hourly.get(key, [])
            if len(values) == len(times):
                weather_df[label] = values

        air_times = air_hourly.get("time", [])
        if air_times:
            air_df = pd.DataFrame({"Date et heure": air_times})

            for key, label in AIR_LABELS.items():
                values = air_hourly.get(key, [])
                if len(values) == len(air_times):
                    air_df[label] = values

            weather_df = weather_df.merge(
                air_df,
                on="Date et heure",
                how="left",
            )

        weather_df["Date et heure"] = pd.to_datetime(
            weather_df["Date et heure"],
            errors="coerce",
        )
        return weather_df

    @staticmethod
    def calculate_summary(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """Calcule moyenne, minimum et maximum pour chaque colonne numérique."""
        summary: Dict[str, Dict[str, float]] = {}

        for column in df.columns:
            if column == "Date et heure":
                continue

            values = pd.to_numeric(df[column], errors="coerce").dropna()
            if not values.empty:
                summary[column] = {
                    "moyenne": round(float(values.mean()), 2),
                    "minimum": round(float(values.min()), 2),
                    "maximum": round(float(values.max()), 2),
                }

        return summary

    def build_city_overview(
        self,
        city_data: Dict[str, Dict[str, Any]],
    ) -> pd.DataFrame:
        """
        Crée un tableau de synthèse par ville avec les valeurs disponibles
        les plus proches de l'heure actuelle.
        """
        rows: List[Dict[str, Any]] = []

        for city, data in city_data.items():
            if "error" in data:
                rows.append({"Ville": city, "Erreur": data["error"]})
                continue

            weather = data.get("weather", {})
            air = data.get("air_quality", {})
            weather_hourly = weather.get("hourly", {})
            air_hourly = air.get("hourly", {})

            weather_index = self._nearest_time_index(weather_hourly.get("time", []))
            air_index = self._nearest_time_index(air_hourly.get("time", []))

            row: Dict[str, Any] = {"Ville": city}

            for key, label in WEATHER_LABELS.items():
                row[label] = self._value_at(weather_hourly, key, weather_index)

            for key, label in AIR_LABELS.items():
                row[label] = self._value_at(air_hourly, key, air_index)

            rows.append(row)

        return pd.DataFrame(rows)

    @staticmethod
    def _nearest_time_index(times: List[str]) -> Optional[int]:
        """Retourne l'index de l'heure la plus proche de l'heure actuelle."""
        if not times:
            return None

        now = datetime.datetime.now()
        parsed = []

        for index, value in enumerate(times):
            try:
                dt = datetime.datetime.fromisoformat(value)
                parsed.append((index, dt))
            except (ValueError, TypeError):
                continue

        if not parsed:
            return 0

        # Les chaînes horaires Open-Meteo sont locales au fuseau renvoyé.
        now_naive = now.replace(tzinfo=None)
        return min(
            parsed,
            key=lambda item: abs(
                (item[1].replace(tzinfo=None) - now_naive).total_seconds()
            ),
        )[0]

    @staticmethod
    def _value_at(
        hourly_data: Dict[str, Any],
        key: str,
        index: Optional[int],
    ) -> Optional[Any]:
        values = hourly_data.get(key, [])
        if index is None or index >= len(values):
            return None
        return values[index]

    # --------------------------------------------------
    # 12. EXPORTATION CSV
    # --------------------------------------------------

    def export_csv(
        self,
        data: Dict[str, Any],
        city: str = "Ville inconnue",
    ) -> bytes:
        """Génère un CSV de toutes les données horaires pour une ville."""
        df = self.prepare_city_dataframe(data)
        df.insert(0, "Ville", city)

        # utf-8-sig facilite l'ouverture des caractères accentués dans Excel.
        output = io.StringIO(newline="")
        df.to_csv(output, index=False, sep=";", quoting=csv.QUOTE_MINIMAL)
        return output.getvalue().encode("utf-8-sig")

    # --------------------------------------------------
    # 13. EXPORTATION PDF
    # --------------------------------------------------

    def export_pdf(
        self,
        data: Dict[str, Any],
        city: str = "Ville inconnue",
    ) -> bytes:
        """
        Génère un PDF avec les statistiques et les 24 premières heures.
        ReportLab est importé ici pour que le client API reste utilisable
        sans cette dépendance si l'export PDF n'est pas appelé.
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Pour exporter en PDF, installe ReportLab : pip install reportlab"
            ) from exc

        df = self.prepare_city_dataframe(data)
        summary = self.calculate_summary(df)

        buffer = io.BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=1.2 * cm,
            leftMargin=1.2 * cm,
            topMargin=1.2 * cm,
            bottomMargin=1.2 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1F4E79"),
            spaceAfter=12,
        )

        story = [
            Paragraph("Rapport météo et qualité de l'air", title_style),
            Paragraph(f"Ville : {city}", styles["Normal"]),
            Paragraph(
                "Généré le : "
                + datetime.datetime.now().strftime("%d/%m/%Y à %H:%M"),
                styles["Normal"],
            ),
            Spacer(1, 12),
            Paragraph("1. Synthèse des indicateurs", styles["Heading2"]),
        ]

        summary_rows = [["Indicateur", "Moyenne", "Minimum", "Maximum"]]
        for label, stats in summary.items():
            summary_rows.append([
                label,
                str(stats["moyenne"]),
                str(stats["minimum"]),
                str(stats["maximum"]),
            ])

        if len(summary_rows) == 1:
            summary_rows.append(["Aucune statistique disponible", "-", "-", "-"])

        summary_table = Table(summary_rows, repeatRows=1, hAlign="LEFT")
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#EAF2F8")]),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([summary_table, Spacer(1, 16)])
        story.append(Paragraph("2. Données horaires", styles["Heading2"]))

        display_df = df.head(24).copy()
        table_data = [[str(column)[:24] for column in display_df.columns]]

        for row in display_df.itertuples(index=False, name=None):
            table_data.append([
                "-" if pd.isna(value) else str(value)
                for value in row
            ])

        hourly_table = Table(table_data, repeatRows=1, hAlign="LEFT")
        hourly_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874A6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(hourly_table)

        if len(df) > 24:
            story.extend([
                Spacer(1, 8),
                Paragraph(
                    "Le PDF affiche les 24 premières lignes. "
                    "Le CSV contient toutes les données horaires.",
                    styles["Italic"],
                ),
            ])

        document.build(story)
        return buffer.getvalue()

    # --------------------------------------------------
    # 14. DONNÉES SIMULÉES POUR LES TESTS
    # --------------------------------------------------

    def _generate_mock_data(
        self,
        lat: float,
        lon: float,
    ) -> Dict[str, Any]:
        """Génère des données fictives pour tester le tableau de bord."""
        now = datetime.datetime.now().replace(
            minute=0,
            second=0,
            microsecond=0,
        )

        times = [
            (now - datetime.timedelta(hours=i)).isoformat(timespec="minutes")
            for i in range(24 * 7 - 1, -1, -1)
        ]
        count = len(times)

        weather = {
            "latitude": lat,
            "longitude": lon,
            "timezone": "auto",
            "hourly": {
                "time": times,
                "temperature_2m": np.random.uniform(5, 35, count).round(1).tolist(),
                "relative_humidity_2m": np.random.randint(30, 95, count).tolist(),
                "surface_pressure": np.random.uniform(990, 1030, count).round(1).tolist(),
                "wind_speed_10m": np.random.uniform(0, 30, count).round(1).tolist(),
            },
        }

        air_quality = {
            "latitude": lat,
            "longitude": lon,
            "timezone": "auto",
            "hourly": {
                "time": times,
                "pm2_5": np.random.uniform(2, 40, count).round(1).tolist(),
                "pm10": np.random.uniform(5, 60, count).round(1).tolist(),
                "nitrogen_dioxide": np.random.uniform(2, 55, count).round(1).tolist(),
                "ozone": np.random.uniform(10, 100, count).round(1).tolist(),
                "sulphur_dioxide": np.random.uniform(1, 20, count).round(1).tolist(),
                "carbon_monoxide": np.random.uniform(100, 1000, count).round(1).tolist(),
                "us_aqi": np.random.randint(0, 151, count).tolist(),
            },
        }

        return {"weather": weather, "air_quality": air_quality}

    # --------------------------------------------------
    # 15. FERMETURE DU CLIENT
    # --------------------------------------------------

    def close(self) -> None:
        """Ferme la session HTTP."""
        self.session.close()
