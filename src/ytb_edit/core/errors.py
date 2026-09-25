"""Hiérarchie des erreurs de l'application.

Chaque erreur porte deux niveaux d'information :
- ``user_message`` : court, en français, affichable tel quel dans l'interface ;
- ``details`` : informations techniques, destinées uniquement aux logs.

Les autres sous-classes (réseau, FFmpeg, disque…) seront ajoutées avec les
étapes qui les produisent.
"""


class AppError(Exception):
    """Erreur attendue, présentable à l'utilisateur."""

    def __init__(self, user_message: str, details: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.details = details


class InvalidTimecodeError(AppError):
    """Texte qui ne peut pas être interprété comme un temps."""


class InvalidSegmentError(AppError):
    """Segment incohérent (bornes, durée de la vidéo)."""


class InvalidStateTransitionError(AppError):
    """Changement d'état interdit : révèle un bug dans le moteur."""


class InvalidUrlError(AppError):
    """Texte qui n'est pas une URL de vidéo YouTube reconnue."""


class VideoUnavailableError(AppError):
    """Vidéo privée, supprimée ou inexistante."""


class UnsupportedVideoError(AppError):
    """Vidéo existante mais volontairement non prise en charge (live, restriction d'âge,
    contenu réservé aux membres, DRM…). Aucun contournement n'est tenté."""


class NetworkError(AppError):
    """Problème de connexion : réessayer plus tard peut suffire."""


class YouTubeError(AppError):
    """Autre échec côté YouTube / yt-dlp."""


class MissingStreamError(AppError):
    """La vidéo ne possède pas la piste nécessaire au mode demandé (ex. pas d'audio)."""


class SourceCorruptedError(AppError):
    """Fichier source téléchargé absent, incomplet ou illisible."""


class FFmpegError(AppError):
    """Échec d'une commande FFmpeg / ffprobe."""


class ToolMissingError(AppError):
    """Outil externe introuvable (FFmpeg, ffprobe)."""


class DiskSpaceError(AppError):
    """Espace disque insuffisant."""


class OperationCancelled(AppError):
    """Opération annulée par l'utilisateur ou par l'arrêt de l'application."""

    def __init__(self, details: str | None = None) -> None:
        super().__init__("Annulé.", details)
