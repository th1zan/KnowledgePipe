# AGENTS.md - Guide pour Modèles AI

Ce fichier contient toutes les informations nécessaires pour qu'un modèle AI puisse travailler efficacement sur ce projet sans avoir à rechercher la documentation externe.

## 1. Vue d'ensemble du projet

**Weekly Digest** est un système self-hosted qui :
- Ingère des articles via RSS → Readeck (quotidien)
- Synchronise vers Open Notebook (hebdomadaire)
- Génère des synthèses textuelles et podcasts
- Expose des flux RSS pour consommation externe

### Stack technique
- **Orchestrateur** : Python 3.11+ / FastAPI / SQLite / APScheduler
- **Bookmarks** : Readeck (API REST)
- **Notebooks** : Open Notebook (FastAPI backend)
- **Conteneurisation** : Docker Compose
- **Tests** : pytest
- **Logs** : structlog (JSON)
- **CI** : GitHub Actions

## 2. Conventions de code

### Python
- Python 3.11+
- Formatter : `ruff format`
- Linter : `ruff check`
- Type hints obligatoires
- Docstrings Google style
- Imports triés avec `ruff`

### Structure des fichiers
```python
"""Module description."""
from __future__ import annotations

import stdlib_modules

import third_party_modules

from local_modules import x


class MyClass:
    """Class description."""
    
    def method(self, arg: str) -> bool:
        """Method description.
        
        Args:
            arg: Description of arg.
            
        Returns:
            Description of return value.
        """
        pass
```

### Tests
- Framework : pytest
- Fixtures dans `conftest.py`
- Mocks avec `pytest-mock` ou `unittest.mock`
- Nommage : `test_<function>_<scenario>`
- Tests async avec `pytest-asyncio`

### Logs (structlog)
```python
import structlog

logger = structlog.get_logger()

logger.info("event_name", key="value", count=42)
logger.error("error_occurred", error=str(e), context="sync")
```

### Configuration (Pydantic)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    readeck_url: str
    readeck_token: str
    
    class Config:
        env_file = ".env"
