# Weekly Digest

[![CI](https://github.com/your-user/weekly-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/your-user/weekly-digest/actions/workflows/ci.yml)

Synthèses textuelles et podcasts automatiques à partir de bookmarks et flux RSS.

## Vue d'ensemble

Weekly Digest est un système **self-hosted** qui :

- Centralise les bookmarks avec **Readeck** (archivage, extraction de contenu)
- Ingère automatiquement des articles depuis des flux **RSS**
- Synchronise chaque semaine vers **Open Notebook** (alternative open-source à NotebookLM)
- Génère automatiquement :
  - Une synthèse textuelle des contenus de la semaine
  - Un podcast audio multi-voix
- Expose deux flux RSS :
  - `/feeds/podcast.rss` - abonnable dans tout player podcast
  - `/feeds/reviews.rss` - newsletter lisible dans tout reader RSS

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         docker-compose                               │
├─────────────┬─────────────┬─────────────────────┬───────────────────┤
│   Readeck   │   Open Notebook Stack             │  sync-orchestrator│
│   :8000     │   ┌─────────┬───────────┬───────┐ │  (Python)         │
│             │   │ Backend │ Frontend  │Surreal│ │                   │
│   Bookmarks │   │ :5055   │ :3000     │ DB    │ │  - RSS fetcher    │
│   + Extract │   └─────────┴───────────┴───────┘ │  - Weekly sync    │
│             │                                   │  - RSS feeds      │
└──────┬──────┴───────────────┬───────────────────┴─────────┬─────────┘
       │                      │                             │
       │      HTTP APIs       │                             │
       └──────────────────────┴─────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │      Nginx        │
                    │  (feeds + audio)  │
                    └───────────────────┘
```

### Flux de données

1. **Quotidien** : RSS feeds → sync-orchestrator → Readeck (nouveaux bookmarks)
2. **Hebdomadaire** : Readeck → sync-orchestrator → Open Notebook
   - Création d'un notebook pour la semaine
   - Ajout des sources (URLs/textes extraits)
   - Génération summary + podcast
3. **À la demande** : Accès aux flux RSS générés

## Prérequis

- Docker + Docker Compose v2+
- 4-8 GB RAM minimum (selon modèles LLM/TTS)
- Tokens API pour Readeck et Open Notebook

## Installation

```bash
# Cloner le repository
git clone https://github.com/your-user/weekly-digest.git
cd weekly-digest

# Configurer l'environnement
cp .env.example .env
# Éditer .env avec vos tokens et configuration

# Lancer la stack
docker compose up -d --build

# Vérifier les logs
docker compose logs -f sync-orchestrator
```

## Configuration

Copier `.env.example` vers `.env` et configurer :

| Variable | Description | Exemple |
|----------|-------------|---------|
| `READECK_URL` | URL interne Readeck | `http://readeck:8000` |
| `READECK_TOKEN` | Token API Readeck | Générer dans Profil > API Tokens |
| `OPEN_NOTEBOOK_URL` | URL backend Open Notebook | `http://open-notebook-backend:5055` |
| `OPEN_NOTEBOOK_PASSWORD` | Mot de passe API | Défini dans la config ON |
| `RSS_FEEDS` | Flux RSS à ingérer (virgule) | `https://feed1.com/rss,https://feed2.com/rss` |
| `SYNC_DAY` | Jour de sync hebdo | `sunday` |
| `SYNC_HOUR` | Heure de sync | `23` |
| `AUDIO_HOSTING` | Hébergement audio | `local`, `anchor`, `backblaze` |

## Accès

| Service | URL | Description |
|---------|-----|-------------|
| Readeck | http://localhost:8000 | Gestion des bookmarks |
| Open Notebook | http://localhost:3000 | Interface notebooks |
| Flux podcast | http://localhost/feeds/podcast.rss | Abonnement podcast |
| Flux reviews | http://localhost/feeds/reviews.rss | Newsletter RSS |
| API orchestrator | http://localhost:8002/docs | Swagger API |
| Health check | http://localhost:8002/health | État des services |

## Structure du projet

```
weekly-digest/
├── README.md                 # Ce fichier
├── AGENTS.md                 # Guide pour AI + doc APIs
├── PLAN.md                   # Plan d'implémentation
├── docker-compose.yml        # Stack complète
├── .env.example              # Template configuration
├── .env                      # Configuration (ignoré git)
├── orchestrator/             # Service Python principal
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── src/
│       ├── config.py         # Configuration Pydantic
│       ├── database.py       # SQLite + modèles
│       ├── clients/          # Clients API
│       │   ├── readeck.py
│       │   └── opennotebook.py
│       ├── jobs/             # Tâches planifiées
│       │   ├── rss_fetcher.py
│       │   ├── weekly_sync.py
│       │   └── audio_uploader.py
│       └── api/              # Endpoints FastAPI
│           ├── main.py
│           ├── feeds.py
│           └── health.py
├── nginx/                    # Configuration reverse proxy
│   └── default.conf
├── tests/                    # Tests pytest
│   ├── conftest.py
│   ├── test_clients/
│   ├── test_jobs/
│   └── integration/
└── .github/
    └── workflows/
        └── ci.yml            # GitHub Actions
```

## Développement

```bash
# Installer les dépendances (Poetry)
cd orchestrator
poetry install

# Lancer les tests
poetry run pytest

# Lancer en mode dev
poetry run uvicorn src.api.main:app --reload --port 8002

# Linter
poetry run ruff check .
poetry run ruff format .
```

## Commandes utiles

```bash
# Forcer une sync immédiate
curl -X POST http://localhost:8002/api/sync/trigger

# Vérifier l'état
curl http://localhost:8002/health

# Voir les bookmarks de la semaine
curl http://localhost:8002/api/bookmarks/week

# Regénérer les flux RSS
curl -X POST http://localhost:8002/api/feeds/regenerate
```

## Dépannage

### Les bookmarks ne s'ajoutent pas
- Vérifier le token Readeck : `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/profile`
- Consulter les logs : `docker compose logs sync-orchestrator`

### Le podcast ne se génère pas
- Vérifier que Open Notebook a accès aux modèles LLM/TTS
- Consulter les logs ON : `docker compose logs open-notebook-backend`

### Les flux RSS sont vides
- Vérifier qu'au moins une sync hebdo a eu lieu
- Forcer une régénération : `curl -X POST http://localhost:8002/api/feeds/regenerate`

## Licence

MIT
