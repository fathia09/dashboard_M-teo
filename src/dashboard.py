import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timezone
from src.api_client import WeatherAPIClient


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
    "Projet 3ᵉ Année Ingénieur — Analyse de données environnementales en temps réel"
)


# --------------------------------------------------
# VILLES
# --------------------------------------------------

DEFAULT_CITIES = {
    "Paris": {"lat": 48.8566, "lon": 2.3522},
    "Lyon": {"lat": 45.7640, "lon": 4.8357},
    "Marseille": {"lat": 43.2965, "lon": 5.3698},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Madrid": {"lat": 40.4168, "lon": -3.7038}
}


# --------------------------------------------------
# BARRE LATÉRALE
# --------------------------------------------------

st.sidebar.header("⚙️ Configuration")

selected_city = st.sidebar.selectbox(
    "Sélectionner une ville",
    list(DEFAULT_CITIES.keys())
)

city_info = DEFAULT_CITIES[selected_city]

if st.sidebar.button("🔄 Actualiser les données"):
    st.rerun()

st.sidebar.info(
    "Les données sont récupérées depuis Open-Meteo."
)


# --------------------------------------------------
# RÉCUPÉRATION DES DONNÉES
# --------------------------------------------------

client = WeatherAPIClient()

with st.spinner(
    f"Chargement des données pour {selected_city}..."
):

    raw_data = client.fetch_weather_and_air_quality(
        city_info["lat"],
        city_info["lon"],
        mock_mode=False
    )


# --------------------------------------------------
# TRANSFORMATION DES DONNÉES
# --------------------------------------------------

try:

    df_weather = pd.DataFrame(
        raw_data["weather"]["hourly"]
    )

    df_air = pd.DataFrame(
        raw_data["air_quality"]["hourly"]
    )

    df = pd.merge(
        df_weather,
        df_air,
        on="time",
        how="inner"
    )

    df["datetime"] = pd.to_datetime(df["time"])

    # Compatibilité entre différentes versions de l'API
    df = df.rename(columns={
        "relative_humidity_2m": "relativehumidity_2m",
        "wind_speed_10m": "windspeed_10m"
    })

    if df.empty:
        st.error("Aucune donnée disponible.")
        st.stop()

except Exception as e:

    st.error(
        f"Erreur lors du traitement des données : {e}"
    )

    st.stop()


# --------------------------------------------------
# DONNÉES ACTUELLES
# --------------------------------------------------

# On conserve uniquement les observations passées
# pour éviter d'afficher une prévision comme une mesure.

now = pd.Timestamp.now(tz="UTC").tz_localize(None)

df["datetime"] = pd.to_datetime(
    df["datetime"],
    utc=True
).dt.tz_localize(None)

df = df[df["datetime"] <= now]

df = df.sort_values("datetime")

if df.empty:
    st.error("Aucune donnée récente disponible.")
    st.stop()

latest = df.iloc[-1]


# --------------------------------------------------
# SCORE DE CONFORT
# --------------------------------------------------

df["health_score"] = (
    100
    - abs(df["temperature_2m"] - 21) * 1.5
    - abs(df["relativehumidity_2m"] - 50) * 0.3
    - df["pm2_5"] * 1.2
).clip(0, 100)

latest = df.iloc[-1]


# --------------------------------------------------
# INFORMATIONS
# --------------------------------------------------

st.subheader(f"📍 Données environnementales : {selected_city}")

st.caption(
    f"Dernière heure disponible : "
    f"{latest['datetime'].strftime('%d/%m/%Y à %H:%M')} (UTC)"
)


# --------------------------------------------------
# ALERTES
# --------------------------------------------------

alerts = []

if latest["pm2_5"] >= 25:

    alerts.append(
        ("danger", "Pollution PM2.5 élevée")
    )

elif latest["pm2_5"] >= 15:

    alerts.append(
        ("warning", "Vigilance pollution PM2.5")
    )

if latest["nitrogen_dioxide"] >= 50:

    alerts.append(
        ("danger", "Dépassement NO₂")
    )

if latest["temperature_2m"] >= 33:

    alerts.append(
        ("warning", "Vigilance forte chaleur")
    )

if alerts:

    for level, message in alerts:

        if level == "danger":
            st.error(f"🚨 DANGER : {message}")

        else:
            st.warning(f"⚠️ ATTENTION : {message}")

else:

    st.success(
        "✅ Aucune alerte détectée selon les seuils du projet."
    )


# --------------------------------------------------
# INDICATEURS
# --------------------------------------------------

st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric(
    "🌡️ Température",
    f"{latest['temperature_2m']:.1f} °C"
)

col2.metric(
    "💧 Humidité",
    f"{latest['relativehumidity_2m']:.0f} %"
)

col3.metric(
    "🌍 Indice AQI (US)",
    f"{int(latest['us_aqi'])}"
)

col4.metric(
    "🌫️ PM2.5",
    f"{latest['pm2_5']:.1f} µg/m³"
)

col5.metric(
    "❤️ Score Confort (0-100)",
    f"{latest['health_score']:.1f}"
)


# --------------------------------------------------
# GRAPHIQUES ET CARTE
# --------------------------------------------------

st.markdown("---")

tab1, tab2, tab3 = st.tabs([
    "📈 Évolution Météo",
    "🏭 Qualité de l'Air",
    "🗺️ Carte Interactive"
])


# ONGLET 1 : MÉTÉO

with tab1:

    st.subheader(
        "Température et Humidité (7 derniers jours)"
    )

    fig_temp = px.line(
        df,
        x="datetime",
        y=[
            "temperature_2m",
            "relativehumidity_2m"
        ],
        labels={
            "datetime": "Date / Heure",
            "value": "Valeur",
            "variable": "Métrique"
        },
        title="Série temporelle Météo"
    )

    st.plotly_chart(
        fig_temp,
        use_container_width=True
    )


# ONGLET 2 : POLLUTION

with tab2:

    st.subheader(
        "Concentration des Polluants Clés (µg/m³)"
    )

    fig_air = px.bar(
        df.tail(24),
        x="datetime",
        y=[
            "pm2_5",
            "pm10",
            "nitrogen_dioxide"
        ],
        barmode="group",
        title="Polluants sur les 24 dernières heures"
    )

    st.plotly_chart(
        fig_air,
        use_container_width=True
    )


# ONGLET 3 : CARTE

with tab3:

    st.subheader(
        f"Localisation de la station : {selected_city}"
    )

    map_df = pd.DataFrame([{
        "lat": city_info["lat"],
        "lon": city_info["lon"]
    }])

    st.map(
        map_df,
        zoom=9
    )