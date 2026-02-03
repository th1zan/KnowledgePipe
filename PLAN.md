# PLAN.md - Plan d'implémentation

Ce document détaille les phases d'implémentation du projet Weekly Digest. Chaque phase est conçue pour être réalisable de manière autonome avec des critères de succès clairs.

## Vue d'ensemble des phases

| Phase | Nom | Durée estimée | Dépendances |
|-------|-----|---------------|-------------|
| 0 | Foundation | 30 min | - |
| 1 | Clients API | 2h | Phase 0 |
| 2 | Base de données | 1h | Phase 0 |
| 3 | RSS Fetcher | 1h30 | Phases 1, 2 |
| 4 | Sync hebdomadaire | 2h | Phases 1, 2 |
| 5 | Génération flux RSS | 1h30 | Phase 4 |
| 6 | Upload audio | 1h | Phase 4 |
| 7 | Health checks | 1h | Phases 1, 2 |
| 8 | Tests d'intégration | 2h | Phases 1-7 |
| 9 | CI/CD | 1h | Phase 8 |

---

## Phase 0 : Foundation (TERMINÉE)

### Objectifs
- [x] Créer les fichiers de documentation de base
- [x] Définir la structure du projet
- [x] Préparer la configuration

### Fichiers créés
- [x] `README.md` - Documentation utilisateur
- [x] `AGENTS.md` - Guide AI avec doc APIs
- [x] `PLAN.md` - Ce fichier
- [x] `.env.example` - Template de configuration
- [x] `.gitignore` - Fichiers à ignorer
- [x] Structure des dossiers (`orchestrator/`, `tests/`, `nginx/`, `.github/`)

### Critères de succès
- Les fichiers de documentation sont complets et lisibles
- Un développeur peut comprendre le projet en lisant le README
- Un modèle AI peut travailler sur le projet avec AGENTS.md

---

## Phase 1 : Clients API

### Objectifs
- Implémenter le client Readeck avec tests
- Implémenter le client Open Notebook avec tests
- Gérer les erreurs et retries

### Fichiers à créer

#### `orchestrator/src/clients/__init__.py`
```python
from .readeck import ReadeckClient
from .opennotebook import OpenNotebookClient

__all__ = ["ReadeckClient", "OpenNotebookClient"]
```

#### `orchestrator/src/clients/readeck.py`
Implémenter :
- `__init__(base_url, token)`
- `health_check() -> bool`
- `add_bookmark(url, title?, labels?) -> str | None`
- `get_bookmarks(range_start?, range_end?, labels?) -> list[dict]`
- `get_week_bookmarks() -> list[dict]`
- `get_bookmark(id) -> dict | None`
- `get_bookmark_content(id, format="md") -> str | None`
- `update_bookmark(id, **kwargs) -> bool`
- Gestion des erreurs HTTP avec retry (tenacity)

#### `orchestrator/src/clients/opennotebook.py`
Implémenter :
- `__init__(base_url, password)`
- `health_check() -> bool`
- `create_notebook(name, description?) -> dict`
- `get_notebook(id) -> dict | None`
- `list_notebooks() -> list[dict]`
- `add_source_url(notebook_id, url, embed?, async?) -> dict`
- `add_source_text(notebook_id, content, title, embed?) -> dict`
- `get_source_status(source_id) -> dict`
- `wait_for_source(source_id, timeout?) -> bool`
- `generate_podcast(notebook_id, episode_name, profiles?) -> dict`
- `get_podcast_job_status(job_id) -> dict`
- `wait_for_podcast(job_id, timeout?) -> str | None`
- `download_episode_audio(episode_id) -> bytes | None`
- `list_episodes() -> list[dict]`
- `get_notebook_notes(notebook_id) -> list[dict]`

### Tests à créer

#### `tests/test_clients/test_readeck.py`
```python
# Tests avec mocks (responses ou pytest-httpx)
def test_health_check_success():
def test_health_check_failure():
def test_add_bookmark_success():
def test_add_bookmark_duplicate():
def test_get_week_bookmarks_empty():
def test_get_week_bookmarks_with_results():
def test_get_bookmark_content_md():
def test_get_bookmark_content_not_found():
def test_retry_on_500():
```

