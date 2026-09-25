# ytb-edit

Application Windows pour télécharger des vidéos YouTube **publiques** et en extraire
plusieurs segments **sans réencodage** (FFmpeg, copie de flux).

> Projet en cours de développement — voir [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Prérequis (Windows)

- Python 3.12 ou 3.13 (3.11 minimum)
- FFmpeg (ffmpeg + ffprobe) : `winget install Gyan.FFmpeg`
- Deno (requis par yt-dlp pour YouTube) : `winget install DenoLand.Deno`

Rouvrir le terminal après l'installation pour que le `PATH` soit à jour.

## Installation (développement)

```powershell
cd ytb-edit
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -e ".[dev]"
```

## Lancement

```powershell
python -m ytb_edit           # ou simplement : ytb-edit
python -m ytb_edit --debug   # affiche aussi les logs dans le terminal
```

Logs : `%LOCALAPPDATA%\ytb-edit\logs\ytb-edit.log`

## Tests et qualité

```powershell
pytest                 # tests unitaires et d'intégration (sans réseau)
pytest -m network      # tests accédant à YouTube (optionnels)
ruff check .
ruff format .
```

## Mise à jour de yt-dlp

YouTube évolue souvent ; en cas d'échec de téléchargement, commencer par :

```powershell
pip install -U "yt-dlp[default]"
```

## Usage responsable

Cet outil ne traite que des vidéos publiques accessibles sans authentification. Il ne
contourne aucune protection (DRM, restriction d'âge, contenu réservé, authentification).
Vous êtes responsable du respect du droit d'auteur, des licences applicables et des
conditions d'utilisation de YouTube.
