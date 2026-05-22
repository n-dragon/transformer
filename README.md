# ImmoAgent 🏠

Agent IA pour trouver des logements en France et en Europe, propulsé par Claude.

## Sites couverts

### France
| Site | Type | Anti-bot | Méthode |
|------|------|----------|---------|
| [PAP.fr](https://www.pap.fr) | Vente/Location | Modéré | HTTP + BeautifulSoup |
| [SeLoger](https://www.seloger.com) | Vente/Location | Modéré | `__NEXT_DATA__` JSON |
| [LeBonCoin](https://www.leboncoin.fr) | Vente/Location | Fort (DataDome) | API interne reverse-engineered |
| [Logic-Immo](https://www.logic-immo.com) | Vente/Location | Modéré | HTTP scraping |
| [Bien'ici](https://www.bienici.com) | Vente/Location | Modéré | HTTP + JSON API |

### Europe
| Site | Pays | Méthode |
|------|------|---------|
| [Idealista](https://www.idealista.com) | Espagne / Italie / Portugal | HTTP + BeautifulSoup |
| [ImmoScout24](https://www.immobilienscout24.de) | Allemagne | API partenaires + reverse-engineering |
| [Rightmove](https://www.rightmove.co.uk) | Royaume-Uni | `__NEXT_DATA__` JSON |
| [Zoopla](https://www.zoopla.co.uk) | Royaume-Uni | HTTP + automation |
| [Immowelt](https://www.immowelt.de) | Allemagne | HTTP direct |

## Installation

```bash
# 1. Cloner le repo
git clone <repo-url>
cd transformer

# 2. Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # ou venv\Scripts\activate sur Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer la clé API
cp .env.example .env
# Éditer .env et ajouter votre ANTHROPIC_API_KEY

# 5. Lancer le serveur
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

L'interface est disponible sur **http://localhost:8000**

## Architecture

```
transformer/
├── backend/
│   ├── main.py              # FastAPI app + routes
│   ├── agent.py             # Agent Claude avec tool use
│   └── scrapers/
│       ├── base.py          # Dataclass Listing + utilitaires
│       ├── pap.py           # Scraper PAP.fr
│       ├── seloger.py       # Scraper SeLoger
│       ├── leboncoin.py     # Scraper LeBonCoin
│       └── idealista.py     # Scraper Idealista (ES/IT/PT)
├── frontend/
│   ├── index.html           # Interface principale
│   └── static/
│       ├── style.css        # Design dark mode
│       └── app.js           # Logique frontend + SSE streaming
└── requirements.txt
```

## Fonctionnalités

- **Configurateur d'agent** : nom, type (location/achat), ville, budget, surface, pièces, sites
- **Chat IA** : conversation naturelle avec Claude qui utilise les scrapers comme outils
- **Streaming** : les réponses s'affichent en temps réel (Server-Sent Events)
- **Multi-sites** : recherche parallèle sur plusieurs portails simultanément
- **Comparaison** : l'agent compare et recommande les meilleures annonces

## Note légale

Ce projet est à des fins éducatives. Respectez les CGU de chaque site et le RGPD.
Certains sites (LeBonCoin) interdisent explicitement le scraping.
