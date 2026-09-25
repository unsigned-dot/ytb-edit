"""Règles sur les segments : validation, ajustements et suggestion de bornes.

Fonctions pures, utilisées à la fois par l'interface (retour immédiat) et par
le moteur (dernier rempart avant la découpe).
"""

from ytb_edit.core.errors import InvalidSegmentError
from ytb_edit.core.timecode import format_time

MIN_SEGMENT_S = 1
DEFAULT_SEGMENT_S = 30


def validate_segment(start_s: int, end_s: int, duration_s: int | None) -> None:
    """Lève ``InvalidSegmentError`` si le segment est incohérent.

    ``duration_s`` peut être ``None`` si la durée de la vidéo est inconnue :
    seule la borne supérieure n'est alors pas vérifiée.
    """
    if start_s < 0 or end_s < 0:
        raise InvalidSegmentError("Un temps ne peut pas être négatif.")
    if end_s <= start_s:
        raise InvalidSegmentError("La fin doit être après le début.")
    if end_s - start_s < MIN_SEGMENT_S:
        raise InvalidSegmentError(f"Un segment doit durer au moins {MIN_SEGMENT_S} s.")
    if duration_s is not None and end_s > duration_s:
        raise InvalidSegmentError(
            f"La fin ({format_time(end_s)}) dépasse la durée de la vidéo "
            f"({format_time(duration_s)})."
        )


def shift_time(value_s: int, delta_s: int, duration_s: int | None) -> int:
    """Applique un décalage (boutons ±) en restant dans [0, durée]."""
    shifted = max(0, value_s + delta_s)
    return shifted if duration_s is None else min(shifted, duration_s)


def suggest_next_segment(
    previous_end_s: int | None, duration_s: int, length_s: int = DEFAULT_SEGMENT_S
) -> tuple[int, int]:
    """Bornes pré-remplies d'un nouveau segment : il suit le précédent.

    Si le précédent se termine trop près de la fin, le segment est recalé sur
    la fin de la vidéo.
    """
    start = previous_end_s or 0
    if start > duration_s - MIN_SEGMENT_S:
        start = max(0, duration_s - length_s)
    return start, min(start + length_s, duration_s)
