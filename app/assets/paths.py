from pathlib import Path

# Base assets dirs
ASSETS_DIR = Path(__file__).resolve().parent / "images"
DEFAULTS_DIR = ASSETS_DIR / "cards" / "defaults"

# Card backs
FATE_BACK: Path = ASSETS_DIR / "fate_back_new.jpg"
DYNASTY_BACK: Path = ASSETS_DIR / "dynasty_back_new.jpg"

# Generic default fronts by type
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