```

## 3. Architecture et flux de données

```
┌──────────────────────────────────────────────────────────────┐
│                      sync-orchestrator                        │
├───────────────┬───────────────┬───────────────┬──────────────┤
│   Scheduler   │    Clients    │   Database    │     API      │
│  (APScheduler)│               │   (SQLite)    │  (FastAPI)   │
├───────────────┼───────────────┼───────────────┼──────────────┤
│ - RSS daily   │ - Readeck     │ - rss_items   │ - /feeds/*   │
│ - Sync weekly │ - OpenNotebook│ - sync_logs   │ - /health    │
│               │ - Uploaders   │ - episodes    │ - /api/*     │
└───────────────┴───────────────┴───────────────┴──────────────┘
```

### Flux quotidien (RSS → Readeck)
1. `rss_fetcher.py` parse les flux RSS configurés
2. Filtre les articles déjà traités (via SQLite)
3. POST chaque nouvel article vers Readeck API
4. Enregistre le GUID dans SQLite

### Flux hebdomadaire (Readeck → Open Notebook)
1. `weekly_sync.py` récupère les bookmarks de la semaine via Readeck API
2. Crée un nouveau notebook dans Open Notebook
3. Ajoute chaque bookmark comme source (URL ou texte extrait pour PDFs)
4. Déclenche la génération de summary
5. Déclenche la génération de podcast
6. Attend la fin du traitement (polling)
7. Upload l'audio si hébergement externe configuré
8. Met à jour les flux RSS

## 4. Documentation API Readeck

### Authentification

Token Bearer généré depuis **Profil > API Tokens** dans l'UI Readeck.

```bash
curl -H "Authorization: Bearer <TOKEN>" https://readeck/api/profile
```

### Endpoints principaux

#### Lister les bookmarks
```http
GET /api/bookmarks
```

**Paramètres de filtre** :
| Paramètre | Type | Description |
|-----------|------|-------------|
| `search` | string | Recherche full-text |
| `title` | string | Filtre par titre |
| `labels` | string | Un ou plusieurs labels |
| `is_marked` | boolean | Favoris |
| `is_archived` | boolean | Archivés |
| `range_start` | string (ISO date) | Date de début |
| `range_end` | string (ISO date) | Date de fin |
| `read_status` | array | `unread`, `reading`, `read` |

**Tri** : `sort=created`, `sort=-created` (desc)

**Pagination** : `page=1&limit=20`

**Exemple - Bookmarks des 7 derniers jours** :
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://readeck/api/bookmarks?range_start=2024-01-08&sort=-created"
```

#### Créer un bookmark
```http
POST /api/bookmarks
Content-Type: application/json

{
  "url": "https://example.com/article",
  "title": "Titre optionnel",
  "labels": ["tech", "lecture"]
}
```

**Réponse** : `202 Accepted` avec header `Bookmark-Id`

#### Détails d'un bookmark
```http
GET /api/bookmarks/{id}
```

**Réponse** :
```json
{
  "id": "abc123",
  "url": "https://example.com/article",
  "title": "Titre de l'article",
  "site_name": "Example",
  "site": "example.com",
  "authors": ["John Doe"],
  "published": "2024-01-10T08:00:00Z",
  "created": "2024-01-15T10:30:00Z",
  "type": "article",
  "has_article": true,
  "description": "Description courte",
  "is_marked": false,
  "is_archived": false,
  "labels": ["tech"],
  "word_count": 1500,
  "reading_time": 6,
  "resources": {
    "article": { "src": "/api/bookmarks/abc123/article" },
    "image": { "src": "/api/bookmarks/abc123/image" }
  }
}
```

#### Récupérer le contenu extrait
```http
GET /api/bookmarks/{id}/article
```
Retourne le HTML extrait.

```http
GET /api/bookmarks/{id}/article.md
```
Retourne le Markdown extrait.

#### Mettre à jour un bookmark
```http
PATCH /api/bookmarks/{id}
Content-Type: application/json

{
  "is_marked": true,
  "labels": ["tech", "important"],
  "add_labels": ["nouveau"],
  "remove_labels": ["ancien"]
}
```

#### Supprimer un bookmark
```http
DELETE /api/bookmarks/{id}
```

### Labels

```http
GET /api/bookmarks/labels
```

**Réponse** :
```json
[
  { "name": "tech", "count": 15 },
  { "name": "lecture", "count": 8 }
]
```

### Exemple complet Python

```python
import requests
from datetime import datetime, timedelta

class ReadeckClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
    
    def add_bookmark(self, url: str, title: str | None = None, labels: list[str] | None = None) -> str | None:
        """Ajoute un bookmark et retourne son ID."""
        data = {"url": url}
        if title:
            data["title"] = title
        if labels:
            data["labels"] = labels
        
        response = requests.post(
            f"{self.base_url}/api/bookmarks",
            json=data,
            headers=self.headers
        )
        
        if response.status_code in (200, 201, 202):
            return response.headers.get("Bookmark-Id")
        return None
    
    def get_week_bookmarks(self) -> list[dict]:
        """Récupère les bookmarks des 7 derniers jours."""
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{self.base_url}/api/bookmarks",
            params={"range_start": since, "sort": "-created"},
            headers=self.headers
        )
        
        if response.status_code == 200:
            return response.json()
        return []
    
    def get_bookmark_content(self, bookmark_id: str, format: str = "md") -> str | None:
        """Récupère le contenu extrait d'un bookmark."""
        endpoint = f"/api/bookmarks/{bookmark_id}/article"
        if format == "md":
            endpoint += ".md"
        
        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            return response.text
        return None
    
    def health_check(self) -> bool:
        """Vérifie la connexion à Readeck."""
        try:
            response = requests.get(
                f"{self.base_url}/api/profile",
                headers=self.headers,
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
```

## 5. Documentation API Open Notebook

### Authentification

Header Bearer avec le mot de passe configuré (`OPEN_NOTEBOOK_PASSWORD`).

```bash
curl -H "Authorization: Bearer your_password" http://open-notebook:5055/api/notebooks
```

**Documentation Swagger** : `http://localhost:5055/docs`

### Endpoints principaux

#### Notebooks

**Créer un notebook** :
```http
POST /api/notebooks
Content-Type: application/json

{
  "name": "Semaine du 15/01/2024",
  "description": "Digest hebdomadaire"
}
```

**Réponse** :
```json
{
  "id": "notebook:abc123",
  "name": "Semaine du 15/01/2024",
  "description": "Digest hebdomadaire",
  "archived": false,
  "created": "2024-01-15T10:00:00Z",
  "source_count": 0,
  "note_count": 0
}
```

**Lister les notebooks** :
```http
GET /api/notebooks
```

**Récupérer un notebook** :
```http
GET /api/notebooks/{id}
```

#### Sources

**Ajouter une URL** :
```http
POST /api/sources
Content-Type: multipart/form-data

type=link
notebooks=["notebook:abc123"]
url=https://example.com/article
embed=true
async_processing=true
```

**Ajouter du texte** :
```http
POST /api/sources
Content-Type: multipart/form-data

type=text
notebooks=["notebook:abc123"]
content=Votre texte ici...
title=Titre du document
embed=true
```

**Ajouter un fichier (PDF)** :
```http
POST /api/sources
Content-Type: multipart/form-data

type=upload
notebooks=["notebook:abc123"]
file=@document.pdf
embed=true
async_processing=true
```

**Réponse (async)** :
```json
{
  "id": "source:xyz789",
  "title": "Processing...",
  "command_id": "command:cmd123",
  "status": "new"
}
```

**Vérifier le statut** :
```http
GET /api/sources/{id}/status
```

**Lier une source existante à un notebook** :
```http
POST /api/notebooks/{notebook_id}/sources/{source_id}
```

#### Transformations (Insights)

**Appliquer une transformation à une source** :
```http
POST /api/sources/{source_id}/insights
Content-Type: application/json

{
  "transformation_id": "transformation:summary"
}
```

**Lister les transformations disponibles** :
```http
GET /api/transformations
```

#### Podcasts

**Générer un podcast** :
```http
POST /api/podcasts/generate
Content-Type: application/json

{
  "episode_name": "Semaine du 15/01/2024",
  "notebook_id": "notebook:abc123",
  "episode_profile": "default",
  "speaker_profile": "default"
}
```

**Réponse** :
```json
{
  "job_id": "job:abc123",
  "status": "submitted",
  "message": "Podcast generation started"
}
```

**Suivre le statut du job** :
```http
GET /api/podcasts/jobs/{job_id}
```

**Réponse** :
```json
{
  "job_id": "job:abc123",
  "status": "completed",
  "episode_id": "podcast_episode:xyz"
}
```

**Lister les épisodes** :
```http
GET /api/podcasts/episodes
```

**Télécharger l'audio** :
```http
GET /api/podcasts/episodes/{id}/audio
```

#### Notes

**Créer une note** :
```http
POST /api/notes
Content-Type: application/json

{
  "title": "Résumé",
  "content": "Contenu de la note",
  "note_type": "human",
  "notebook_id": "notebook:abc123"
}
```

**Lister les notes d'un notebook** :
```http
GET /api/notes?notebook_id=notebook:abc123
```

#### Recherche

**Recherche vectorielle** :
```http
POST /api/search
Content-Type: application/json

{
  "query": "intelligence artificielle",
  "type": "vector",
  "limit": 10,
  "search_sources": true,
  "search_notes": true
}
```

### Exemple complet Python

```python
import requests
import time
from typing import Any

class OpenNotebookClient:
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {password}"}
    
    def create_notebook(self, name: str, description: str = "") -> dict[str, Any]:
        """Crée un notebook et retourne ses infos."""
        response = requests.post(
            f"{self.base_url}/api/notebooks",
            json={"name": name, "description": description},
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def add_source_url(
        self,
        notebook_id: str,
        url: str,
        embed: bool = True,
        async_processing: bool = True
    ) -> dict[str, Any]:
        """Ajoute une URL comme source."""
        response = requests.post(
            f"{self.base_url}/api/sources",
            data={
                "type": "link",
                "notebooks": f'["{notebook_id}"]',
                "url": url,
                "embed": str(embed).lower(),
                "async_processing": str(async_processing).lower()
            },
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def add_source_text(
        self,
        notebook_id: str,
        content: str,
        title: str,
        embed: bool = True
    ) -> dict[str, Any]:
        """Ajoute du texte comme source."""
        response = requests.post(
            f"{self.base_url}/api/sources",
            data={
                "type": "text",
                "notebooks": f'["{notebook_id}"]',
                "content": content,
                "title": title,
                "embed": str(embed).lower()
            },
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def wait_for_source(self, source_id: str, timeout: int = 300) -> bool:
        """Attend que la source soit traitée."""
        start = time.time()
        while time.time() - start < timeout:
            response = requests.get(
                f"{self.base_url}/api/sources/{source_id}/status",
                headers=self.headers
            )
            if response.status_code == 200:
                status = response.json().get("status")
                if status == "completed":
                    return True
                if status == "failed":
                    return False
            time.sleep(5)
        return False
    
    def generate_podcast(
        self,
        notebook_id: str,
        episode_name: str,
        episode_profile: str = "default",
        speaker_profile: str = "default"
    ) -> dict[str, Any]:
        """Lance la génération d'un podcast."""
        response = requests.post(
            f"{self.base_url}/api/podcasts/generate",
            json={
                "notebook_id": notebook_id,
                "episode_name": episode_name,
                "episode_profile": episode_profile,
                "speaker_profile": speaker_profile
            },
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def wait_for_podcast(self, job_id: str, timeout: int = 600) -> str | None:
        """Attend la fin de génération et retourne l'episode_id."""
        start = time.time()
        while time.time() - start < timeout:
            response = requests.get(
                f"{self.base_url}/api/podcasts/jobs/{job_id}",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "completed":
                    return data.get("episode_id")
                if data.get("status") == "failed":
                    return None
            time.sleep(10)
        return None
    
    def download_episode_audio(self, episode_id: str) -> bytes | None:
        """Télécharge l'audio d'un épisode."""
        response = requests.get(
            f"{self.base_url}/api/podcasts/episodes/{episode_id}/audio",
            headers=self.headers
        )
        if response.status_code == 200:
            return response.content
        return None
    
    def get_notebook_notes(self, notebook_id: str) -> list[dict]:
        """Récupère les notes d'un notebook (dont le summary généré)."""
        response = requests.get(
            f"{self.base_url}/api/notes",
            params={"notebook_id": notebook_id},
            headers=self.headers
        )
        if response.status_code == 200:
            return response.json()
        return []
    
    def health_check(self) -> bool:
        """Vérifie la connexion à Open Notebook."""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
```

## 6. Exemples de workflows complets

### Workflow : Sync hebdomadaire complète

```python
from datetime import datetime

def weekly_sync():
    """Synchronisation hebdomadaire complète."""
    logger.info("weekly_sync_started")
    
    # 1. Récupérer les bookmarks de la semaine
    readeck = ReadeckClient(settings.readeck_url, settings.readeck_token)
    bookmarks = readeck.get_week_bookmarks()
    
    if not bookmarks:
        logger.info("no_bookmarks_found")
        return
    
    logger.info("bookmarks_found", count=len(bookmarks))
    
    # 2. Créer le notebook
    on = OpenNotebookClient(settings.open_notebook_url, settings.open_notebook_password)
    week_name = f"Semaine du {datetime.now().strftime('%d/%m/%Y')}"
    notebook = on.create_notebook(week_name, f"{len(bookmarks)} articles")
    notebook_id = notebook["id"]
    
    logger.info("notebook_created", notebook_id=notebook_id)
    
    # 3. Ajouter les sources
    source_ids = []
    for bm in bookmarks:
        try:
            # Pour les PDFs, utiliser le texte extrait
            if bm["url"].endswith(".pdf") or bm.get("type") == "pdf":
                content = readeck.get_bookmark_content(bm["id"], format="md")
                if content:
                    source = on.add_source_text(notebook_id, content, bm["title"])
                else:
                    source = on.add_source_url(notebook_id, bm["url"])
            else:
                source = on.add_source_url(notebook_id, bm["url"])
            
            source_ids.append(source["id"])
            logger.info("source_added", source_id=source["id"], title=bm["title"])
        except Exception as e:
            logger.error("source_add_failed", url=bm["url"], error=str(e))
    
    # 4. Attendre le traitement des sources
    for source_id in source_ids:
        if not on.wait_for_source(source_id, timeout=120):
            logger.warning("source_processing_timeout", source_id=source_id)
    
    # 5. Générer le podcast
    job = on.generate_podcast(notebook_id, week_name)
    logger.info("podcast_generation_started", job_id=job["job_id"])
    
    episode_id = on.wait_for_podcast(job["job_id"], timeout=600)
    if episode_id:
        logger.info("podcast_generated", episode_id=episode_id)
        
        # 6. Upload audio si nécessaire
        if settings.audio_hosting != "local":
            audio_data = on.download_episode_audio(episode_id)
            if audio_data:
                upload_audio(audio_data, week_name)
    else:
        logger.error("podcast_generation_failed")
    
    # 7. Régénérer les flux RSS
    regenerate_feeds()
    
    logger.info("weekly_sync_completed")
```

### Workflow : RSS fetcher quotidien

```python
import feedparser
from database import get_db, RssItem

def process_rss_feeds():
    """Traite tous les flux RSS configurés."""
    logger.info("rss_processing_started")
    
    readeck = ReadeckClient(settings.readeck_url, settings.readeck_token)
    feeds = settings.rss_feeds.split(",")
    
    new_count = 0
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url.strip())
            
            for entry in feed.entries:
                guid = entry.get("id") or entry.get("link")
                
                # Vérifier si déjà traité
                with get_db() as db:
                    if db.query(RssItem).filter_by(guid=guid).first():
                        continue
                
                # Ajouter à Readeck
                bookmark_id = readeck.add_bookmark(
                    url=entry.link,
                    title=entry.get("title"),
                    labels=["rss", feed.feed.get("title", "unknown")]
                )
                
                if bookmark_id:
                    # Enregistrer en base
                    with get_db() as db:
                        db.add(RssItem(
                            guid=guid,
                            url=entry.link,
                            title=entry.get("title"),
                            feed_url=feed_url,
                            bookmark_id=bookmark_id
                        ))
                        db.commit()
                    
                    new_count += 1
                    logger.info("rss_item_added", title=entry.get("title"))
        
        except Exception as e:
            logger.error("rss_feed_failed", feed_url=feed_url, error=str(e))
    
    logger.info("rss_processing_completed", new_items=new_count)
```

## 7. Troubleshooting courant

### Erreur d'authentification Readeck
```
401 Unauthorized
```
**Cause** : Token expiré ou invalide.
**Solution** : Régénérer le token dans Profil > API Tokens.

### Erreur d'authentification Open Notebook
```
403 Forbidden
```
**Cause** : Mot de passe incorrect.
**Solution** : Vérifier `OPEN_NOTEBOOK_PASSWORD` dans `.env`.

### Source bloquée en "processing"
```json
{"status": "processing", "progress": 0}
```
**Cause** : Problème de connectivité ou de modèle LLM.
**Solutions** :
1. Vérifier les logs : `docker compose logs open-notebook-backend`
2. Retry manuel : `POST /api/sources/{id}/retry`
3. Vérifier la config des modèles dans Open Notebook

### Podcast ne se génère pas
**Causes possibles** :
1. Modèle TTS non configuré
2. Pas assez de contenu dans le notebook
3. Timeout de génération

**Solutions** :
1. Vérifier la config speaker/episode profiles
2. Ajouter plus de sources
3. Augmenter le timeout

### Flux RSS vide
**Cause** : Aucune sync hebdomadaire complétée.
**Solution** : 
1. Vérifier que des bookmarks existent : `GET /api/bookmarks`
2. Forcer une sync : `POST /api/sync/trigger`
3. Vérifier les logs de génération

### Base SQLite corrompue
```
sqlite3.DatabaseError: database disk image is malformed
```
**Solution** :
```bash
# Backup
cp orchestrator/data/state.db orchestrator/data/state.db.bak

# Repair
sqlite3 orchestrator/data/state.db "PRAGMA integrity_check;"
sqlite3 orchestrator/data/state.db ".recover" | sqlite3 orchestrator/data/state_new.db
mv orchestrator/data/state_new.db orchestrator/data/state.db
```

## 8. Ressources externes

### Readeck
- **Repo** : https://codeberg.org/readeck/readeck
- **Doc API embarquée** : `http://readeck:8000/docs/api`
- **Scopes OAuth** : `bookmarks:read`, `bookmarks:write`, `profile:read`

### Open Notebook
- **Repo** : https://github.com/lfnovo/open-notebook
- **Swagger** : `http://open-notebook:5055/docs`
- **Doc ReDoc** : `http://open-notebook:5055/redoc`

### Librairies clés
- **feedparser** : https://feedparser.readthedocs.io/
- **feedgen** : https://feedgen.kiesow.be/
- **APScheduler** : https://apscheduler.readthedocs.io/
- **structlog** : https://www.structlog.org/
- **Pydantic Settings** : https://docs.pydantic.dev/latest/concepts/pydantic_settings/
