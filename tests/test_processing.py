
import pandas as pd

from src.data_processing import DataProcessor

from src.alerts import detect_alerts, detect_who_alerts


def test_calculate_statistics():
    # On prépare trois mesures météo fictives
    df = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2026-10-20 08:00",
            "2026-10-20 09:00",
            "2026-10-20 10:00"
        ]),
        "temperature_2m": [18, 20, 22],
        "relative_humidity_2m": [60, 65, 70],
        "pm2_5": [8, 12, 16],
        "pm10": [15, 20, 25],
        "nitrogen_dioxide": [10, 15, 20],
        "ozone": [40, 50, 60]
    })

    # On appelle notre fonction
    resultat = DataProcessor.calculate_statistics(df, n_hours=3)

    # On vérifie les résultats attendus
    assert resultat["temperature_moyenne"] == 20
    assert resultat["temperature_mediane"] == 20
    assert resultat["humidite_moyenne"] == 65
    assert resultat["pm25_moyenne"] == 12


def test_calculate_trend():
    df = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2026-10-20 08:00",
            "2026-10-20 09:00",
            "2026-10-20 10:00"
        ]),
        "temperature_2m": [18, 20, 22]
    })

    resultat = DataProcessor.calculate_trend(
        df, "temperature_2m", n_hours=24
    )

    assert resultat == 4


def test_calculate_custom_health_index():
    df = pd.DataFrame({
        "temperature_2m": [21, 35],
        "relative_humidity_2m": [50, 80],
        "pm2_5": [5, 30]
    })

    scores = DataProcessor.calculate_custom_health_index(df)

    assert len(scores) == 2
    assert scores.iloc[0] > scores.iloc[1]
    assert scores.between(0, 100).all()


def test_detect_alerts():
    df = pd.DataFrame({
        "temperature_2m": [40],
        "pm2_5": [30],
        "nitrogen_dioxide": [60]
    })

    alertes = detect_alerts(df)

    assert len(alertes) > 0
    assert any(
        alerte["level"] == "danger"
        for alerte in alertes
    )


def test_process_raw_api_data():
    # Données fictives provenant des deux API
    raw_data = {
        "weather": {
            "hourly": {
                "time": [
                    "2026-10-20T09:00",
                    "2026-10-20T08:00",
                    "2026-10-20T08:00"
                ],
                "temperature_2m": [20, 18, 18]
            }
        },
        "air_quality": {
            "hourly": {
                "time": [
                    "2026-10-20T08:00",
                    "2026-10-20T09:00"
                ],
                "pm2_5": [8, 12]
            }
        }
    }

    # Appel de notre fonction
    resultat = DataProcessor.process_raw_api_data(raw_data)

    # Vérifier que les données sont fusionnées
    assert "temperature_2m" in resultat.columns
    assert "pm2_5" in resultat.columns

    # Vérifier la suppression des doublons
    assert len(resultat) == 2

    # Vérifier l'ordre chronologique
    assert resultat["datetime"].is_monotonic_increasing

    # Vérifier que les données correspondent
    assert resultat["temperature_2m"].iloc[0] == 18
    assert resultat["pm2_5"].iloc[0] == 8

