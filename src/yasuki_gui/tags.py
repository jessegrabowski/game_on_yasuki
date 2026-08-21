from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole

# Canvas item tags are opaque strings derived deterministically from the domain keys, so hit-testing
# and drag code keep working with plain prefixes while the view maps each tag back to its key.

_ROLE_TAG = {
    ZoneRole.HAND: "hand",
    ZoneRole.FATE_DISCARD: "fate_discard",
    ZoneRole.FATE_BANISH: "fate_banish",
    ZoneRole.DYNASTY_DISCARD: "dynasty_discard",
    ZoneRole.DYNASTY_BANISH: "dynasty_banish",
    ZoneRole.PROVINCE: "province",
}


def card_tag(card_id: str) -> str:
    return f"card:{card_id}"


def card_id_for_tag(tag: str) -> str | None:
    return tag[len("card:") :] if tag.startswith("card:") else None


def deck_tag(key: DeckKey) -> str:
    return f"deck:{key.owner.name}:{key.side.name}"


def zone_tag(key: ZoneKey) -> str:
    base = f"zone:{key.owner.name}:{_ROLE_TAG[key.role]}"
    return f"{base}:{key.idx}" if key.idx is not None else base


def allocation_tag(card_id: str, step: int) -> str:
    """The tag of the arrow that moves one creation on or off ``card_id`` while it is dividing a
    number of them; ``step`` is +1 for the up arrow and -1 for the down."""
    return f"alloc:{'up' if step > 0 else 'down'}:{card_id}"


def allocation_step_for_tag(tag: str) -> tuple[str, int] | None:
    """The card and the step an allocation arrow tag names, or None for any other tag."""
    if not tag.startswith("alloc:"):
        return None
    _, direction, card_id = tag.split(":", 2)
    return card_id, 1 if direction == "up" else -1
