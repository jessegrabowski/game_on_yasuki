import datetime
import json
import zlib
from dataclasses import astuple, dataclass

from yasuki_core.paths import ART_LAYOUT_PATH

with open(ART_LAYOUT_PATH, encoding="utf-8") as _f:
    _LAYOUT = json.load(_f)

# Art rectangles (left, top, right, bottom) per (era, layout type). A rect is the donor's cut region
# when its card is the donor and the recipient's land window when it's the recipient. This and the
# era/layout maps below are the single source of truth shared by the GUI, the web backend, and the
# browser canvas (served verbatim via the art-layout API), so the two renderers cannot drift.
ART_RECTS = {tuple(key.split("|")): tuple(rect) for key, rect in _LAYOUT["rects"].items()}
LAYOUT_TYPE = _LAYOUT["layout_type"]
# (exclusive upper-bound date, era). Boundaries are full dates, not years, because the full-bleed
# frame redesign landed mid-2008 (The Heaven's Will), splitting a calendar year.
ERA_BANDS = [
    (datetime.date.fromisoformat(band["max_date"]), band["era"]) for band in _LAYOUT["era_bands"]
]
DEFAULT_ERA = _LAYOUT["default_era"]
DEFAULT_LAYOUT = _LAYOUT["default_layout"]

_set_eras: dict[str, str] | None = None


def load_art_layout() -> dict:
    """The raw art-layout data (rects, era bands, layout map) for serving to the browser canvas."""
    return _LAYOUT


def era_for_date(release_date: datetime.date | None) -> str:
    """Map a set's release date to its art-layout era band; the modern band for an unknown date."""
    if release_date is None:
        return DEFAULT_ERA
    for max_date, era in ERA_BANDS:
        if release_date < max_date:
            return era
    return DEFAULT_ERA


def era_for_set(set_name: str) -> str:
    """Art-layout era for a set, by name. Set eras are computed once and cached.

    A set with no release date falls back to the earliest dated set in its arc, so metadata gaps
    (e.g. Samurai Edition Banzai, Chaos Reigns Part III) still bucket correctly."""
    global _set_eras
    if _set_eras is None:
        import yasuki_core.database as db

        with db.get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT set_name, release_date, arc FROM l5r_sets")
            rows = cur.fetchall()
        arc_floor: dict[str, datetime.date] = {}
        for row in rows:
            if row["release_date"] is not None:
                arc = row["arc"]
                if arc not in arc_floor or row["release_date"] < arc_floor[arc]:
                    arc_floor[arc] = row["release_date"]
        _set_eras = {
            row["set_name"]: era_for_date(row["release_date"] or arc_floor.get(row["arc"]))
            for row in rows
        }
    return _set_eras.get(set_name, DEFAULT_ERA)


def classify(card: dict, set_name: str) -> tuple[str, str]:
    """A card printing's (era, layout type) key into ART_RECTS."""
    types = card.get("types") or []
    ltype = next((LAYOUT_TYPE[t] for t in types if t in LAYOUT_TYPE), DEFAULT_LAYOUT)
    return (era_for_set(set_name), ltype)


def art_rect(key: tuple[str, str]) -> tuple[float, float, float, float]:
    """The art rect for an (era, layout type) key, falling back to the era's then the modern Strategy window."""
    era, _ = key
    return (
        ART_RECTS.get(key)
        or ART_RECTS.get((era, DEFAULT_LAYOUT))
        or ART_RECTS[(DEFAULT_ERA, DEFAULT_LAYOUT)]
    )


def cover_crop(
    box: tuple[int, int, int, int], target_w: int, target_h: int
) -> tuple[int, int, int, int]:
    """Shrink box to the target aspect ratio, centered, so a resize to target fills without distortion.

    Canonical geometry mirrored by the browser canvas; keep the two implementations in step."""
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    if w * target_h > h * target_w:
        new_w = round(h * target_w / target_h)
        left += (w - new_w) // 2
        right = left + new_w
    else:
        new_h = round(w * target_h / target_w)
        top += (h - new_h) // 2
        bottom = top + new_h
    return (left, top, right, bottom)


@dataclass(frozen=True)
class CustomPrint:
    """A reproducible art-swap recipe: the donor's art landed onto a specific recipient printing."""

    recipient_card_id: str
    recipient_print_id: int
    donor_card_id: str
    donor_print_id: int


def custom_print_id(recipe: CustomPrint) -> int:
    """A stable synthetic print id for a recipe, negative to never collide with DB serial ids.

    Deterministic across runs and processes (CRC32 of the recipe, not the salted built-in hash),
    so the same swap reloads to the same id and stacks instead of duplicating."""
    return -(zlib.crc32(repr(astuple(recipe)).encode()) + 1)
