# ytb-edit — Architecture (Étape 1, proposition à valider)

> Statut : **validée** (voir §20). Ce document sert de référence pour les étapes
> suivantes et est mis à jour au fil des décisions.

Outil personnel Windows : télécharger des vidéos YouTube publiques puis en extraire
des segments **sans réencodage**, via une file de tâches dans une interface graphique.

---

## 1. Contradictions et tensions détectées dans le cahier des charges

| # | Tension | Décision proposée |
|---|---------|-------------------|
| C1 | **« ±1 s » vs « pas de réencodage »**. En copie de flux, une vidéo ne peut commencer que sur une *image clé*. Sur YouTube, l'écart entre images clés est typiquement de 2 à 5 s (parfois plus). La précision ±1 s n'est donc **pas garantissable** sans réencodage. | Le début est **aligné sur l'image clé précédente** : le clip peut commencer jusqu'à ~2-5 s *plus tôt* que demandé, mais ne coupe **jamais** le contenu voulu. La fin est précise (±1 image/paquet). L'UI affiche le début réel. Le « smart cut » (réencoder uniquement les premières secondes) est reporté en V2. |
| C2 | **« Meilleure qualité » vs « MP4 »**. La meilleure piste YouTube est souvent en **AV1 ou VP9** (+ audio **Opus**). Ces codecs se placent très bien dans un MP4, mais certains logiciels (anciens lecteurs Windows, Premiere Pro…) les lisent mal. Le « tout compatible » (H.264/AAC) est souvent limité à 1080p. | **Meilleure qualité absolue**, conteneur MP4. Réglage « préférer la compatibilité (H.264/AAC) » envisageable plus tard. *À valider selon l'usage des clips.* |
| C3 | **« Audio seul en M4A » vs « meilleure piste audio »**. La meilleure piste audio est généralement Opus (~130-160 kb/s), pas AAC (128 kb/s). | Extension adaptée au codec : **`.opus`** si Opus, **`.m4a`** si AAC. Pas de réencodage. |
| C4 | **Dossier temporaire nommé d'après le titre**. Un titre peut changer, contenir des caractères interdits ou être dupliqué. | Cache indexé par **identifiant YouTube** (`cache/dQw4w9WgXcQ/`). Le titre ne sert qu'au dossier de sortie. |
| C5 | **Nettoyage automatique du source vs « ajouter des segments à tout moment »**. On ne peut pas savoir si un segment sera encore ajouté. | Le cache est une **optimisation, jamais une dépendance** : si le source a été supprimé et qu'un segment est ajouté, la vidéo est simplement retéléchargée. Politique de nettoyage en §9. |
| C6 | **Choix d'un mode par vidéo vs modification du mode après téléchargement**. | Les pistes vidéo et audio sont stockées **séparément** dans le cache ; seules les pistes nécessaires au mode sont téléchargées. Changer de mode ne télécharge que la piste manquante. |
| C7 | **« Lancement de la file » explicite vs « ajout pendant le traitement »**. | La file a un état *En cours / En pause*. Une fois démarrée, toute vidéo ou tout segment ajouté est pris en charge automatiquement. |
| C8 | **Pause d'une tâche** : yt-dlp n'offre pas de vraie pause d'un téléchargement en cours. | V1 : *mettre la file en pause* (aucune nouvelle opération ne démarre) + *annuler* tâche/segment. Pause fine par tâche : V2. |
| C9 | **Choisir le dossier temporaire au lancement** alourdit le parcours. | Dossier de sortie visible en permanence dans la fenêtre (mémorisé). Dossier cache : valeur par défaut, modifiable dans *Paramètres*. |

---

## 2. Décisions techniques

