import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

BUNDLED_IMAGES_DIR = _PACKAGE_DIR / "assets" / "images"
DEFAULTS_DIR = BUNDLED_IMAGES_DIR / "defaults"
OVERLAYS_DIR = BUNDLED_IMAGES_DIR / "overlays"
FONTS_DIR = _PACKAGE_DIR / "assets" / "fonts"

# Card-facing image paths are relative and resolved at render time by resolve_card_image_path. A
# card carries the path it was printed with, not a filesystem location: an absolute one would be
# baked into every snapshot and logged spawn, tying a saved game to the machine that wrote it.
FATE_BACK = Path("fate_back_new.jpg")
DYNASTY_BACK = Path("dynasty_back_new.jpg")

_DEFAULT_SETS_DIR = Path.cwd() / "sets"
SETS_DIR: Path = Path(os.environ.get("YASUKI_SETS_DIR", str(_DEFAULT_SETS_DIR)))

DATABASE_DIR = _PACKAGE_DIR / "assets" / "database"

ART_LAYOUT_PATH = _PACKAGE_DIR / "assets" / "art_layout.json"


def resolve_set_image_path(relative_path: str) -> Path | None:
    """
    Resolve a DB-stored image path to an absolute filesystem path.

    The database stores paths like ``"sets/celestial_edition/card.png"``.
    This strips the leading ``sets/`` prefix and resolves against SETS_DIR.

    Parameters
    ----------
    relative_path : str
        Relative path as stored in the database

    Returns
    -------
    resolved : Path or None
        Absolute path, or None if the input is empty
    """
    if not relative_path:
        return None
    stripped = relative_path.removeprefix("sets/")
    return SETS_DIR / stripped


DEFAULT_STRATEGY = Path("defaults/generic_strategy.jpg")
DEFAULT_RING = Path("defaults/generic_ring.jpg")
DEFAULT_SENSEI = Path("defaults/generic_sensei.jpg")
DEFAULT_WIND = Path("defaults/generic_wind.jpg")
DEFAULT_STRONGHOLD = Path("defaults/generic_stronghold.jpg")

DEFAULT_ITEM = Path("defaults/generic_item.jpg")
DEFAULT_FOLLOWER = Path("defaults/generic_follower.jpg")
DEFAULT_SPELL = Path("defaults/generic_spell.jpg")

DEFAULT_PERSONALITY = Path("defaults/generic_personality.jpg")
DEFAULT_HOLDING = Path("defaults/generic_holding.jpg")
DEFAULT_EVENT = Path("defaults/generic_event.jpg")
DEFAULT_REGION = Path("defaults/generic_region.jpg")
DEFAULT_CELESTIAL = Path("defaults/generic_celestial.jpg")

_GREAT_CLANS = frozenset(
    {
        "crab",
        "crane",
        "dragon",
        "lion",
        "mantis",
        "naga",
        "phoenix",
        "scorpion",
        "spider",
        "unicorn",
    }
)


def default_personality_image(clans: list[str] | None) -> Path:
    """The clan-specific placeholder frame for a Personality with no scanned print. Fall back to the
    unaligned frame (``generic_personality.jpg``) when no great-clan alignment is present."""
    for clan in clans or []:
        slug = clan.lower().replace(" clan", "").strip()
        if slug in _GREAT_CLANS:
            return Path(f"defaults/generic_personality_{slug}.jpg")
    return DEFAULT_PERSONALITY


def resolve_card_image_path(path: Path | str | None) -> Path | None:
    """Resolve an image path off a card to a filesystem path.

    A card's own art is set-relative (``"sets/.../card.jpg"``); its type's default art and deck back
    are relative to the bundled images. An absolute path is returned unchanged, so a caller holding
    one already resolved is safe.

    Parameters
    ----------
    path : Path or str, optional
        The path as the card carries it. Default None, which resolves to None.
    """
    if not path:
        return None
    if Path(path).is_absolute():
        return Path(path)
    text = str(path)
    if text.startswith("sets/"):
        return resolve_set_image_path(text)
    return BUNDLED_IMAGES_DIR / text
