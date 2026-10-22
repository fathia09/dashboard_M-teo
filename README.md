# 🌤️ Dashboard Météo & Qualité de l'Air

Application Streamlit qui récupère la météo et la qualité de l'air et les affiche dans un dashboard interactif.

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

## Tests

```bash
python -m pytest
```
