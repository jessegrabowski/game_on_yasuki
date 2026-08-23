from pathlib import Path
from typing import Any

import yaml

# The C scanner parses the card data about nine times faster than the Python one, and
# ``yaml.safe_load`` always picks the Python one. Pixi pins a PyYAML built against libyaml; a pip
# install off an sdist may not have it, and slower beats refusing to import.
try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:  # pragma: no cover - decided by how PyYAML was built, not by our code
    from yaml import SafeLoader


def load_yaml(text: str) -> Any:
    """Parse ``text`` as YAML under the safe schema, refusing arbitrary object construction."""
    return yaml.load(text, Loader=SafeLoader)


def read_yaml(path: Path) -> Any:
    """Parse the UTF-8 YAML file at ``path`` under the safe schema."""
    return load_yaml(path.read_text(encoding="utf-8"))
