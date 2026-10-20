import sqlite3
import datetime
import json
import logging
from typing import Any, Dict, Optional

import requests
import numpy as np


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

CACHE_DB = "data_cache.db"
CACHE_TTL_MINUTES = 30

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

REQUEST_TIMEOUT = 10


# --------------------------------------------------
# 2. CLIENT API
# --------------------------------------------------

class WeatherAPIClient:
    """Gère les API, le géocodage, le cache et les erreurs."""

    def __init__(
        self,
        db_path: str = CACHE_DB,
        cache_ttl_minutes: int = CACHE_TTL_MINUTES
    ):
        self.db_path = db_path
        self.cache_ttl_minutes = cache_ttl_minutes

        # Réutilise une session HTTP pour les requêtes.
        self.session = requests.Session()

        # Crée la table SQLite si elle n'existe pas.
        self._init_db()

    # --------------------------------------------------
    # 3. INITIALISATION DU CACHE SQLITE
    # --------------------------------------------------

    def _init_db(self) -> None:
        """Crée la table qui stocke les réponses des API."""

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_cache (
                        key TEXT PRIMARY KEY,
                        response TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                """)

            logging.info("Cache SQLite initialisé.")

        except sqlite3.Error:
            logging.exception("Impossible d'initialiser le cache SQLite.")
            raise

    # --------------------------------------------------
    # 4. LECTURE DU CACHE
    # --------------------------------------------------

    def _get_cached_data(
        self,
        key: str
    ) -> Optional[Dict[str, Any]]:
        """Retourne les données en cache si elles sont encore valides."""

        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT response, timestamp
                    FROM api_cache
                    WHERE key = ?
                    """,
                    (key,)
                ).fetchone()

            if row is None:
                return None

            response_json, timestamp_text = row

            timestamp = datetime.datetime.fromisoformat(
                timestamp_text
            )

            age = datetime.datetime.now() - timestamp
            ttl = datetime.timedelta(
                minutes=self.cache_ttl_minutes
            )

            # Si le cache est expiré, on ne l'utilise pas.
            if age >= ttl:
                logging.info("Cache expiré : %s", key)
                return None

            logging.info("Cache utilisé : %s", key)

            return json.loads(response_json)

        except (
            sqlite3.Error,
            ValueError,
            TypeError,
            json.JSONDecodeError
        ):
            logging.exception("Erreur lors de la lecture du cache.")
            return None

    # --------------------------------------------------
    # 5. ÉCRITURE DANS LE CACHE
    # --------------------------------------------------

    def _set_cached_data(
        self,
        key: str,
        data: Dict[str, Any]
    ) -> None:
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
                    (key, response_json, timestamp)
                )

            logging.info("Données mises en cache : %s", key)

        except (sqlite3.Error, TypeError, ValueError):
            # Une panne du cache ne doit pas masquer
            # une réponse API déjà obtenue.
            logging.exception("Impossible d'enregistrer le cache.")

    # --------------------------------------------------
    # 6. GÉOCODAGE : NOM DE VILLE -> COORDONNÉES
    # --------------------------------------------------

    def geocode_city(
        self,
        city: str,
        country_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Recherche une ville et retourne son nom,
        son pays, sa latitude et sa longitude.
        """

        city = city.strip()

        if not city:
            raise ValueError("Le nom de la ville est obligatoire.")

        # La clé tient compte du nom et du pays demandé.
        cache_key = f"geocode:{city.lower()}:{country_code or ''}"

        cached = self._get_cached_data(cache_key)

        if cached is not None:
            return cached

        params = {
            "name": city,
            "count": 10,
            "language": "fr",
            "format": "json"
        }

        if country_code:
            params["countryCode"] = country_code.upper()

        try:
            response = self.session.get(
                GEOCODING_URL,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()
            payload = response.json()

            results = payload.get("results", [])

            if not results:
                raise ValueError(
                    f"Aucune ville trouvée pour : {city}"
                )

            # Prend le premier résultat proposé par l'API.
            place = results[0]

            location = {
                "name": place.get("name", city),
                "country": place.get("country", ""),
                "country_code": place.get("country_code", ""),
                "latitude": place["latitude"],
                "longitude": place["longitude"]
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

    def _fetch_weather(
        self,
        lat: float,
        lon: float
    ) -> Dict[str, Any]:
        """Récupère les données météo horaires."""

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
            "timezone": "auto"
        }

        response = self.session.get(
            WEATHER_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    # --------------------------------------------------
    # 8. RÉCUPÉRATION QUALITÉ DE L'AIR
    # --------------------------------------------------

    def _fetch_air_quality(
        self,
        lat: float,
        lon: float
    ) -> Dict[str, Any]:
        """Récupère les données horaires de qualité de l'air."""

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
            "timezone": "auto"
        }

        response = self.session.get(
            AIR_QUALITY_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    # --------------------------------------------------
    # 9. RÉCUPÉRATION DES DEUX TYPES DE DONNÉES
    # --------------------------------------------------

    def fetch_weather_and_air_quality(
        self,
        lat: float,
        lon: float,
        mock_mode: bool = False
    ) -> Dict[str, Any]:
        """
        Retourne météo + qualité de l'air.

        Utilise le cache, les API ou des données simulées.
        """

        if not -90 <= lat <= 90:
            raise ValueError("La latitude doit être comprise entre -90 et 90.")

        if not -180 <= lon <= 180:
            raise ValueError("La longitude doit être comprise entre -180 et 180.")

        cache_key = f"weather_air:{lat:.4f}:{lon:.4f}"

        # Mode de démonstration : aucune requête API.
        if mock_mode:
            return self._generate_mock_data(lat, lon)

        # Vérifie si les données existent déjà dans le cache.
        cached = self._get_cached_data(cache_key)

        if cached is not None:
            return cached

        try:
            weather_data = self._fetch_weather(lat, lon)
            air_data = self._fetch_air_quality(lat, lon)

            # Les deux réponses sont regroupées.
            result = {
                "weather": weather_data,
                "air_quality": air_data
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
            # Par exemple, réponse JSON invalide.
            logging.exception("Réponse API invalide.")
            raise RuntimeError(
                "Les données reçues des API sont invalides."
            ) from exc

    # --------------------------------------------------
    # 10. DONNÉES SIMULÉES POUR LES TESTS
    # --------------------------------------------------

    def _generate_mock_data(
        self,
        lat: float,
        lon: float
    ) -> Dict[str, Any]:
        """Génère des données fictives pour tester le tableau de bord."""

        now = datetime.datetime.now().replace(
            minute=0, second=0, microsecond=0
        )

        times = [
            (now - datetime.timedelta(hours=i)).isoformat(
                timespec="minutes"
            )
            for i in range(24 * 7 - 1, -1, -1)
        ]

        count = len(times)

        weather = {
            "latitude": lat,
            "longitude": lon,
            "hourly": {
                "time": times,
                "temperature_2m": np.random.uniform(
                    5, 35, count
                ).round(1).tolist(),
                "relative_humidity_2m": np.random.randint(
                    30, 95, count
                ).tolist(),
                "surface_pressure": np.random.uniform(
                    990, 1030, count
                ).round(1).tolist(),
                "wind_speed_10m": np.random.uniform(
                    0, 30, count
                ).round(1).tolist()
            }
        }

        air_quality = {
            "latitude": lat,
            "longitude": lon,
            "hourly": {
                "time": times,
                "pm2_5": np.random.uniform(
                    2, 40, count
                ).round(1).tolist(),
                "pm10": np.random.uniform(
                    5, 60, count
                ).round(1).tolist(),
                "nitrogen_dioxide": np.random.uniform(
                    2, 55, count
                ).round(1).tolist(),
                "ozone": np.random.uniform(
                    10, 100, count
                ).round(1).tolist(),
                "sulphur_dioxide": np.random.uniform(
                    1, 20, count
                ).round(1).tolist(),
                "carbon_monoxide": np.random.uniform(
                    100, 1000, count
                ).round(1).tolist(),
                "us_aqi": np.random.randint(
                    0, 151, count
                ).tolist()
            }
        }

        return {
            "weather": weather,
            "air_quality": air_quality
        }

    # --------------------------------------------------
    # 11. FERMETURE DU CLIENT
    # --------------------------------------------------

    def close(self) -> None:
        """Ferme la session HTTP."""

        self.session.close()