#### `tests/test_clients/test_opennotebook.py`
```python
def test_health_check_success():
def test_create_notebook():
def test_add_source_url():
def test_add_source_text():
def test_wait_for_source_success():
def test_wait_for_source_timeout():
def test_generate_podcast():
def test_wait_for_podcast_success():
def test_download_audio():
```

### Dépendances à ajouter
```toml
[tool.poetry.dependencies]
requests = "^2.31"
tenacity = "^8.2"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-mock = "^3.12"
responses = "^0.24"
```

### Critères de succès
```bash
poetry run pytest tests/test_clients/ -v
# Tous les tests passent
```

### Commandes de validation
```bash
# Test unitaire des clients
poetry run pytest tests/test_clients/ -v --cov=src/clients

# Test manuel contre services réels (si disponibles)
python -c "
from src.clients import ReadeckClient
c = ReadeckClient('http://localhost:8000', 'token')
print(c.health_check())
"
```

---

## Phase 2 : Base de données (TERMINÉE)

### Objectifs
- [x] Créer le schéma SQLite
- [x] Implémenter les modèles SQLAlchemy
- [x] Créer les fonctions helpers

### Fichiers à créer

#### `orchestrator/src/database.py`
```python
# Modèles :
# - RssItem (guid, url, title, feed_url, bookmark_id, created_at)
# - SyncLog (id, started_at, completed_at, status, notebook_id, bookmarks_count, error)
# - Episode (id, notebook_id, episode_id, audio_url, created_at, uploaded)

# Fonctions :
# - init_db()
# - get_session() -> contextmanager
# - is_rss_item_processed(guid) -> bool
# - add_rss_item(guid, url, title, feed_url, bookmark_id)
# - create_sync_log(notebook_id, bookmarks_count) -> SyncLog
# - update_sync_log(log_id, status, error?)
# - get_latest_episodes(limit=20) -> list[Episode]
# - add_episode(notebook_id, episode_id, audio_url)
# - mark_episode_uploaded(episode_id, public_url)
```

### Tests à créer

#### `tests/test_database.py`
```python
def test_init_db_creates_tables():
def test_add_rss_item():
def test_is_rss_item_processed_true():
def test_is_rss_item_processed_false():
def test_create_sync_log():
def test_update_sync_log():
def test_add_episode():
def test_get_latest_episodes():
```

### Dépendances à ajouter
```toml
sqlalchemy = "^2.0"
```

### Critères de succès
```bash
poetry run pytest tests/test_database.py -v
# Base créée dans /tmp, tous les tests passent
```

---

## Phase 3 : RSS Fetcher (TERMINÉE)

### Objectifs
- [x] Parser les flux RSS configurés
- [x] Filtrer les articles déjà traités
- [x] Ajouter les nouveaux à Readeck
- [x] Enregistrer en base

### Fichiers à créer

#### `orchestrator/src/jobs/rss_fetcher.py`
```python
# Fonctions :
# - fetch_feed(url) -> list[FeedEntry]
# - process_entry(entry, feed_title) -> bool
# - process_all_feeds() -> ProcessingResult
# - run_rss_job()  # Point d'entrée scheduler
```

### Tests à créer

#### `tests/test_jobs/test_rss_fetcher.py`
```python
def test_fetch_feed_success():
def test_fetch_feed_invalid_url():
def test_fetch_feed_timeout():
def test_process_entry_new():
def test_process_entry_duplicate():
def test_process_entry_readeck_error():
def test_process_all_feeds_mixed():
```

### Dépendances à ajouter
```toml
feedparser = "^6.0"
```

### Critères de succès
```bash
poetry run pytest tests/test_jobs/test_rss_fetcher.py -v

# Test manuel avec un flux réel
python -c "
from src.jobs.rss_fetcher import fetch_feed
entries = fetch_feed('https://hnrss.org/frontpage')
print(f'Found {len(entries)} entries')
"
```

---

## Phase 4 : Sync hebdomadaire (TERMINÉE)

### Objectifs
- [x] Récupérer les bookmarks de la semaine
- [x] Créer un notebook Open Notebook
- [x] Ajouter les sources (URLs ou texte extrait)
- [x] Déclencher summary et podcast
- [x] Attendre la fin du traitement
- [x] Enregistrer en base

### Fichiers à créer

