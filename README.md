# 🌤️ Dashboard Météo & Qualité de l'Air

Application Streamlit qui récupère la météo et la qualité de l'air et les affiche dans un dashboard interactif.

## Fonctionnalités

| Domaine | Détail |
|---|---|
| **Ingestion** | Données horaires sur 7 jours via **Open-Meteo** : géocodage, météo, qualité de l'air. |
| **Villes** | Paris, Lyon, Marseille, Londres, Madrid, plus une saisie libre (« Autre… ») géocodée à la volée. |
| **Météo** | Température, humidité, pression atmosphérique, vitesse du vent. |
| **Qualité de l'air** | Indice AQI (US), PM2.5, PM10, NO₂, O₃, CO, SO₂. |
| **Cache** | Base **SQLite** locale avec durée de vie (TTL) de 30 minutes, pour limiter les appels API. |
| **Traitement** | Nettoyage, statistiques (moyenne, médiane), tendance sur 24 h, score de confort (0–100). |
| **Alertes** | Seuils du projet sur la dernière mesure, et moyennes 24 h comparées aux valeurs guides OMS. |
| **Interface** | Streamlit : sélecteur de ville, cartes KPI, graphiques Plotly interactifs, carte de localisation. |
| **Bonus** | Mode déconnecté (données simulées), export **CSV** et **PDF**, conteneur **Docker**. |

---

## Architecture

Le projet sépare la récupération des données, le traitement métier et l'affichage.

```
projet_python/
├── src/
│   ├── __init__.py
│   ├── api_client.py       # Requêtes API, géocodage, cache SQLite, mode simulé, exports
│   ├── data_processing.py  # Nettoyage Pandas, statistiques, tendances, score de confort
│   ├── alerts.py           # Moteur de règles et d'alertes
│   └── dashboard.py        # Interface Streamlit
├── tests/
│   ├── test_api.py         # Tests du client API (pytest)
│   └── test_processing.py  # Tests du traitement et des alertes (pytest)
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```


## Prérequis

- Python 3.10 ou supérieur
- `git`

## Installation

```bash
# 1. Récupérer le projet
git clone https://github.com/fathia09/dashboard_M-teo.git
cd dashboard_Meteo

# 2. Créer et activer un environnement virtuel
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows

# 3. Installer les dépendances
pip install -r requirements.txt
```

Aucune clé d'API n'est nécessaire. Pour une configuration locale, copiez `.env.example` en `.env` (fichier exclu de Git).

## Lancement

Depuis la **racine du projet** :

```bash
streamlit run src/dashboard.py
```

Le dashboard s'ouvre sur <http://localhost:8501>.

Pour tester sans Internet, cochez **« Mode Déconnecté / Data Mocked »** dans la barre latérale.


## Utilisation du dashboard

1. **Barre latérale :** choisissez une ville (ou « Autre… » pour saisir n'importe quelle ville) et activez éventuellement le mode déconnecté.
2. **Alertes :** deux panneaux côte à côte.
   - *Seuils du projet* : comparés à la dernière mesure disponible.
   - *Valeurs guides OMS* : comparées aux moyennes des 24 dernières heures.
3. **Dernière mesure :** cartes KPI avec la variation sur 24 h. Pour les polluants, une hausse s'affiche en rouge.
4. **Statistiques sur 24 h :** moyennes et médianes (température, humidité, PM2.5, PM10, NO₂, O₃).
5. **Onglets :** évolution météo, qualité de l'air, carte de localisation.
6. **Exports :** boutons *Données CSV* et *Exporter en PDF* dans la barre latérale.

---

## Documentation technique

### `api_client.py` : récupération des données

- **API utilisées :** Open-Meteo (géocodage, météo, qualité de l'air), sans clé.
- **Cache :** les réponses sont enregistrées dans une base SQLite (`data_cache.db`) pendant 30 minutes, ce qui évite les appels inutiles.
- **Erreurs :** réseau coupé, délai dépassé, erreur HTTP ou JSON invalide donnent un message d'erreur clair dans le dashboard.
- **Mode simulé :** `mock_mode=True` génère des données fictives, sans Internet.
- **Exports :** CSV et PDF.

### `data_processing.py` : traitement

- **Nettoyage :** fusion météo + air, conversion des dates, suppression des valeurs impossibles (humidité hors 0–100 %, polluants négatifs) et des doublons.
- **Statistiques :** moyenne et médiane sur les 24 dernières heures.
- **Tendance :** variation d'une mesure sur 24 h.
- **Score de confort (0 à 100) :**

```
score = 100 − ( 1,5 × |T − 21|  +  0,3 × |H − 50|  +  1,2 × PM2.5 )
```

`T` est la température (°C), `H` l'humidité (%) et `PM2.5` la concentration en particules fines (µg/m³). Plus on s'éloigne de 21 °C, de 50 % d'humidité ou plus l'air est pollué, plus le score baisse.

### `alerts.py` : alertes

| Indicateur | Vigilance ⚠️ | Danger 🚨 |
|---|---|---|
| PM2.5 | ≥ 15 µg/m³ | ≥ 25 µg/m³ |
| PM10 | ≥ 45 µg/m³ | ≥ 50 µg/m³ |
| NO₂ | ≥ 25 µg/m³ | ≥ 50 µg/m³ |
| Température | ≥ 33 °C | ≥ 38 °C |

Ces seuils s'appliquent à la **dernière mesure** et sont modifiables dans `THRESHOLDS`. Le dashboard compare aussi les **moyennes sur 24 h** aux valeurs guides de l'OMS : PM2.5 > 15, PM10 > 45 et NO₂ > 25 µg/m³.

### `dashboard.py` : interface

Il affiche uniquement les résultats des trois autres modules (aucun calcul métier).

## Tests

```bash
python -m pytest
```
| Fichier | Contenu |
|---|---|
| `tests/test_api.py` | Cache (écriture, lecture, expiration, TTL à 0, JSON corrompu), géocodage, paramètres des requêtes, validation des coordonnées, mode simulé, erreurs réseau et HTTP, résilience multi-villes, DataFrame, statistiques, export. |
| `tests/test_processing.py` | Nettoyage des données, statistiques, tendance, score de confort, alertes à seuils, alertes OMS (données incomplètes, heure manquante). |

## Docker

```bash
docker build -t dashboard-meteo .
docker run -p 8501:8501 dashboard-meteo
```

Le dashboard est alors disponible sur <http://localhost:8501>. L'image est basée sur `python:3.14-slim`, installe `requirements.txt`, copie le projet et lance `streamlit run src/dashboard.py` sur `0.0.0.0:8501`.
