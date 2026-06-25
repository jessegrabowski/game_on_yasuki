from yasuki_core.engine.table import (
    TableState,
    Intent,
    Event,
    IntentOp,
    DeckKey,
    ZoneRole,
    MoveDest,
    BATTLEFIELD,
)

_FLAG_VERB = {
    IntentOp.BOW: "bowed",
    IntentOp.UNBOW: "unbowed",
    IntentOp.FLIP: "flipped",
    IntentOp.INVERT: "inverted",
    IntentOp.REVEAL: "revealed",
    IntentOp.HIDE: "hid",
}

_ZONE_DEST = {
    ZoneRole.HAND: "their hand",
    ZoneRole.FATE_DISCARD: "the fate discard",
    ZoneRole.FATE_BANISH: "the fate banish",
    ZoneRole.DYNASTY_DISCARD: "the dynasty discard",
    ZoneRole.DYNASTY_BANISH: "the dynasty banish",
    ZoneRole.PROVINCE: "a province",
}


def _card_segment(state: TableState, card_id: str) -> dict:
    """Reference a card by a clickable link when it is publicly visible on the battlefield, else by
    the unlinked words "a card" — so a card the opponent may not see is never named in a shared log
    line.
    """
    card = state.cards_by_id.get(card_id)
    if (
        card is not None
        and (card.face_up or card.revealed)
        and any(held is card for held in state.battlefield.cards)
    ):
        return {"card_id": card_id, "name": card.name}
    return {"text": "a card"}


def _card_segments(state: TableState, card_ids: tuple[str, ...]) -> list[dict]:
    segments: list[dict] = []
    for i, card_id in enumerate(card_ids):
        if i:
            segments.append({"text": ", "})
        segments.append(_card_segment(state, card_id))
    return segments


def _deck_desc(deck: DeckKey) -> str:
    return f"their {deck.side.value.lower()} deck"


def _dest_desc(to: MoveDest) -> str:
    if to == BATTLEFIELD:
        return "the battlefield"
    if isinstance(to, DeckKey):
        return _deck_desc(to)
    return _ZONE_DEST.get(to.role, "a zone")


def describe_intent(state: TableState, actor: str, intent: Intent, event: Event) -> list[dict]:
    """Build the shared game-log segments for one accepted intent, safe to show both seats.

    A card is named (and linked) only when it is publicly visible on the battlefield; everywhere else
    it reads as "a card". Pure card repositioning (``SET_CARD_POS``) is not shown — the result is an
    empty list, and the caller logs nothing.

    Parameters
    ----------
    state : TableState
        The table after the intent applied.
    actor : str
        Display name of the acting seat.
    intent : Intent
        The intent that was accepted.
    event : Event
        The event it produced, whose ``cards`` name the affected cards.
    """
    op = intent.op
    if op is IntentOp.SET_CARD_POS:
        return []

    lead = {"text": f"{actor} "}

    if op in _FLAG_VERB:
        return [lead, {"text": f"{_FLAG_VERB[op]} "}, *_card_segments(state, event.cards)]

    match op:
        case IntentOp.MOVE_CARD:
            card_id = event.cards[0] if event.cards else intent.card_id
            return [
                lead,
                {"text": "moved "},
                _card_segment(state, card_id),
                {"text": f" to {_dest_desc(intent.to)}"},
            ]
        case IntentOp.DRAW:
            return [lead, {"text": "drew a card"}]
        case IntentOp.SHUFFLE:
            return [lead, {"text": f"shuffled {_deck_desc(intent.deck)}"}]
        case IntentOp.SEARCH_DECK:
            return [lead, {"text": f"searched {_deck_desc(intent.deck)}"}]
        case IntentOp.FILL_PROVINCE:
            return [lead, {"text": "filled a province"}]
        case IntentOp.DESTROY_PROVINCE:
            return [lead, {"text": "destroyed a province"}]
        case IntentOp.DISCARD_PROVINCE:
            return [lead, {"text": "discarded a province card"}]
        case IntentOp.CREATE_PROVINCE:
            return [lead, {"text": "created a province"}]
        case IntentOp.SET_HONOR:
            if intent.value is not None:
                return [lead, {"text": f"set their honor to {intent.value}"}]
            verb = "gained" if intent.delta > 0 else "lost"
            return [lead, {"text": f"{verb} {abs(intent.delta)} honor"}]
        case IntentOp.SPAWN_CARD:
            return [lead, {"text": "spawned "}, _card_segment(state, intent.card_id)]
        case IntentOp.REMOVE_CARD:
            return [lead, {"text": "removed a card"}]
        case _:
            return []
