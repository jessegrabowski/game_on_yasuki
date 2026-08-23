import pathlib
from functools import cache

from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, SetEntry, iter_set_entries


@cache
def set_entries(cards_dir: pathlib.Path = DEFAULT_CARDS_PATH) -> tuple[SetEntry, ...]:
    """Every card entry in ``cards_dir``, parsed once per session and shared by every check that
    scans the whole corpus. Cached on the directory, so a test reading a fixture directory of its
    own gets its own parse.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    """
    return tuple(iter_set_entries(cards_dir))
