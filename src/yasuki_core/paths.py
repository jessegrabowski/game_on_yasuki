import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

BUNDLED_IMAGES_DIR = _PACKAGE_DIR / "assets" / "images"
DEFAULTS_DIR = BUNDLED_IMAGES_DIR / "defaults"

FATE_BACK: Path = BUNDLED_IMAGES_DIR / "fate_back_new.jpg"
DYNASTY_BACK: Path = BUNDLED_IMAGES_DIR / "dynasty_back_new.jpg"

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


DEFAULT_STRATEGY: Path = DEFAULTS_DIR / "generic_strategy.jpg"
DEFAULT_RING: Path = DEFAULTS_DIR / "generic_ring.jpg"
DEFAULT_SENSEI: Path = DEFAULTS_DIR / "generic_sensei.jpg"
DEFAULT_WIND: Path = DEFAULTS_DIR / "generic_wind.jpg"
DEFAULT_STRONGHOLD: Path = DEFAULTS_DIR / "generic_stronghold.jpg"

DEFAULT_ITEM: Path = DEFAULTS_DIR / "generic_item.jpg"
DEFAULT_FOLLOWER: Path = DEFAULTS_DIR / "generic_follower.jpg"
DEFAULT_SPELL: Path = DEFAULTS_DIR / "generic_spell.jpg"

DEFAULT_PERSONALITY: Path = DEFAULTS_DIR / "generic_personality.jpg"
DEFAULT_HOLDING: Path = DEFAULTS_DIR / "generic_holding.jpg"
DEFAULT_EVENT: Path = DEFAULTS_DIR / "generic_event.jpg"
DEFAULT_REGION: Path = DEFAULTS_DIR / "generic_region.jpg"
DEFAULT_CELESTIAL: Path = DEFAULTS_DIR / "generic_celestial.jpg"
