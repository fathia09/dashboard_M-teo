import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from alerts import detect_alerts, detect_who_alerts
from api_client import WeatherAPIClient
from data_processing import DataProcessor


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Dashboard Météo & AQI",
    page_icon="🌤️",
    layout="wide"
)

st.title("🌤️ Dashboard Météo & Surveillance Qualité de l'Air")
st.markdown(
    "Projet 3ᵉ Année Ingénieur — Analyse de données environnementales"
)

# Fenêtre d'analyse (les alertes OMS sont définies sur 24 h).
PERIOD_HOURS = 24

# Villes proposées dans la liste. Les coordonnées sont obtenues via
# WeatherAPIClient.geocode_city(). Ce dictionnaire ne sert de secours
# qu'en mode déconnecté, quand le géocodage est impossible.
DEFAULT_CITIES = {
    "Paris": (48.8566, 2.3522),
    "Lyon": (45.7640, 4.8357),
    "Marseille": (43.2965, 5.3698),
    "London": (51.5074, -0.1278),
    "Madrid": (40.4168, -3.7038),
}

# Indicateurs affichés : (libellé, colonne, format, unité, couleur du delta).
# "inverse" = une hausse est défavorable (polluants), "off" = neutre.
METRICS = [
    ("🌡️ Température", "temperature_2m", ".1f", " °C", "off"),
    ("💧 Humidité relative", "relative_humidity_2m", ".0f", " %", "off"),
    ("🧭 Pression de surface", "surface_pressure", ".1f", " hPa", "off"),
    ("💨 Vent à 10 m", "wind_speed_10m", ".1f", " km/h", "off"),
    ("🌍 AQI (US)", "us_aqi", ".0f", "", "inverse"),
    ("🌫️ PM2.5", "pm2_5", ".1f", " µg/m³", "inverse"),
    ("🌫️ PM10", "pm10", ".1f", " µg/m³", "inverse"),
    ("🏭 NO₂", "nitrogen_dioxide", ".1f", " µg/m³", "inverse"),
    ("☀️ Ozone (O₃)", "ozone", ".1f", " µg/m³", "inverse"),
    ("🏭 SO₂", "sulphur_dioxide", ".1f", " µg/m³", "inverse"),
    ("🔥 CO", "carbon_monoxide", ".0f", " µg/m³", "inverse"),
    ("💚 Score de confort", "health_index", ".1f", " /100", "normal"),
]

# Statistiques renvoyées par DataProcessor.calculate_statistics().
STATS_LABELS = [
    ("temperature_moyenne", "🌡️ Température moyenne", ".1f", " °C"),
    ("temperature_mediane", "🌡️ Température médiane", ".1f", " °C"),
    ("humidite_moyenne", "💧 Humidité moyenne", ".0f", " %"),
    ("pm25_moyenne", "🌫️ PM2.5 moyenne", ".1f", " µg/m³"),
    ("pm25_mediane", "🌫️ PM2.5 médiane", ".1f", " µg/m³"),
    ("pm10_moyenne", "🌫️ PM10 moyenne", ".1f", " µg/m³"),
    ("no2_moyenne", "🏭 NO₂ moyenne", ".1f", " µg/m³"),
    ("ozone_moyenne", "☀️ Ozone moyenne", ".1f", " µg/m³"),
]


@st.cache_resource
def get_client() -> WeatherAPIClient:
    """Un seul client (session HTTP + cache SQLite) pour toute l'application."""
    return WeatherAPIClient()


client = get_client()


def fmt(value, fmt_str: str, unit: str = "") -> str:
    """Formate une valeur, en gérant les valeurs manquantes (null de l'API)."""
    if value is None or pd.isna(value):
        return "N/D"
    return f"{format(value, fmt_str)}{unit}"


def show_alerts(alerts: list) -> None:
    """Affiche une liste d'alertes de alerts.py selon leur niveau."""
    if not alerts:
        st.success("Aucun dépassement de seuil.")
        return
    for alert in alerts:
        if alert["level"] == "danger":
            st.error(alert["message"], icon="🚨")
        else:
            st.warning(alert["message"], icon="⚠️")


