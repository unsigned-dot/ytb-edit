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