| Sujet | Choix | Raison principale |
|-------|-------|-------------------|
| Langage | Python **3.12 ou 3.13** recommandé (3.11 minimum) | Supporté par toutes les dépendances. |
| GUI | **PySide6** (Qt 6, paquet `PySide6-Essentials`) | Rendu Windows natif, signaux thread-safe, widgets riches, licence LGPL (≠ PyQt en GPL), binding officiel Qt, bon support PyInstaller/Nuitka. Tkinter : trop limité (pas de range slider, rendu daté). Solutions web (Flet, pywebview…) : une couche de plus sans bénéfice ici. |
| Slider début/fin | **`superqt.QRangeSlider`** | Qt n'a pas de slider à deux poignées ; `superqt` est petit, maintenu, compatible PySide6. Évite ~150 lignes de widget custom. |
| YouTube | **yt-dlp** (API Python, extra `[default]`) | Standard de fait, maintenu très activement, métadonnées structurées, hooks de progression, exceptions typées. |
| Runtime JS | **Deno** (installé à part) | Depuis fin 2025, yt-dlp a besoin d'un runtime JavaScript externe pour le support complet de YouTube. C'est la configuration officielle de yt-dlp, pas un contournement. *À revérifier à l'étape 4.* |
| FFmpeg | **FFmpeg système** (+ chemin optionnel dans les paramètres, + dossier `bin/` réservé au futur packaging) | Le plus simple à maintenir : `winget install Gyan.FFmpeg`, mises à jour indépendantes de l'app. |
| Paramètres | Fichier **JSON** dans `%APPDATA%\ytb-edit\` | Lisible, testable, indépendant de Qt (QSettings écrirait dans le registre et couplerait le cœur à Qt). |
| Chemins système | **platformdirs** | Chemins Windows corrects, tests possibles sous Linux/CI. |
| Logs | `logging` standard, fichier rotatif `%LOCALAPPDATA%\ytb-edit\logs\` | Aucune dépendance. |
| Concurrence | `threading` + `subprocess` dans le cœur, pont Qt dans l'UI | Le cœur reste testable sans Qt. |
| Tests | pytest (+ pytest-qt pour quelques tests d'UI) | Standard. |
| Qualité | ruff (lint + format) ; mypy optionnel | Un seul outil rapide. |

---

## 3. Architecture générale

```
┌──────────────────────────── ui/ (PySide6) ─────────────────────────────┐
│ MainWindow · QueueView · TaskEditor · TimeInput · SettingsDialog         │
│        │ commandes (appels de méthode)          ▲ événements (Signal Qt) │
│        ▼                                        │                        │
│                         EngineBridge (QObject)                           │
└────────┼────────────────────────────────────────┼────────────────────────┘
         ▼                                        │ callback emit(event)
┌─────────────────────────── core/ (pur Python) ──┼────────────────────────┐
│ Engine : état des tâches (verrou) + 3 workers   │                        │
│   ├─ worker « infos »        (2 threads)        │                        │
│   ├─ worker « téléchargement » (1 thread)       │                        │
│   └─ worker « découpe »      (1 thread)         │                        │
│ models · timecode · segments · errors · events · scheduling             │
└────────┼─────────────────────────────────────────────────────────────────┘
         ▼
┌──────────────────────── services/ (I/O, outils externes) ───────────────┐
│ youtube (yt-dlp) · ffmpeg (ffprobe/ffmpeg) · process (sous-processus)    │
│ files (noms Windows, chemins uniques, espace disque) · cache            │
└──────────────────────────────────────────────────────────────────────────┘
settings.py · logging_setup.py · app.py (assemblage)
```

Règles :
- `core/` n'importe **jamais** Qt. `ui/` ne manipule **jamais** les modèles directement :
  il envoie des commandes à l'`Engine` et reçoit des instantanés immuables.
- `services/` ne connaît ni l'UI ni la file : ce sont des fonctions/classes
  « fais cette opération, signale ta progression, respecte ce jeton d'annulation ».
- L'`Engine` reçoit ses services en paramètres du constructeur → en test, on injecte des
  faux (pas de YouTube, éventuellement pas de FFmpeg).

---

## 4. Structure des dossiers

```
ytb-edit/
├── pyproject.toml
├── README.md
├── docs/
│   └── ARCHITECTURE.md
├── src/
│   └── ytb_edit/
│       ├── __init__.py
│       ├── __main__.py          # python -m ytb_edit
│       ├── app.py               # assemblage : settings, logs, vérif outils, engine, fenêtre
│       ├── paths.py             # emplacements : paramètres, logs, cache (platformdirs)
│       ├── settings.py          # AppSettings + chargement/sauvegarde JSON
│       ├── logging_setup.py     # configuration logging (fichier + console)
│       ├── core/
│       │   ├── models.py        # dataclasses & enums
│       │   ├── timecode.py      # "3:20" ⇄ 200 s, formats d'affichage et de nom de fichier
│       │   ├── segments.py      # validation des segments
│       │   ├── errors.py        # hiérarchie d'erreurs + messages utilisateur
│       │   ├── events.py        # événements émis vers l'UI
│       │   ├── scheduling.py    # fonctions pures : « quelle est la prochaine opération ? »
│       │   └── engine.py        # file, verrou, workers, annulation
│       ├── services/
│       │   ├── youtube.py       # validation d'URL, métadonnées, téléchargement
│       │   ├── ffmpeg.py        # détection, ffprobe, images clés, découpe
│       │   ├── process.py       # exécution annulable de sous-processus (+ Job Object Windows)
│       │   ├── files.py         # nettoyage noms Windows, nommage clips, chemin unique, espace disque
│       │   └── cache.py         # cache des sources (par video_id), purge
│       └── ui/
│           ├── bridge.py        # EngineBridge : événements → signaux Qt
│           ├── main_window.py
│           ├── queue_view.py    # arbre vidéos → segments + états
│           ├── task_editor.py   # titre, durée, mode, liste des segments
│           ├── time_input.py    # champ mm:ss + boutons ±
│           ├── settings_dialog.py
│           └── summary.py       # panneau de résumé final
└── tests/
    ├── conftest.py              # fixtures : vidéo de test générée par FFmpeg, faux services
    ├── unit/
    ├── integration/             # FFmpeg réel, fichiers locaux
    └── network/                 # YouTube réel, désactivés par défaut