# --------------------------------------------------
# BARRE LATÉRALE
# --------------------------------------------------

st.sidebar.header("⚙️ Configuration")

choice = st.sidebar.selectbox(
    "Sélectionner une ville",
    list(DEFAULT_CITIES.keys()) + ["Autre..."]
)

if choice == "Autre...":
    city_query = st.sidebar.text_input("Nom de la ville", value="Grenoble")
else:
    city_query = choice

mock_mode = st.sidebar.checkbox(
    "Mode Déconnecté / Data Mocked",
    value=False
)


# --------------------------------------------------
# GÉOCODAGE + RÉCUPÉRATION DES DONNÉES (via api_client)
# --------------------------------------------------

try:
    with st.spinner(f"Chargement des données pour {city_query}..."):
        try:
            place = client.geocode_city(city_query)
        except (RuntimeError, ValueError):
            if mock_mode and city_query in DEFAULT_CITIES:
                lat, lon = DEFAULT_CITIES[city_query]
                place = {
                    "name": city_query,
                    "country": "",
                    "country_code": "",
                    "latitude": lat,
                    "longitude": lon,
                }
            else:
                raise

        raw_data = client.fetch_weather_and_air_quality(
            place["latitude"],
            place["longitude"],
            mock_mode=mock_mode
        )

except (RuntimeError, ValueError) as exc:
    st.error(f"Impossible de charger les données : {exc}")
    st.stop()


# --------------------------------------------------
# TRANSFORMATION DES DONNÉES (via DataProcessor)
# --------------------------------------------------

try:
    df = DataProcessor.process_raw_api_data(raw_data)
except (KeyError, ValueError, TypeError) as exc:
    st.error(f"Erreur lors du traitement des données : {exc}")
    st.stop()

if df.empty:
    st.error("Aucune donnée disponible.")
    st.stop()

# Score de confort (DataProcessor.calculate_custom_health_index)
df["health_index"] = DataProcessor.calculate_custom_health_index(df)


# --------------------------------------------------
# HEURE COURANTE ET MESURES OBSERVÉES
# --------------------------------------------------

offset = raw_data["weather"].get("utc_offset_seconds")

if offset is not None:
    now_local = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=offset)
    ).replace(tzinfo=None)
else:
    now_local = datetime.datetime.now()

# Les méthodes de data_processing et alerts raisonnent sur "la dernière
# mesure" et "les dernières 24 h" : on leur transmet donc uniquement les
# heures déjà écoulées (l'API peut renvoyer des heures futures).
df_obs = df[df["datetime"] <= pd.Timestamp(now_local)]

if df_obs.empty:
    st.warning(
        "Aucune mesure antérieure à l'heure actuelle : "
        "analyse effectuée sur l'ensemble des données reçues."
    )
    df_obs = df

latest = df_obs.sort_values("datetime").iloc[-1]


# --------------------------------------------------
# INFORMATIONS
# --------------------------------------------------

label = place["name"]
if place.get("country"):
    label += f", {place['country']}"

st.subheader(f"📍 Données environnementales : {label}")

st.caption(
    f"Dernière mesure disponible : "
    f"{latest['datetime'].strftime('%d/%m/%Y à %H:%M')} (heure locale) — "
    f"{'données simulées' if mock_mode else 'Open-Meteo'}"
)


# --------------------------------------------------
# ALERTES (alerts.py)
# --------------------------------------------------

st.markdown("---")
st.subheader("🚨 Alertes")

col_alert_1, col_alert_2 = st.columns(2)

with col_alert_1:
    st.markdown("**Seuils du projet — dernière mesure**")
    show_alerts(detect_alerts(df_obs))

with col_alert_2:
    st.markdown(f"**Valeurs guides OMS — moyennes sur {PERIOD_HOURS} h**")
    show_alerts(detect_who_alerts(df_obs))


# --------------------------------------------------
# INDICATEURS (dernière mesure + tendance DataProcessor.calculate_trend)
# --------------------------------------------------

