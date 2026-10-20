
from typing import Dict, List

import pandas as pd


# Seuils de vigilance et de danger choisis pour le projet.
# Ils servent aux alertes sur les dernières mesures disponibles.
# Ils ne représentent pas tous des seuils officiels de l'OMS.
THRESHOLDS = {
    "pm2_5": {"warning": 15.0, "danger": 25.0, "unit": "µg/m³"},
    "pm10": {"warning": 45.0, "danger": 50.0, "unit": "µg/m³"},
    "no2": {"warning": 25.0, "danger": 50.0, "unit": "µg/m³"},
    "temp_max": {"warning": 33.0, "danger": 38.0, "unit": "°C"}
}


def detect_alerts(df: pd.DataFrame) -> List[Dict[str, str]]:
    """Détecte les dépassements de seuils sur la dernière mesure."""

    alerts = []

    # Vérifier si le DataFrame est vide
    if df.empty:
        return alerts

    # Prendre la mesure la plus récente
    if "datetime" in df.columns:
        latest = df.sort_values("datetime").iloc[-1]
    else:
        latest = df.iloc[-1]

    # Indicateurs à surveiller :
    # (colonne du DataFrame, seuil, nom affiché)
    indicateurs = [
        ("pm2_5", "pm2_5", "PM2.5"),
        ("pm10", "pm10", "PM10"),
        ("nitrogen_dioxide", "no2", "NO₂"),
        ("temperature_2m", "temp_max", "Température")
    ]

    for colonne, seuil, nom in indicateurs:

        # Ignorer les mesures absentes
        if colonne not in latest.index:
            continue

        valeur = pd.to_numeric(latest[colonne], errors="coerce")

        if pd.isna(valeur):
            continue

        # Récupérer les seuils de l'indicateur
        seuil_warning = THRESHOLDS[seuil]["warning"]
        seuil_danger = THRESHOLDS[seuil]["danger"]
        unite = THRESHOLDS[seuil]["unit"]

        # Vérifier le niveau de danger en premier
        if valeur >= seuil_danger:
            alerts.append({
                "level": "danger",
                "message": (
                    f"Danger {nom} : {valeur:.1f} {unite} "
                    f"(seuil du projet : {seuil_danger} {unite})"
                )
            })

        # Sinon, vérifier le niveau de vigilance
        elif valeur >= seuil_warning:
            alerts.append({
                "level": "warning",
                "message": (
                    f"Vigilance {nom} : {valeur:.1f} {unite} "
                    f"(seuil du projet : {seuil_warning} {unite})"
                )
            })

    return alerts


def detect_who_alerts(df: pd.DataFrame) -> List[Dict[str, str]]:
    """Compare les moyennes sur 24 h aux valeurs guides OMS."""

    alerts = []

    if df.empty or "datetime" not in df.columns:
        return alerts

    # Préparer les dates et conserver les mesures valides
    data = df.copy()
    data["datetime"] = pd.to_datetime(
        data["datetime"], errors="coerce"
    )
    data = data.dropna(subset=["datetime"])

    if data.empty:
        return alerts

    # Définir les dernières 24 heures
    fin = data["datetime"].max()
    debut = fin - pd.Timedelta(hours=24)

    data = data[
        (data["datetime"] > debut)
        & (data["datetime"] <= fin)
    ].copy()

    # Conserver une seule mesure par heure
    data["heure"] = data["datetime"].dt.floor("h")
    data = data.sort_values("datetime")
    data = data.drop_duplicates(subset=["heure"], keep="last")

    # Valeurs guides OMS sur 24 heures
    seuils_oms = {
        "pm2_5": ("PM2.5", 15.0),
        "pm10": ("PM10", 45.0),
        "nitrogen_dioxide": ("NO₂", 25.0)
    }

    for colonne, (nom, seuil) in seuils_oms.items():

        if colonne not in data.columns:
            continue

        valeurs = pd.to_numeric(
            data[colonne], errors="coerce"
        )

        # Vérifier que les 24 heures attendues sont présentes
        heures_attendues = pd.date_range(
            end=fin.floor("h"),
            periods=24,
            freq="h"
        )

        heures_presentes = pd.DatetimeIndex(
            data.loc[valeurs.notna(), "heure"]
        )

        if not heures_attendues.isin(heures_presentes).all():
            continue

        moyenne = valeurs.mean()

        if moyenne > seuil:
            alerts.append({
                "level": "warning",
                "message": (
                    f"Moyenne 24 h {nom} : {moyenne:.1f} µg/m³ "
                    f"(valeur guide OMS : {seuil} µg/m³)"
                )
            })

    return alerts