```

~20 modules, chacun avec une responsabilité unique. Pas de couches « repository »,
« factory » ou « interface » artificielles.

---

## 5. Modèle de données

Temps représentés en **secondes entières (`int`)** : la précision à la seconde suffit,
pas besoin d'une classe `Timecode`.

```python
# Enums
class OutputMode(Enum):      AUDIO_VIDEO, VIDEO_ONLY, AUDIO_ONLY
class TaskStatus(Enum):      FETCHING_INFO, READY, DOWNLOADING, DOWNLOADED,
                             PROCESSING, COMPLETED, FAILED, CANCELLED
class SegmentStatus(Enum):   PENDING, PROCESSING, DONE, FAILED, CANCELLED

# Données
@dataclass(frozen=True) VideoInfo      # video_id, url canonique, title, duration_s,
                                       # has_video, has_audio, taille estimée, uploader
@dataclass(frozen=True) SourceFiles    # video_path | None, audio_path | None, codecs
@dataclass Segment                     # id, number (clip_00N, stable), start_s, end_s,
                                       # mode, status, actual_start_s, output_path, error
@dataclass VideoTask                   # id, url, info, mode, segments, status,
                                       # download_progress, source, error
@dataclass AppSettings                 # output_dir, cache_dir, keep_cache_on_exit,
                                       # cache_limit_gb, ffmpeg_path, default_mode, …
```

Classes **non retenues** et pourquoi :
- `DownloadInfo` → remplacé par `VideoInfo` (avant) + `SourceFiles` (après téléchargement).
- `ProcessingResult` → inutile : chaque `Segment` porte son propre résultat
  (`status`, `output_path`, `error`). Le résumé final est calculé à partir des tâches.

Erreurs (`core/errors.py`) : une base `AppError(user_message, details)` et des
sous-classes ciblées : `InvalidUrlError`, `VideoUnavailableError`, `UnsupportedVideoError`
(live, restriction d'âge, DRM, membres…), `NetworkError`, `DownloadError`,
`MissingStreamError`, `SourceCorruptedError`, `FFmpegError`, `ToolMissingError`,
`InvalidSegmentError`, `DiskSpaceError`, `OperationCancelled`.

Événements (`core/events.py`) : `TaskChanged(snapshot)`, `DownloadProgress(task_id,
fraction, speed, eta, stream)`, `SegmentChanged(snapshot)`, `QueueIdle(summary)`.
Les instantanés sont des copies figées : l'UI ne peut pas corrompre l'état du cœur.

**Mode par segment en interne** : chaque segment reçoit le mode de la vidéo à sa
création ; changer le mode de la vidéo met à jour les segments encore en attente.
L'UI V1 n'expose que le mode par vidéo, mais un mode par segment en V2 ne coûtera rien.

---

## 6. Machine à états

```
Tâche :
 FETCHING_INFO ──ok──▶ READY ──(file en cours ET ≥1 segment)──▶ DOWNLOADING
       │                 ▲                                        │
       └──erreur──▶ FAILED ◀──────────────erreur──────────────────┤
                         │ (Réessayer)                             ▼
                         └──────▶ READY                        DOWNLOADED
                                                                   │ segment en attente
                                                                   ▼
                                     COMPLETED ◀──tous terminés── PROCESSING
                                         │  nouveau segment ajouté     ▲
                                         └─────────────────────────────┘
 Toute tâche non terminée ──(Annuler)──▶ CANCELLED

