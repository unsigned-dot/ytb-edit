"""Conversion entre texte saisi et secondes, et formats d'affichage.

Formats acceptés par ``parse_time`` (espaces ignorés) :
- avec deux-points : ``20``, ``3:20``, ``03:20``, ``1:02:03``, ``75:00`` ;
- chiffres seuls (saisie rapide « micro-ondes ») : ``45`` → 45 s, ``320`` → 3:20,
  ``10203`` → 1:02:03 (1 ou 2 chiffres = secondes) ;
- avec unités, comme dans les noms de fichiers : ``3m20s``, ``1h02m03s``, ``90s``.

Seule la première composante peut dépasser 59 (``75:00`` est valide, ``3:75`` non).
"""

import re

from ytb_edit.core.errors import InvalidTimecodeError

_DIGITS = re.compile(r"[0-9]+")
_COLON = re.compile(r"[0-9]+(?::[0-9]{1,2}){1,2}")
_UNITS = re.compile(r"(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?")


def parse_time(text: str) -> int:
    """Convertit un texte saisi en secondes. Lève ``InvalidTimecodeError``."""
    raw = "".join(text.split()).lower()
    if not raw:
        raise InvalidTimecodeError("Temps vide.")

    if _DIGITS.fullmatch(raw):
        components = _split_digits(raw)
        units = "hms"[-len(components) :]
    elif _COLON.fullmatch(raw):
        components = [int(part) for part in raw.split(":")]
        units = "hms"[-len(components) :]
    elif (match := _UNITS.fullmatch(raw)) and any(match.groups()):
        present = [(u, g) for u, g in zip("hms", match.groups(), strict=True) if g is not None]
        components = [int(g) for _, g in present]
        units = "".join(u for u, _ in present)
    else:
        raise InvalidTimecodeError(f"Temps invalide : « {text.strip()} » (exemple : 3:20).")

    return _combine(components, units, text)


def _split_digits(raw: str) -> list[int]:
    if len(raw) <= 2:
        return [int(raw)]
    seconds, rest = raw[-2:], raw[:-2]
    minutes, hours = rest[-2:], rest[:-2]
    return [int(p) for p in (hours, minutes, seconds) if p]


def _combine(components: list[int], units: str, original: str) -> int:
    if any(value > 59 for value in components[1:]):
        raise InvalidTimecodeError(
            f"Temps invalide : « {original.strip()} » (minutes et secondes doivent être < 60)."
        )
    factor = {"h": 3600, "m": 60, "s": 1}
    return sum(value * factor[unit] for value, unit in zip(components, units, strict=True))


def format_time(seconds: int) -> str:
    """Affichage : ``03:20`` sous une heure, ``1:02:03`` au-delà."""
    _check_non_negative(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_for_filename(seconds: int, *, with_hours: bool = False) -> str:
    """Nom de fichier : ``03m20s``, ou ``0h03m20s`` si ``with_hours``.

    ``with_hours`` est choisi une fois par vidéo (durée ≥ 1 h) pour que tous les
    clips d'un même dossier aient un nom de même forme et se trient correctement.
    """
    _check_non_negative(seconds)
    if with_hours:
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}m{secs:02d}s"


def _check_non_negative(seconds: int) -> None:
    if seconds < 0:
        raise ValueError(f"Temps négatif : {seconds}")
