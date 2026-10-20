import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from src.api_client import WeatherAPIClient
st.set_page_config(
    page_title="Dashboard Météo & AQI",
    page_icon="🌤️",
    layout="wide"
)

st.title("🌤️ Dashboard Météo & Surveillance Qualité de l'Air")
st.markdown("Projet 3ᵉ Année Ingénieur — Analyse de données environnementales")

# Choix des villes
villes = {
    "Paris": {"lat": 48.8566, "lon": 2.3522},
    "Lyon": {"lat": 45.7640, "lon": 4.8357},
    "Marseille": {"lat": 43.2965, "lon": 5.3698},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Madrid": {"lat": 40.4168, "lon": -3.7038}
}

st.sidebar.header("⚙️ Configuration")

ville = st.sidebar.selectbox(
    "Sélectionner une ville",
    list(villes.keys())
)

st.sidebar.checkbox(
    "Mode Déconnecté / Data Mocked",
    value=True,
    disabled=True
)

st.info("Mode démonstration : les données affichées sont simulées.")

# Création de données simulées
np.random.seed(42)

dates = pd.date_range(end=pd.Timestamp.now(), periods=168, freq="h")

df = pd.DataFrame({
    "datetime": dates,
    "temperature_2m": np.random.normal(20, 5, 168),
    "relativehumidity_2m": np.random.uniform(40, 90, 168),
    "pm2_5": np.random.uniform(5, 35, 168),
    "pm10": np.random.uniform(10, 60, 168),
    "nitrogen_dioxide": np.random.uniform(10, 55, 168),
    "us_aqi": np.random.randint(15, 120, 168)
})

df["health_score"] = (
    100
    - abs(df["temperature_2m"] - 21) * 1.5
    - abs(df["relativehumidity_2m"] - 50) * 0.3
    - df["pm2_5"] * 1.2
).clip(0, 100)

latest = df.iloc[-1]

# Alertes
if latest["pm2_5"] >= 25:
    st.error("🚨 DANGER : Pollution PM2.5 élevée")
elif latest["pm2_5"] >= 15:
    st.warning("⚠️ ATTENTION : Pollution PM2.5 modérée")
else:
    st.success("✅ Conditions environnementales stables.")

# Indicateurs
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Température", f"{latest['temperature_2m']:.1f} °C")
col2.metric("Humidité", f"{latest['relativehumidity_2m']:.0f} %")
col3.metric("Indice AQI (US)", f"{int(latest['us_aqi'])}")
col4.metric("PM 2.5", f"{latest['pm2_5']:.1f} µg/m³")
col5.metric("Score Confort (0-100)", f"{latest['health_score']:.1f}")

# Onglets
st.markdown("---")

tab1, tab2, tab3 = st.tabs([
    "📈 Évolution Météo",
    "🏭 Qualité de l'Air",
    "🗺️ Carte Interactive"
])

with tab1:
    st.subheader("Température et Humidité (7 derniers jours / Prévisions)")

    fig_temp = px.line(
        df,
        x="datetime",
        y=["temperature_2m", "relativehumidity_2m"],
        title="Série temporelle Météo"
    )

    st.plotly_chart(fig_temp, use_container_width=True)

with tab2:
    st.subheader("Concentration des Polluants Clés (µg/m³)")

    fig_air = px.bar(
        df.tail(24),
        x="datetime",
        y=["pm2_5", "pm10", "nitrogen_dioxide"],
        barmode="group",
        title="Exposition aux polluants sur les 24 dernières heures"
    )

    st.plotly_chart(fig_air, use_container_width=True)

with tab3:
    st.subheader("Localisation de la station de suivi")

    map_df = pd.DataFrame([{
        "lat": villes[ville]["lat"],
        "lon": villes[ville]["lon"]
    }])

    st.map(map_df, zoom=9)