Segment : PENDING ─▶ PROCESSING ─▶ DONE | FAILED ;  PENDING|PROCESSING ─(Annuler)─▶ CANCELLED
```

- Seul l'`Engine` change les états, via une table de transitions autorisées (testée).
- `COMPLETED` est **réouvrable** : ajouter un segment repasse la tâche en `PROCESSING`
  (ou `DOWNLOADING` si le source a été purgé).
- Un segment en échec n'échoue pas la tâche : la tâche affiche « 3/4 segments, 1 erreur ».
- Seuls les segments `PENDING` sont modifiables/supprimables.

---

## 7. Pipeline complet

```
1. Saisie URL
   └─ validation syntaxique (hôtes youtube.com, m., music., youtu.be, /shorts/, /live/),
      extraction de l'ID (11 caractères), URL canonique, paramètres list=/t= ignorés.
   └─ doublon (même ID déjà dans la file) → sélection de la tâche existante.
2. Métadonnées (worker « infos », yt-dlp extract_info(download=False))
   └─ rejet : live/à venir, DRM, restriction d'âge, membres, privée, supprimée.
   └─ vérification des pistes disponibles vs mode (ex. pas d'audio → erreur explicite).
   └─ affichage titre + durée → slider activé.
3. Ajout des segments (validation immédiate dans l'UI et à nouveau dans le cœur).
4. Téléchargement (worker « téléchargement »), si file en cours ET ≥1 segment en attente
   ET pistes nécessaires absentes du cache.
   └─ vérification de l'espace disque (taille estimée × 1,1 + marge).
   └─ pistes séparées : meilleure vidéo et/ou meilleur audio → cache/<video_id>/.
5. Validation du source (ffprobe : pistes présentes, durée ≈ durée annoncée).
   └─ fichier corrompu → suppression + 1 retéléchargement automatique, puis échec.
   └─ écriture de cache/<video_id>/source.json (marqueur « source complet »).
6. Découpe (worker « découpe »), segment par segment, dans l'ordre de la file.
   └─ recherche de l'image clé ≤ début (ffprobe sur les paquets, sans décodage).
   └─ ffmpeg -c copy vers <nom>.part.mp4, puis renommage vers le nom final unique.
   └─ vérification rapide du clip (ffprobe).
7. Tâche COMPLETED (réouvrable).
8. Nettoyage du cache selon la politique (§9).
9. File inactive → résumé final.
```

---

## 8. Stratégie de gestion de la file et concurrence

**Trois workers spécialisés, chacun avec une concurrence fixe :**

| Worker | Threads | Justification |
|--------|---------|---------------|
| Infos | 2 | Rapide (1-3 s) ; ne doit **jamais** attendre derrière un téléchargement de 2 Go, sinon coller une URL « gèle » l'affichage du titre. |
| Téléchargement | 1 | La bande passante est le goulot : paralléliser n'accélère généralement pas et multiplie l'espace disque occupé. Réglable plus tard (`max_downloads`). |
| Découpe | 1 | En copie de flux, un clip prend typiquement < 1 s à quelques secondes ; c'est limité par le disque, pas le CPU. |

Effet pipeline : pendant que la vidéo 2 se télécharge, les segments de la vidéo 1 sont
découpés. Au total 4 threads d'arrière-plan + le thread UI, CPU quasi nul.

**Mécanique :**
- L'`Engine` détient la liste ordonnée des tâches, protégée par un `threading.Lock`
  + une `Condition`.
- Chaque worker boucle : *attendre → choisir la prochaine opération → l'exécuter hors
  verrou → publier le résultat*.
- Le choix de la prochaine opération est fait par des **fonctions pures** de
  `core/scheduling.py` (`next_info_job`, `next_download_job`, `next_cut_job`) → la logique
  d'ordonnancement se teste sans aucun thread.
- Toute commande de l'UI (`add_video`, `add_segment`, `set_mode`, `cancel_…`, `retry`,
  `start`, `pause`, `close_task`) modifie l'état sous verrou puis `notify_all()` : un
  segment ajouté pendant le traitement est pris dès qu'un worker est libre.
- Ordre de traitement : ordre des vidéos dans la file, puis numéro de segment.
- Chaque opération est encapsulée : toute exception (y compris un bug) est attrapée,
  journalisée, et transformée en `FAILED` sur la tâche/le segment concerné. **Le worker
  continue toujours.**

**Parcours simplifié (un seul concept) :** coller une URL crée immédiatement la tâche dans
la file (état `FETCHING_INFO`). Il n'y a pas de « brouillon » séparé ; le téléchargement ne
démarre que lorsque la file est en cours **et** qu'au moins un segment existe.

---

## 9. Stratégie de téléchargement et de cache

**Sélection des formats (yt-dlp) :**
- Vidéo + audio : `bestvideo` **et** `bestaudio`, téléchargés comme deux fichiers
  séparés, **sans fusion**.
- Vidéo seule : `bestvideo`. Audio seul : `bestaudio`.
- Repli si YouTube ne propose qu'un format combiné (vieilles vidéos) : `best`, la découpe
  sélectionne alors les pistes dans le même fichier.
- Pourquoi ne pas fusionner au téléchargement : la fusion réécrit tout le fichier
  (temps + double espace disque temporaire) alors que FFmpeg peut combiner les deux
  pistes directement lors de la découpe de chaque clip. Et le cache sert les trois modes.

**Options yt-dlp :** `noplaylist=True`, `retries`/`fragment_retries` (réessais
internes), `socket_timeout=20`, `continuedl=True`, logger redirigé vers nos logs, aucun
cookie, aucune authentification.

**Cache :**
```
<cache_dir>/                    défaut : %LOCALAPPDATA%\ytb-edit\cache
└── <video_id>/
    ├── video.<format_id>.webm
    ├── audio.<format_id>.webm
    └── source.json              écrit uniquement après validation
```
- Réutilisé entre sessions : un `source.json` valide ⇒ pas de retéléchargement.
- **Politique de nettoyage (proposée) :**
  1. le source est conservé tant que l'application est ouverte ;
  2. action « Terminer cette vidéo » (ou suppression de la tâche) → suppression immédiate ;
  3. fermeture de l'application → suppression des sources des tâches terminées
     (désactivable : « conserver le cache ») ;
  4. plafond de taille (ex. 20 Go) → éviction des sources les plus anciennes des tâches
     terminées ;
  5. au démarrage → purge des restes incomplets (`.part`, dossiers sans `source.json`).
- Échec de suppression (fichier verrouillé par un antivirus/lecteur) → avertissement
  dans les logs, nouvelle tentative au démarrage suivant ; **jamais** une erreur de tâche.

---

## 10. Stratégie FFmpeg

**Détection au démarrage** (ordre) : chemin des paramètres → `<app>/bin/` (packaging futur)
→ `PATH`. `ffmpeg -version` et `ffprobe -version` exécutés ; si absent : bandeau dans la
fenêtre avec la commande d'installation (`winget install Gyan.FFmpeg`), traitement
désactivé, reste de l'UI utilisable. Même principe pour Deno.

**Découpe sans réencodage — alignement explicite sur l'image clé :**
1. `ffprobe` lit les paquets vidéo autour du début (`-read_intervals`, sans décodage) et
   trouve `K` = dernière image clé ≤ début demandé.
2. Découpe avec recherche en entrée (`-ss` avant `-i`) à `K` pour **chaque** entrée :

```
Vidéo + audio :
ffmpeg -hide_banner -nostdin -n
       -ss K -i video.webm  -ss K -i audio.webm  -t (fin − K)
       -map 0:v:0 -map 1:a:0 -c copy
       -avoid_negative_ts make_zero -movflags +faststart  clip.part.mp4
Vidéo seule : idem avec une seule entrée, -map 0:v:0 -an
Audio seul  : -ss début -i audio.* -t (fin − début) -map 0:a:0 -c copy  → .opus / .m4a
```

Pourquoi chercher `K` soi-même plutôt que laisser FFmpeg arrondir : en copie, FFmpeg
conserve la portion avant le point demandé avec des horodatages négatifs/listes
d'édition, ce qui donne selon les lecteurs une image figée au début ou une
désynchronisation. En démarrant exactement sur `K`, vidéo et audio démarrent au même
instant, le clip est « propre » partout, et l'UI peut afficher le début réel.

- `-n` : FFmpeg ne peut jamais écraser un fichier.
- Écriture dans `*.part.*` puis renommage → jamais de clip à moitié écrit sous un nom final.
- Progression par `-progress pipe:1` (utile pour les longs segments).
- Commande complète journalisée ; en cas d'échec, les 30 dernières lignes de stderr sont
  journalisées et un message clair est affiché.
- Sous Windows : `CREATE_NO_WINDOW` (pas de fenêtre console qui clignote).

---

## 11. Gestion des fichiers et nommage

**Dossier de sortie** : `<dossier choisi>\<Titre nettoyé>\`
Nettoyage Windows : normalisation Unicode NFC ; remplacement de `< > : " / \ | ? *` et des
caractères de contrôle ; suppression des points/espaces finaux ; noms réservés
(`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) suffixés ; espaces multiples réduits ;
longueur limitée (~80 caractères, et chemin total < 250 pour respecter `MAX_PATH`) ;
titre vide → ID de la vidéo.

**Nom des clips** (convention demandée, conservée) :
```
clip_001_03m20s-03m50s.mp4
clip_004_1h02m03s-1h03m00s.mp4       (heures seulement si nécessaire)
clip_001_03m20s-03m50s_1.mp4          (collision)
```
- Le numéro est celui du segment dans la tâche, **stable** (pas de renumérotation si on
  supprime un segment en attente).
- Les horodatages du nom sont ceux **demandés** (modèle mental de l'utilisateur), même si
  le début réel est aligné sur une image clé.
- Nom unique déterminé au moment de la découpe (`_1`, `_2`, …) ; un seul worker de
  découpe ⇒ pas de course entre deux écritures.

---

## 12. Stratégie de progression

- Hooks yt-dlp → `DownloadProgress` **limité à ~5 événements/s par tâche** (sinon l'UI est
  inondée). Pourcentage calculé en octets sur l'ensemble des pistes (vidéo + audio),
  avec vitesse et temps restant.
- Changement d'état tâche/segment → `TaskChanged` / `SegmentChanged`.
- Pont UI : l'`Engine` appelle `emit(event)` depuis un thread de travail ;
  `EngineBridge.event.emit(...)` (Signal Qt) est automatiquement remis au thread UI.
  **Aucun appel bloquant dans le thread UI.**
- Affichage :
  - file (arbre) : icône d'état par vidéo et par segment (○ ⏳ ✓ ✗ ⊘), barre de
    téléchargement dans la ligne de la vidéo, « 3/5 segments » ;
  - barre globale en bas : *Vidéos 2/5 · Segments 7/17 · 1 erreur* + barre basée sur les
    segments terminés (une vraie mesure plutôt qu'une moyenne pondérée arbitraire) ;
  - activité courante : « Téléchargement : Vidéo B — 78 % — 4,2 Mo/s » et
    « Découpe : Vidéo A — segment 3 (03:20 → 03:50) ».
- Résumé final (panneau non bloquant) lorsque la file devient inactive.

---

## 13. Stratégie de gestion des erreurs

| Cas | Détection | Conséquence |
|-----|-----------|-------------|
| URL invalide | Validation syntaxique avant toute requête | Refus immédiat, message sous le champ |
| Vidéo indisponible / supprimée / privée | Exceptions yt-dlp analysées | Tâche `FAILED` |
| Live, à venir, restriction d'âge, membres, DRM | Métadonnées | `FAILED` « non supporté » (aucun contournement) |
| Pas d'audio alors que demandé | Formats disponibles | Erreur à la saisie du mode |
| Erreur réseau / interruption | Réessais yt-dlp puis exception | `FAILED` + bouton **Réessayer** (reprise du `.part`) |
| Espace disque insuffisant | Vérification préalable + `OSError(ENOSPC)` | `FAILED`, message avec l'espace nécessaire |
| Fichier source corrompu | ffprobe après téléchargement | 1 retéléchargement automatique puis `FAILED` |
| FFmpeg absent | Démarrage | Bandeau, traitement désactivé |
| Erreur FFmpeg | Code retour ≠ 0 | Segment `FAILED`, stderr dans les logs |
| Timestamp invalide / négatif / début ≥ fin / hors durée | UI (bloquant) + cœur | Impossible d'ajouter le segment |
| Nom Windows invalide | Nettoyage systématique | Transparent |
| Fichier existant | Nom unique + `-n` | Transparent |
| Fermeture de l'application | `closeEvent` | Annulation propre (§14) |
| Échec de suppression temporaire | `OSError` | Avertissement log, nouvelle tentative au démarrage |
| Bug inattendu | `except Exception` au niveau du worker | `FAILED` « erreur interne (voir logs) », la file continue |

Séparation des messages : `AppError.user_message` (français, court, affiché) vs détails
techniques et trace (fichier de log uniquement). Menu « Ouvrir le dossier des logs ».

---

## 14. Annulation et arrêt

- Un `CancelToken` (`threading.Event`) par tâche et par segment + un jeton global d'arrêt.
- yt-dlp : le hook de progression vérifie le jeton et lève `DownloadCancelled`
  (mécanisme prévu par yt-dlp). Délai maximal ≈ `socket_timeout` si le réseau est bloqué.
- FFmpeg : `services/process.py` surveille le jeton (~100 ms) et termine le processus.
- Filet de sécurité Windows : les sous-processus sont rattachés à un **Job Object**
  (`KILL_ON_JOB_CLOSE`, via `ctypes`) → même en cas de crash de Python, aucun FFmpeg
  orphelin.
- Fermeture : si un travail est en cours → confirmation → `engine.shutdown(timeout=5 s)` :
  jeton global, arrêt des processus, `join` des threads, suppression des `.part`,
  nettoyage du cache selon la politique.
- **Pas de persistance de la file entre deux lancements en V1** (les sources en cache
  restent réutilisables si on recolle l'URL). Sauvegarde de la file en JSON : V2.

---

## 15. Interface (esquisse)

```
┌─ ytb-edit ─────────────────────────────────────────────────────────────────┐
│ Sortie : [C:\Users\Moi\Videos\Clips              ] [Parcourir…]  [⚙]       │
│ URL    : [https://youtu.be/…                     ] [Ajouter]              │
├──────────────── File ───────────────┬──────── Vidéo sélectionnée ──────────┤
│ ✓ Vidéo A          4/4              │ Titre : Vidéo B   Durée : 45:12      │
│ ⏳ Vidéo B  ████░ 78 %  0/2          │ Mode : (•) Vidéo+audio ( ) Vidéo     │
│    ○ 01:10 → 01:45                  │        ( ) Audio                     │
│    ○ 08:20 → 09:00                  │ Segments :  #1 01:10 → 01:45  [✕]    │
│ ○ Vidéo C          0/1              │             #2 08:20 → 09:00  [✕]    │
│                                     │ ──────────────────────────────────── │
│                                     │ Début [08:20] [-10][-1][+1][+10]     │
│                                     │ Fin   [09:00] [-10][-1][+1][+10]     │
│                                     │ |────[■════■]──────────────────────| │
│                                     │ Durée : 40 s     [Ajouter le segment]│
├─────────────────────────────────────┴──────────────────────────────────────┤
│ [▶ Démarrer / ⏸ Pause]  Vidéos 1/3 · Segments 4/7 · 0 erreur  ██████░░ 57 % │
│ Découpe : Vidéo A — segment 4 (12:45 → 13:30)                    [Erreurs] │
└────────────────────────────────────────────────────────────────────────────┘
```

Saisie des temps :
- champ texte tolérant : `3:20`, `03:20`, `1:02:03`, et saisie rapide « à la
  micro-ondes » en chiffres seuls (`320` → 3:20, `10203` → 1:02:03) ;
- boutons **−10 s / −1 s / +1 s / +10 s** (±1 s pour l'ajustement fin, ±10 s pour le
  grossier ; ±20 s = deux clics) ;
- clavier : ↑/↓ = ±1 s, Maj+↑/↓ = ±10 s, Ctrl+↑/↓ = ±60 s ; molette sur le champ ;
- slider à deux poignées synchronisé avec les champs ;
- nouveau segment pré-rempli : début = fin du segment précédent, fin = début + 30 s.

---

## 16. Dépendances

**Python (runtime)** — 4 dépendances :
| Paquet | Rôle |
|--------|------|
| `PySide6-Essentials` | GUI (Qt Widgets sans les modules lourds) |
| `yt-dlp[default]` | Métadonnées + téléchargement (inclut le composant JS « EJS ») |
| `superqt` | Slider à deux poignées |
| `platformdirs` | Chemins `%APPDATA%` / `%LOCALAPPDATA%` |

**Dev** : `pytest`, `pytest-qt`, `ruff` (+ `mypy` optionnel).

**Outils externes (Windows)** :
```
winget install Gyan.FFmpeg        # ffmpeg + ffprobe
winget install DenoLand.Deno      # runtime JS requis par yt-dlp pour YouTube
```
yt-dlp doit être mis à jour régulièrement (`pip install -U "yt-dlp[default]"`) car
YouTube évolue souvent ; sa version est affichée dans les logs et la fenêtre « À propos ».

---

## 17. Stratégie de tests

| Niveau | Contenu | Dépendances |
|--------|---------|-------------|
| **Unitaires** (`tests/unit`) | parsing/formatage des temps ; validation des segments ; validation/canonicalisation des URLs ; nettoyage des noms Windows ; génération des noms de clips ; chemin unique ; table de transitions ; fonctions d'ordonnancement ; traduction des erreurs yt-dlp → `AppError` | Aucune (ni réseau, ni FFmpeg, ni Qt) |
| **Moteur** (`tests/unit/test_engine.py`) | file complète avec **faux** services : ajout pendant traitement, échec d'une tâche sans impact sur les autres, annulation, réouverture d'une tâche terminée, retéléchargement après éviction | Aucune |
| **Intégration FFmpeg** (`tests/integration`) | vidéo de test **générée localement** par FFmpeg (`lavfi testsrc` + `sine`, images clés toutes les 2 s) : recherche d'image clé, découpe des 3 modes, synchro, fichier source corrompu, `-n` | FFmpeg (test ignoré s'il est absent) |
| **Erreurs** | FFmpeg absent (chemin invalide), source absent, disque plein (simulé : `shutil.disk_usage` patché, `OSError(ENOSPC)` injectée), téléchargement échoué (faux downloader) | Aucune |
| **Réseau** (`tests/network`, `-m network`) | métadonnées + téléchargement d'une vidéo publique courte et stable (« Me at the zoo », 19 s, celle qu'utilise la suite de tests de yt-dlp) | Internet + Deno, **désactivés par défaut** |
| **UI** (quelques tests pytest-qt) | saisie de temps, boutons ±, synchronisation slider ↔ champs | Qt |

---

## 18. Évolutivité (hors V1, mais non bloquée)

| Évolution | Point d'extension |
|-----------|-------------------|
| Playlists / chaînes | `services/youtube` renvoie plusieurs `VideoInfo` → plusieurs tâches |
| Téléchargement partiel | autre stratégie dans `services/youtube` (le cache reste l'interface) |
| Coupe précise (smart cut), réencodage, clips verticaux, texte | nouvelles fonctions de `services/ffmpeg` + profil d'export sur le segment |
| Mode par segment | déjà présent dans le modèle |
| Fusion de clips | nouveau type d'opération dans l'`Engine` (un 4ᵉ worker ou une file d'opérations) |
| Persistance de la file | sérialisation JSON des `VideoTask` |
| Packaging `.exe` | PyInstaller/Nuitka ; `bin/` déjà prévu pour FFmpeg/Deno embarqués |

---

## 19. Conformité

L'application ne traite que des vidéos **publiques** accessibles sans authentification.
Aucun cookie, aucun identifiant, aucun contournement de DRM, de restriction d'âge, de
contenu réservé aux membres ou de toute autre protection : ces vidéos sont refusées avec
un message explicite. Le README rappellera que l'utilisateur doit respecter le droit
d'auteur, les licences applicables et les conditions d'utilisation de YouTube.

---

## 20. Décisions validées

1. ✅ **Précision** : début aligné sur l'image clé précédente, fin précise.
2. ✅ **Codecs** : meilleure qualité absolue (AV1/VP9 + Opus possibles dans le MP4).
3. ⏳ **Audio seul** : question MP3 en cours (MP3 impose un réencodage de l'audio).
4. ✅ **Parcours** : la vidéo entre dans la file dès que l'URL est collée ; téléchargement
   quand la file est démarrée et qu'au moins un segment existe.
5. ✅ **Cache** : conservé pendant la session, supprimé par « Terminer la vidéo » ou à la
   fermeture, plafond de taille, réutilisation entre sessions.
6. ✅ **Pause** : pause de la file + annulation ; pas de pause individuelle en V1.
7. ✅ **Persistance de la file** entre deux lancements : hors V1.
8. ✅ **Boutons d'incrément** : −10 / −1 / +1 / +10 s + clavier + saisie rapide.
9. ⏳ **Dépendance Deno** : à confirmer (nécessaire à partir de l'étape 4).
