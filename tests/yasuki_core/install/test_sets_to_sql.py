import re

from yasuki_core import DATABASE_DIR
from yasuki_core.yaml_io import read_yaml


def test_every_set_has_a_distinct_short_id_of_at_least_three_characters():
    sets = [
        entry for arc in read_yaml(DATABASE_DIR / "set_info.yaml")["arcs"] for entry in arc["sets"]
    ]
    short_ids = [entry.get("short_id") for entry in sets]

    assert all(re.fullmatch(r"[a-z0-9]{3,}", str(short_id)) for short_id in short_ids)
    assert len(set(short_ids)) == len(sets)
