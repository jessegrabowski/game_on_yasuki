from pathlib import Path

from yasuki_gui.config import load_hotkeys, Hotkeys


def test_load_hotkeys_defaults_when_missing(tmp_path: Path):
    # No config.yaml present
    hk = load_hotkeys(tmp_path / "config.yaml")
    assert hk == Hotkeys()


def test_load_hotkeys_overrides(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
        gui:
          hotkeys:
            bow: x
            flip: y
            dishonor: z
        """
    )
    hk = load_hotkeys(cfg)
    assert hk == Hotkeys(bow="x", flip="y", dishonor="z")


def test_load_hotkeys_reads_the_former_invert_key(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
        gui:
          hotkeys:
            invert: z
        """
    )
    assert load_hotkeys(cfg).dishonor == "z"