#### `orchestrator/src/jobs/weekly_sync.py`
```python
# Fonctions :
# - get_week_bookmarks() -> list[Bookmark]
# - create_weekly_notebook(bookmarks) -> str  # notebook_id
# - add_sources_to_notebook(notebook_id, bookmarks) -> list[str]  # source_ids
# - wait_for_sources(source_ids) -> bool
# - trigger_generations(notebook_id) -> GenerationResult
# - run_weekly_sync()  # Point d'entrée scheduler
```

### Tests à créer

#### `tests/test_jobs/test_weekly_sync.py`
```python
def test_get_week_bookmarks_empty():
def test_get_week_bookmarks_with_results():
def test_create_weekly_notebook():
def test_add_sources_url():
def test_add_sources_pdf_fallback_text():
def test_wait_for_sources_all_success():
def test_wait_for_sources_partial_failure():
def test_trigger_generations():
def test_run_weekly_sync_full():
```

### Critères de succès
```bash
poetry run pytest tests/test_jobs/test_weekly_sync.py -v
```

---

## Phase 5 : Génération flux RSS (TERMINÉE)

### Objectifs
- [x] Générer un flux RSS podcast (iTunes compatible)
- [x] Générer un flux RSS reviews (texte)
- [x] Servir via FastAPI

### Fichiers à créer

#### `orchestrator/src/api/feeds.py`
```python
# Endpoints :
# - GET /feeds/podcast.rss
# - GET /feeds/reviews.rss
# - POST /feeds/regenerate

# Fonctions :
# - generate_podcast_feed() -> str  # XML
# - generate_reviews_feed() -> str  # XML
# - get_cached_feed(name) -> str | None
# - invalidate_cache()
```

### Tests à créer

#### `tests/test_api/test_feeds.py`
```python
def test_podcast_rss_empty():
def test_podcast_rss_with_episodes():
def test_podcast_rss_itunes_tags():
def test_reviews_rss_empty():
def test_reviews_rss_with_content():
def test_regenerate_endpoint():
```

### Dépendances à ajouter
```toml
feedgen = "^1.0"
```

### Critères de succès
```bash
poetry run pytest tests/test_api/test_feeds.py -v

# Validation XML
curl http://localhost:8002/feeds/podcast.rss | xmllint --noout -
```

---

## Phase 6 : Upload audio (TERMINÉE)

### Objectifs
- [x] Supporter upload vers stockage local
- [x] Supporter upload vers Backblaze B2

### Fichiers à créer

#### `orchestrator/src/jobs/audio_uploader.py`
```python
# Classes :
# - AudioUploader (abstract)
# - LocalUploader(AudioUploader)
# - BackblazeUploader(AudioUploader)
# - AnchorUploader(AudioUploader)  # optionnel

# Fonctions :
# - get_uploader() -> AudioUploader  # factory selon config
# - upload_episode(episode_id, audio_data) -> str  # public URL
```

### Tests à créer

#### `tests/test_jobs/test_audio_uploader.py`
```python
def test_local_uploader():
def test_backblaze_uploader_mock():
def test_get_uploader_local():
def test_get_uploader_backblaze():
```

### Dépendances à ajouter
```toml
boto3 = "^1.34"  # Pour Backblaze B2 (S3 compatible)
```

### Critères de succès
```bash
poetry run pytest tests/test_jobs/test_audio_uploader.py -v
```

---

## Phase 7 : Health checks (TERMINÉE)

### Objectifs
- [x] Endpoint /health basique
- [x] Endpoint /health/detailed avec état des services
- [x] Endpoints /health/readiness et /health/liveness pour Kubernetes

### Fichiers à créer

#### `orchestrator/src/api/health.py`
```python
# Endpoints :
# - GET /health -> {"status": "ok"}
# - GET /health/detailed -> {
#     "status": "ok|degraded|unhealthy",
#     "services": {
#       "readeck": {"status": "ok", "latency_ms": 45},
#       "opennotebook": {"status": "ok", "latency_ms": 120},
#       "database": {"status": "ok"}
#     },
#     "uptime_seconds": 3600
#   }
# - GET /metrics  # Prometheus format (optionnel)
```

### Tests à créer

#### `tests/test_api/test_health.py`
```python
def test_health_basic():
def test_health_detailed_all_up():
def test_health_detailed_service_down():
def test_health_detailed_degraded():
```

