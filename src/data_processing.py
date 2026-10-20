from typing import Dict, Any

import pandas as pd
import numpy as np
"""
    Data Transformation, Calculations, and Alert Engine.
    Author: Student B (Data Analyst)
    """
class DataProcessor:
    @staticmethod
    def process_raw_api_data(raw_data: Dict[str, Any]) -> pd.DataFrame:
        """Transforms raw API responses into a clean Pandas DataFrame."""
        w_hourly = raw_data.get("weather", {}).get("hourly", {})
        a_hourly = raw_data.get("air_quality", {}).get("hourly", {})

        df_weather = pd.DataFrame(w_hourly)
        df_air = pd.DataFrame(a_hourly)

        if df_weather.empty or df_air.empty:
            return pd.DataFrame()

        df = pd.merge(df_weather, df_air, on="time", how="inner")
        df["datetime"] = pd.to_datetime(df["time"])
        df.sort_values("datetime", inplace=True)
        df.drop_duplicates(subset=["time"], inplace=True) #supprime les mesures qui possèdent le même horodatage, afin de ne pas compter deux fois la même heure dans nos statistiques
        return df

    @staticmethod
    def calculate_statistics(df, n_hours=24):
        if df.empty: #vérifie si le tableau est vide
            return{}

        # Sélectionner les N dernières mesures horaires
        recent_data = df.sort_values("datetime").tail(n_hours)

        # Calculer les statistiques
        statistiques = {
            # Statistiques météo
            "temperature_moyenne": recent_data["temperature_2m"].mean(),
            "temperature_mediane": recent_data["temperature_2m"].median(),
            "humidite_moyenne": recent_data["relative_humidity_2m"].mean(),

            # Statistiques pollution
            "pm25_moyenne": recent_data["pm2_5"].mean(),
            "pm25_mediane": recent_data["pm2_5"].median(),
            "pm10_moyenne": recent_data["pm10"].mean(),
            "no2_moyenne": recent_data["nitrogen_dioxide"].mean(),
            "ozone_moyenne": recent_data["ozone"].mean()
        }

        return statistiques

    
    @staticmethod
    def calculate_trend(df, column, n_hours=24):

        # Vérifier si le tableau contient des données
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

        return tendance #renvoie la différence entre les deux valeurs


    @staticmethod
    def calculate_custom_health_index(df: pd.DataFrame) -> pd.Series:
        """
        Calculates a custom composite Comfort/Health Score (0-100 scale).
        Higher is better.
        """
        temp = df["temperature_2m"]
        humidity = df["relative_humidity_2m"]
        pm2_5 = df["pm2_5"]

        # Penalty factors based on optimal comfort conditions
        temp_penalty = np.abs(temp - 21.0) * 1.5
        humidity_penalty = np.abs(humidity - 50.0) * 0.3 #np.abs() calcule la valeur absolue
        pollution_penalty = pm2_5 * 1.2

        score = 100 - (temp_penalty + humidity_penalty + pollution_penalty)
        return score.clip(0, 100).round(1)

    