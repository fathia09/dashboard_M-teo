
import pandas as pd

from src.data_processing import DataProcessor

from src.alerts import detect_alerts


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