### Critères de succès
```bash
poetry run pytest tests/test_api/test_health.py -v

curl http://localhost:8002/health
curl http://localhost:8002/health/detailed
```

---

## Phase 8 : Tests d'intégration (TERMINÉE)

### Objectifs
- [x] Tests e2e avec Docker Compose
- [x] Scénarios complets (RSS → Readeck → ON → Podcast)

### Fichiers à créer

#### `tests/integration/docker-compose.test.yml`
```yaml
# Stack de test avec :
# - Readeck (mock ou réel)
# - Open Notebook (mock ou réel)
# - sync-orchestrator
```

#### `tests/integration/test_e2e.py`
```python
@pytest.fixture(scope="module")
def docker_stack():
    # Démarrer docker-compose.test.yml
    yield
    # Arrêter

def test_rss_to_readeck():
def test_readeck_to_notebook():
def test_full_weekly_sync():
def test_podcast_generation():
def test_rss_feeds_served():
```

### Critères de succès
```bash
poetry run pytest tests/integration/ -v --slow
```

---

## Phase 9 : CI/CD (TERMINÉE)

### Objectifs
- [x] Workflow GitHub Actions pour tests
- [x] Build et push image Docker
- [x] Lint avec ruff

### Fichiers à créer

#### `.github/workflows/ci.yml`
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/ruff-action@v1

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          pip install poetry
          cd orchestrator && poetry install
      - name: Run tests
        run: |
          cd orchestrator && poetry run pytest --cov

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t weekly-digest ./orchestrator
```

### Critères de succès
- Le workflow passe sur GitHub
- Badge de statut dans README

---

## Checklist globale

### Phase 0 : Foundation (TERMINÉE)
- [x] README.md
- [x] AGENTS.md  
- [x] PLAN.md
- [x] .env.example
- [x] .gitignore
- [x] Structure dossiers

### Phase 1 : Clients API (TERMINÉE)
- [x] orchestrator/src/config.py
- [x] orchestrator/src/clients/readeck.py
- [x] orchestrator/src/clients/opennotebook.py
- [x] orchestrator/src/clients/__init__.py
- [x] tests/test_clients/test_readeck.py
- [x] tests/test_clients/test_opennotebook.py
- [x] tests/conftest.py
- [x] orchestrator/pyproject.toml

### Phase 2 : Base de données (TERMINÉE)
- [x] orchestrator/src/database.py
- [x] tests/test_database.py

### Phase 3 : RSS Fetcher (TERMINÉE)
- [x] orchestrator/src/jobs/rss_fetcher.py
- [x] tests/test_jobs/test_rss_fetcher.py

### Phase 4 : Sync hebdomadaire (TERMINÉE)
- [x] orchestrator/src/jobs/weekly_sync.py
- [x] tests/test_jobs/test_weekly_sync.py

### Phase 5 : Génération flux RSS (TERMINÉE)
- [x] orchestrator/src/api/feeds.py
- [x] tests/test_api/test_feeds.py

### Phase 6 : Upload audio (TERMINÉE)
- [x] orchestrator/src/jobs/audio_uploader.py
- [x] tests/test_jobs/test_audio_uploader.py

### Phase 7 : Health checks (TERMINÉE)
- [x] orchestrator/src/api/health.py
- [x] tests/test_api/test_health.py

### Phase 8 : Tests d'intégration (TERMINÉE)
- [x] tests/integration/docker-compose.test.yml
- [x] tests/integration/test_e2e.py
- [x] tests/integration/mocks/readeck/* (WireMock mappings)
- [x] tests/integration/mocks/opennotebook/* (WireMock mappings)

### Phase 9 : CI/CD (TERMINÉE)
- [x] .github/workflows/ci.yml
- [x] orchestrator/Dockerfile
- [x] orchestrator/src/api/main.py (FastAPI entry point)

---

## Notes pour le modèle AI

1. **Avant chaque phase** : Relire AGENTS.md pour les conventions et la doc API
2. **Pendant l'implémentation** : Suivre les critères de succès
3. **Après chaque phase** : Mettre à jour la checklist dans ce fichier
4. **En cas de blocage** : Consulter la section Troubleshooting de AGENTS.md
