import yaml
import pytest

from yasuki_core import DATABASE_DIR
from yasuki_core.card_identity import current_id, retired_ids
from yasuki_core.install.images_to_sql import CARD_BACKS

IMAGES_DIR = DATABASE_DIR / "images"
MANIFESTS = sorted(IMAGES_DIR.glob("*.yaml"))

# A renamed card's image files keep the name they were stored under, its retired id.
FORMER_IDS: dict[str, list[str]] = {}
for retired in retired_ids():
    FORMER_IDS.setdefault(current_id(retired), []).append(retired)


def test_manifests_exist():
    assert MANIFESTS, f"no image manifests in {IMAGES_DIR}"


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.stem)
def test_manifest_shape(manifest):
    """Every manifest matches the contract load_print_images reads: set + images[card_id,
    printing_id, files[role, file, sha256]], front-first, unique printings."""
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert isinstance(data["set"], str) and data["set"]

    seen = set()
    for image in data["images"]:
        key = (image["card_id"], image["printing_id"])
        assert key not in seen, f"duplicate printing {key} in {manifest.name}"
        seen.add(key)

        files = image["files"]
        assert files, f"empty files for {key}"
        assert files[0]["role"] == "front"
        for file_info in files:
            assert file_info["role"] in {"front", "back"}
            names = (image["card_id"], *FORMER_IDS.get(image["card_id"], ()))
            assert file_info["file"].startswith(names)
            assert len(file_info["sha256"]) == 64


def test_card_backs_constant_covers_decks_and_eras():
    assert {(deck, era) for deck, era, _ in CARD_BACKS} == {
        ("Fate", "old"),
        ("Fate", "new"),
        ("Dynasty", "old"),
        ("Dynasty", "new"),
        ("Dynasty", "token"),
    }
    for _deck, _era, path in CARD_BACKS:
        assert path.startswith("sets/backs/")
