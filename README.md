# ytb-edit

Application Windows pour télécharger des vidéos YouTube **publiques** et en extraire
plusieurs segments **sans réencodage** (qualité d'origine, découpe en quelques secondes).

## Installation (Windows, une seule fois)

1. **Python 3.12** (ou 3.11 / 3.13), si ce n'est pas déjà fait :
   `winget install Python.Python.3.12`
2. Récupérez le projet (bouton *Code → Download ZIP* sur GitHub, puis décompressez, ou
   `git clone`).
3. Double-cliquez sur **`installer.bat`**. Il :
   - crée un environnement Python isolé (`.venv`) et installe les dépendances ;
   - propose d'installer **FFmpeg** (indispensable) et **Deno** (requis par yt-dlp pour
     YouTube) via `winget`.

Ensuite, lancez l'application avec **`Lancer ytb-edit.bat`** (pas de fenêtre console).
Astuce : clic droit → *Envoyer vers → Bureau (créer un raccourci)*.

## Utilisation

1. **Dossier de sortie** : *Parcourir…* (mémorisé pour les fois suivantes).
2. **Collez une URL** YouTube, choisissez le mode (*Vidéo + audio*, *Vidéo seule*,
   *Audio seul*) puis **Entrée**. Le titre et la durée s'affichent.
3. **Ajoutez des segments** dans le panneau de droite :
   - saisie directe : `3:20`, `03:20`, `1:02:03`, ou rapide `320` (= 3:20) ;
   - boutons **−10 s / −1 s / +1 s / +10 s** ;
   - clavier dans un champ : **↑/↓** ±1 s, **Maj** ±10 s, **Ctrl** ±60 s, ou la molette ;
   - le **curseur à deux poignées** pour placer rapidement début et fin ;
   - **Entrée** ajoute le segment ; le suivant est pré-rempli à la suite.
   - Cliquez un segment *en attente* pour le modifier.
4. Ajoutez d'autres vidéos si besoin, puis **▶ Démarrer la file**.
5. Pendant le traitement, vous pouvez **ajouter des vidéos et des segments** : ils sont
   pris en charge automatiquement, sans retélécharger une vidéo déjà présente.
6. **Terminer / retirer de la file** supprime le fichier source temporaire d'une vidéo
   (les clips restent). À la fermeture, les fichiers temporaires sont supprimés
   (réglable dans *⚙ Paramètres*).

Les clips sont rangés ainsi :

```
<Dossier de sortie>\<Titre de la vidéo>\clip_001_03m20s-03m50s.mp4
                                        clip_002_05m10s-05m15s.mp4
```

Un fichier existant n'est jamais écrasé (`clip_001_…_1.mp4`).

### Précision de la découpe

Sans réencodage, une vidéo ne peut commencer que sur une *image clé* (toutes les
2 à 5 s environ sur YouTube). Le clip commence donc sur l'image clé **précédant** le
début demandé : il peut contenir quelques secondes de plus au début, mais ne coupe
jamais le passage voulu. La fin est précise. Le début réel est indiqué dans la liste des
segments. En *Audio seul*, la coupe est précise à la seconde.

### Formats

| Mode | Fichier | Détail |
|------|---------|--------|
| Vidéo + audio | `.mp4` | meilleures pistes disponibles (souvent AV1/VP9 + Opus) |
| Vidéo seule | `.mp4` | meilleure piste vidéo |
| Audio seul | `.m4a` | piste AAC d'origine ; option **MP3** dans les paramètres |

Les MP4 en AV1/VP9 se lisent avec VLC, les navigateurs et les lecteurs récents. Certains
logiciels anciens (ou de montage) peuvent préférer le H.264.

## En cas de problème

- **Une vidéo publique échoue soudainement** : YouTube a changé quelque chose. Lancez
  **`Mettre a jour yt-dlp.bat`**.
- **« FFmpeg est introuvable »** : relancez `installer.bat`, ou indiquez le dossier de
  FFmpeg dans *⚙ Paramètres*.
- **Détails techniques** : *⚙ Paramètres → Ouvrir le dossier des logs*
  (`%LOCALAPPDATA%\ytb-edit\logs\ytb-edit.log`).

## Développement

```powershell
.venv\Scripts\activate
pip install -e ".[dev]"
python -m ytb_edit --debug   # logs aussi dans le terminal
pytest                       # tests (sans réseau ; tests FFmpeg si FFmpeg est installé)
pytest -m network            # tests contre le vrai YouTube (optionnels)
ruff check . ; ruff format .
```

Architecture : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Usage responsable

Cet outil ne traite que des vidéos publiques accessibles sans authentification. Il ne
contourne aucune protection (DRM, restriction d'âge, contenu réservé, authentification) :
ces vidéos sont refusées. Vous êtes responsable du respect du droit d'auteur, des
licences applicables et des conditions d'utilisation de YouTube.