st.markdown("---")
st.subheader("📊 Dernière mesure")

for start in range(0, len(METRICS), 4):
    cols = st.columns(4)
    for col, (name, column, fmt_str, unit, delta_color) in zip(
        cols, METRICS[start:start + 4]
    ):
        trend = DataProcessor.calculate_trend(df_obs, column, PERIOD_HOURS)
        delta = None if trend is None or pd.isna(trend) \
            else f"{format(trend, '+' + fmt_str)}{unit}"

        col.metric(
            name,
            fmt(latest.get(column), fmt_str, unit),
            delta=delta,
            delta_color=delta_color
        )

st.caption(
    f"Les variations affichées correspondent à l'évolution sur "
    f"les {PERIOD_HOURS} dernières heures."
)


# --------------------------------------------------
# STATISTIQUES (DataProcessor.calculate_statistics)
# --------------------------------------------------

st.markdown("---")
st.subheader(f"📐 Statistiques sur les {PERIOD_HOURS} dernières heures")

stats = DataProcessor.calculate_statistics(df_obs, PERIOD_HOURS)

for start in range(0, len(STATS_LABELS), 4):
    cols = st.columns(4)
    for col, (key, name, fmt_str, unit) in zip(
        cols, STATS_LABELS[start:start + 4]
    ):
        col.metric(name, fmt(stats.get(key), fmt_str, unit))


# --------------------------------------------------
# GRAPHIQUES ET CARTE
# --------------------------------------------------

st.markdown("---")

tab1, tab2, tab3 = st.tabs([
    "📈 Évolution Météo",
    "🏭 Qualité de l'Air",
    "🗺️ Carte Interactive"
])

LABELS = {
    "datetime": "Date / Heure",
    "value": "Valeur",
    "variable": "Métrique",
    "health_index": "Score de confort"
}

with tab1:
    st.subheader("Température et humidité")
    st.plotly_chart(
        px.line(
            df, x="datetime",
            y=["temperature_2m", "relative_humidity_2m"],
            labels=LABELS
        ),
        use_container_width=True
    )

    st.subheader("Pression de surface et vent")
    col_a, col_b = st.columns(2)
    col_a.plotly_chart(
        px.line(df, x="datetime", y="surface_pressure", labels=LABELS),
        use_container_width=True
    )
    col_b.plotly_chart(
        px.line(df, x="datetime", y="wind_speed_10m", labels=LABELS),
        use_container_width=True
    )

    st.subheader("Score de confort (0–100)")
    st.plotly_chart(
        px.line(df, x="datetime", y="health_index", labels=LABELS),
        use_container_width=True
    )

with tab2:
    st.subheader("Polluants (µg/m³)")
    st.plotly_chart(
        px.line(
            df, x="datetime",
            y=["pm2_5", "pm10", "nitrogen_dioxide",
               "ozone", "sulphur_dioxide"],
            labels=LABELS
        ),
        use_container_width=True
    )

    col_c, col_d = st.columns(2)
    col_c.subheader("Monoxyde de carbone")
    col_c.plotly_chart(
        px.line(df, x="datetime", y="carbon_monoxide", labels=LABELS),
        use_container_width=True
    )
    col_d.subheader("Indice AQI (US)")
    col_d.plotly_chart(
        px.line(df, x="datetime", y="us_aqi", labels=LABELS),
        use_container_width=True
    )

with tab3:
    st.subheader(f"Localisation : {label}")
    st.map(
        pd.DataFrame([{
            "lat": place["latitude"],
            "lon": place["longitude"]
        }]),
        zoom=9
    )


# --------------------------------------------------
# EXPORTS
# --------------------------------------------------

st.sidebar.download_button(
    "⬇️ Données CSV",
    df.drop(columns=["datetime"]).to_csv(index=False).encode("utf-8"),
    f"{place['name']}_donnees.csv",
    "text/csv"
)
st.sidebar.download_button(
    "⬇️ Exporter en PDF",
    client.export_pdf(raw_data, place["name"]),
    f"{place['name']}_synthese.pdf",
    "application/pdf",
    use_container_width=True
)