[{
	"resource": "/c:/Users/klhoe/OneDrive/Documents/Travaux/Meteo/dashboard_M-teo/src/data_processing.py",
	"owner": "Pylance",
	"code": {
		"value": "reportUndefinedVariable",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportUndefinedVariable.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 4,
	"message": "« DataProcessor » n’est pas défini",
	"source": "Pylance",
	"startLineNumber": 200,
	"startColumn": 14,
	"endLineNumber": 200,
	"endColumn": 27,
	"modelVersionId": 53,
	"origin": "extHost1"
}]


def test_health_index_uses_apparent_temperature():
    # Deux situations avec la même température réelle
    df = pd.DataFrame({
        "temperature_2m": [21, 21],
        "apparent_temperature": [21, 35],
        "relative_humidity_2m": [50, 50],
        "pm2_5": [5, 5]
    })

    # Calcul de l'indice de confort
    scores = DataProcessor.calculate_custom_health_index(df)

    # La température ressentie élevée doit réduire le confort
    assert scores.iloc[0] > scores.iloc[1]

    # Vérifier les résultats exacts
    assert scores.iloc[0] == 94.0
    assert scores.iloc[1] == 73.0


def test_detect_alerts_all_indicators():
    # Dernières mesures avec différents dépassements
    df = pd.DataFrame({
        "temperature_2m": [40],
        "pm2_5": [30],
        "pm10": [47],
        "nitrogen_dioxide": [30]
    })

    alertes = detect_alerts(df)

    # Les quatre indicateurs doivent produire une alerte
    assert len(alertes) == 4

    # Deux dangers : température et PM2.5
    dangers = [
        alerte for alerte in alertes
        if alerte["level"] == "danger"
    ]
    assert len(dangers) == 2

    # Deux vigilances : PM10 et NO2
    vigilances = [
        alerte for alerte in alertes
        if alerte["level"] == "warning"
    ]
    assert len(vigilances) == 2


def test_detect_who_alerts():
    # 24 mesures horaires consécutives
    df = pd.DataFrame({
        "datetime": pd.date_range(
            "2026-10-20 00:00",
            periods=24,
            freq="h"
        ),
        "pm2_5": [20] * 24,
        "pm10": [30] * 24,
        "nitrogen_dioxide": [30] * 24
    })

    alertes = detect_who_alerts(df)

    # PM2.5 et NO2 dépassent leurs valeurs guides
    assert len(alertes) == 2

    assert any(
        "PM2.5" in alerte["message"]
        for alerte in alertes
    )

    assert any(
        "NO₂" in alerte["message"]
        for alerte in alertes
    )

    # PM10 reste sous sa valeur guide
    assert not any(
        "PM10" in alerte["message"]
        for alerte in alertes
    )


def test_who_alerts_incomplete_data():
    # Seulement 10 heures de mesures
    df = pd.DataFrame({
        "datetime": pd.date_range(
            "2026-10-20 08:00",
            periods=10,
            freq="h"
        ),
        "pm2_5": [30] * 10,
        "pm10": [60] * 10,
        "nitrogen_dioxide": [40] * 10
    })

    alertes = detect_who_alerts(df)

    # Aucune comparaison sur 24 h avec seulement 10 mesures
    assert alertes == []


def test_who_alerts_missing_hour():
    # 25 heures possibles, mais on retire une heure
    dates = pd.date_range(
        "2026-10-19 10:00",
        periods=25,
        freq="h"
    ).delete(12)

    df = pd.DataFrame({
        "datetime": dates,
        "pm2_5": [30] * 24,
        "pm10": [60] * 24,
        "nitrogen_dioxide": [40] * 24
    })

    alertes = detect_who_alerts(df)

    # Il manque une heure dans les dernières 24 heures
    assert alertes == []

def test_statistics_missing_pollution_data():
    df = pd.DataFrame({
        "datetime": pd.date_range(
            "2026-10-20",
            periods=24,
            freq="h"
        ),
        "temperature_2m": [20.0] * 24,
        "relative_humidity_2m": [50.0] * 24,
        "pm2_5": [float("nan")] * 24,
        "pm10": [10.0] * 24,
        "nitrogen_dioxide": [5.0] * 24,
        "ozone": [30.0] * 24
    })

    resultat = DataProcessor.calculate_statistics(
        df,
        n_hours=24
    )

    assert resultat["temperature_moyenne"] == 20.0
    assert pd.isna(resultat["pm25_moyenne"])

def test_statistics_24h_vs_7days():
    # Création de 7 jours de données horaires
    dates = pd.date_range(
        "2026-10-01",
        periods=168,
        freq="h"
    )

    # Les 6 premiers jours : 10 °C
    # Le dernier jour : 30 °C
    temperatures = [10.0] * 144 + [30.0] * 24

    df = pd.DataFrame({
        "datetime": dates,
        "temperature_2m": temperatures,
        "relative_humidity_2m": [50.0] * 168,
        "pm2_5": [10.0] * 168,
        "pm10": [20.0] * 168,
        "nitrogen_dioxide": [5.0] * 168,
        "ozone": [30.0] * 168
    })

    stats_24h = DataProcessor.calculate_statistics(
        df, n_hours=24
    )

    stats_7j = DataProcessor.calculate_statistics(
        df, n_hours=168
    )

    assert stats_24h["temperature_moyenne"] == 30.0

    assert round(
        stats_7j["temperature_moyenne"], 2
    ) == 12.86

def test_health_index_missing_pm25():
    df = pd.DataFrame({
        "temperature_2m": [22.0, 25.0],
        "apparent_temperature": [24.0, 28.0],
        "relative_humidity_2m": [50.0, 60.0],
        "pm2_5": [10.0, float("nan")]
    })

    scores = DataProcessor.calculate_custom_health_index(df)

    # Première mesure : toutes les données sont présentes
    assert scores.iloc[0] == 83.5

    # Deuxième mesure : PM2.5 manquant
    assert pd.isna(scores.iloc[1])

def test_cleaning_invalid_data():
    raw_data = {
        "weather": {
            "hourly": {
                "time": [
                    "2026-10-20T10:00",
                    "2026-10-20T11:00",
                    "2026-10-20T12:00"
                ],
                "temperature_2m": [20, 21, 22],
                "relative_humidity_2m": [50, 150, 60]
            }
        },
        "air_quality": {
            "hourly": {
                "time": [
                    "2026-10-20T10:00",
                    "2026-10-20T11:00",
                    "2026-10-20T12:00"
                ],
                "pm2_5": [10, -5, 15],
                "pm10": [20, 25, -10],
                "nitrogen_dioxide": [5, 10, 15],
                "ozone": [30, 40, 50]
            }
        }
    }

    df = DataProcessor.process_raw_api_data(raw_data)

    # Les trois lignes doivent être conservées
    assert len(df) == 3

    # L'humidité à 150 % est invalide
    assert pd.isna(df.loc[1, "relative_humidity_2m"])

    # Une concentration de PM2.5 négative est invalide
    assert pd.isna(df.loc[1, "pm2_5"])

    # Une concentration de PM10 négative est invalide
    assert pd.isna(df.loc[2, "pm10"])

    # Les valeurs valides restent inchangées
    assert df.loc[0, "temperature_2m"] == 20
    assert df.loc[0, "pm2_5"] == 10