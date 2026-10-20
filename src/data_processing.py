
from typing import Dict, Any

import pandas as pd
import numpy as np


class DataProcessor:

    @staticmethod
    def process_raw_api_data(raw_data: Dict[str, Any]) -> pd.DataFrame:
        """Transforme et nettoie les données reçues des API."""

        # 1. Récupérer les données des deux API
        w_hourly = raw_data.get("weather", {}).get("hourly", {})
        a_hourly = raw_data.get("air_quality", {}).get("hourly", {})

        # 2. Transformer les données en DataFrames
        df_weather = pd.DataFrame(w_hourly)
        df_air = pd.DataFrame(a_hourly)

        # 3. Vérifier si les données sont vides
        if df_weather.empty or df_air.empty:
            return pd.DataFrame()

        # Vérifier la présence de la colonne time
        if "time" not in df_weather.columns or "time" not in df_air.columns:
            return pd.DataFrame()

        # 4. Fusionner les données météo et pollution
        df = pd.merge(df_weather, df_air, on="time", how="inner")

        if df.empty:
            return df

        # 5. Convertir les dates
        df["datetime"] = pd.to_datetime(
            df["time"], errors="coerce"
        )

        # Supprimer les lignes avec des dates invalides
        df.dropna(subset=["datetime"], inplace=True)

        # 6. Convertir les mesures en nombres
        colonnes_numeriques = [
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "pm2_5",
            "pm10",
            "nitrogen_dioxide",
            "ozone"
        ]

        for colonne in colonnes_numeriques:
            if colonne in df.columns:
                df[colonne] = pd.to_numeric(
                    df[colonne], errors="coerce"
                )

        # 7. Corriger les valeurs incohérentes

        # L'humidité doit être comprise entre 0 et 100 %
        if "relative_humidity_2m" in df.columns:
            humidite = df["relative_humidity_2m"]

            df.loc[
                ~humidite.between(0, 100),
                "relative_humidity_2m"
            ] = np.nan

        # Les concentrations de polluants ne peuvent pas être négatives
        polluants = [
            "pm2_5",
            "pm10",
            "nitrogen_dioxide",
            "ozone"
        ]

        for colonne in polluants:
            if colonne in df.columns:
                df.loc[df[colonne] < 0, colonne] = np.nan

        # 8. Trier les mesures chronologiquement
        df.sort_values("datetime", inplace=True)

        # 9. Supprimer les doublons
        df.drop_duplicates(subset=["time"], inplace=True)

        # Réinitialiser les index
        df.reset_index(drop=True, inplace=True)

        return df

    @staticmethod
    def calculate_statistics(df, n_hours=24):
        """Calcule les statistiques sur une période donnée."""

        if df.empty:
            return {}

        # Trier les données
        df = df.sort_values("datetime")

        # Sélectionner les N dernières heures réelles
        derniere_date = df["datetime"].max()
        debut = derniere_date - pd.Timedelta(hours=n_hours)

        recent_data = df[
            (df["datetime"] > debut)
            & (df["datetime"] <= derniere_date)
        ]

        # Calculer les statistiques
        statistiques = {
            "temperature_moyenne": recent_data["temperature_2m"].mean(),
            "temperature_mediane": recent_data["temperature_2m"].median(),
            "humidite_moyenne": recent_data["relative_humidity_2m"].mean(),
            "pm25_moyenne": recent_data["pm2_5"].mean(),
            "pm25_mediane": recent_data["pm2_5"].median(),
            "pm10_moyenne": recent_data["pm10"].mean(),
            "no2_moyenne": recent_data["nitrogen_dioxide"].mean(),
            "ozone_moyenne": recent_data["ozone"].mean()
        }

        return statistiques

    @staticmethod
    def calculate_trend(df, column, n_hours=24):
        """Calcule l'évolution d'une mesure sur N heures."""

        if df.empty or column not in df.columns:
            return None

        # Trier les données par date
        recent_data = df.sort_values("datetime")

        # Définir la période à analyser
        derniere_date = recent_data["datetime"].max()
        debut = derniere_date - pd.Timedelta(hours=n_hours)

        # Garder les mesures de la période
        recent_data = recent_data[
            recent_data["datetime"] >= debut
        ]

        # Supprimer les valeurs manquantes
        valeurs = recent_data.dropna(subset=[column])

        if len(valeurs) < 2:
            return None

        # Calculer la variation
        premiere_valeur = valeurs[column].iloc[0]
        derniere_valeur = valeurs[column].iloc[-1]

        tendance = derniere_valeur - premiere_valeur

        return tendance

    @staticmethod
    def calculate_custom_health_index(df: pd.DataFrame) -> pd.Series:
        """Calcule un score de confort entre 0 et 100."""

        # Utiliser la température ressentie si elle est disponible
        if "apparent_temperature" in df.columns:
            temp = df["apparent_temperature"].fillna(
                df["temperature_2m"]
            )
        else:
            temp = df["temperature_2m"]

        humidity = df["relative_humidity_2m"]
        pm2_5 = df["pm2_5"]

        # Calcul des pénalités
        temp_penalty = np.abs(temp - 21.0) * 1.5
        humidity_penalty = np.abs(humidity - 50.0) * 0.3
        pollution_penalty = pm2_5 * 1.2

        # Calcul du score final
        score = 100 - (
            temp_penalty
            + humidity_penalty
            + pollution_penalty
        )

        return score.clip(0, 100).round(1)

    


      