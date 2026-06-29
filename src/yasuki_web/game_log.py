from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole, MoveDest, BATTLEFIELD
from yasuki_core.engine.intents import (
    Intent,
    Event,
    IntentOp,
    coin_flip_outcome,
    dice_roll_outcome,
)
from yasuki_core.engine.redaction import card_identity_public

_FLAG_VERB = {
    IntentOp.BOW: "bowed",
    IntentOp.UNBOW: "unbowed",
    IntentOp.FLIP: "flipped",
    IntentOp.FLIP_FACE: "turned over",
    IntentOp.INVERT: "inverted",
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
    """Reference a card by a clickable, named link when its identity is public to both seats, else by
    the unlinked words "a card" — so a shared log line never names a card the opponent cannot see."""
    if card_identity_public(state, card_id):
        return {"card_id": card_id, "name": state.cards_by_id[card_id].name}
    return {"text": "a card"}


def _card_segments(state: TableState, card_ids: tuple[str, ...]) -> list[dict]:
    segments: list[dict] = []
    for i, card_id in enumerate(card_ids):
        if i:
            segments.append({"text": ", "})
        segments.append(_card_segment(state, card_id))
    return segments


def _side_word(state: TableState, card_id: str) -> str:
    """The card's side as a lowercase word ("fate"/"dynasty") for a generic, non-leaking reference."""
    card = state.cards_by_id.get(card_id)
    return card.side.value.lower() if card is not None else "card"


def _deck_desc(deck: DeckKey) -> str:
    return f"their {deck.side.value.lower()} deck"


def _pile_desc(pile: DeckKey | ZoneKey) -> str:
    """An own-pile description for the reorder log, hiding the card and the new order. The reorder is
    owner-gated, so a deck reads "their fate deck" and a discard "their fate discard"."""
    if isinstance(pile, DeckKey):
        return _deck_desc(pile)
    return f"their {pile.role.value.split('_')[0]} discard"


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
    # Cosmetic-only ops (free repositioning, stacking-order raise) are not surfaced in the log.
    if op in (
        IntentOp.SET_CARD_POS,
        IntentOp.SET_CARD_POSITIONS,
        IntentOp.REORDER_HAND,
        IntentOp.RAISE,
        IntentOp.SET_NOTE,
    ):
        return []

    lead = {"text": f"{actor} "}

    if op in _FLAG_VERB:
        return [lead, {"text": f"{_FLAG_VERB[op]} "}, *_card_segments(state, event.cards)]

    match op:
        case IntentOp.MOVE_CARD | IntentOp.MOVE_DECK_TOP:
            card_id = event.cards[0] if event.cards else getattr(intent, "card_id", "")
            # A face-down play hides the card's identity from the opponent, so it reads generically.
            if intent.to == BATTLEFIELD and getattr(intent, "face_down", False):
                return [lead, {"text": f"plays a face-down {_side_word(state, card_id)} card"}]
            if isinstance(intent.to, DeckKey):
                where = "bottom" if getattr(intent, "to_bottom", False) else "top"
                return [
                    lead,
                    {"text": "put "},
                    _card_segment(state, card_id),
                    {"text": f" on the {where} of {_deck_desc(intent.to)}"},
                ]
            return [
                lead,
                {"text": "moved "},
                _card_segment(state, card_id),
                {"text": f" to {_dest_desc(intent.to)}"},
            ]
        case IntentOp.SHOW:
            # Named only when the card is public to ALL seats after the show (a fate card from hand);
            # a shown face-down card stays hidden from its owner, so it must read generically.
            if card_identity_public(state, intent.card_id):
                return [lead, {"text": "shows "}, _card_segment(state, intent.card_id)]
            return [lead, {"text": f"shows a {_side_word(state, intent.card_id)} card"}]
        case IntentOp.UNSHOW:
            return [lead, {"text": f"stops showing a {_side_word(state, intent.card_id)} card"}]
        case IntentOp.PEEK:
            return [lead, {"text": f"peeks at a {_side_word(state, intent.card_id)} card"}]
        case IntentOp.UNPEEK:
            return [lead, {"text": f"stops peeking at a {_side_word(state, intent.card_id)} card"}]
        case IntentOp.DRAW:
            return [lead, {"text": "drew a card"}]
        case IntentOp.SHUFFLE:
            return [lead, {"text": f"shuffled {_deck_desc(intent.deck)}"}]
        case IntentOp.REORDER_PILE:
            return [lead, {"text": f"reordered {_pile_desc(intent.pile)}"}]
        case IntentOp.FLIP_DECK_TOP:
            return [lead, {"text": f"flipped the top of {_deck_desc(intent.deck)}"}]
        case IntentOp.SEARCH_DECK:
            if intent.limit is not None and intent.limit > 0:
                return [
                    lead,
                    {"text": f"searched the top {intent.limit} cards of {_deck_desc(intent.deck)}"},
                ]
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
        case IntentOp.GIVE_CONTROL:
            return [lead, {"text": "gave control of "}, _card_segment(state, intent.card_id)]
        case IntentOp.SPAWN_CARD:
            if intent.token_id:
                verb = "created "
            elif intent.source_card_id:
                verb = "duplicated "
            else:
                verb = "spawned "
            return [lead, {"text": verb}, _card_segment(state, intent.card_id)]
        case IntentOp.REMOVE_CARD:
            return [lead, {"text": "removed a card"}]
        case IntentOp.FLIP_COIN:
            return [lead, {"text": f"flipped a coin: {coin_flip_outcome(intent.seed)}"}]
        case IntentOp.ROLL_DICE:
            face = dice_roll_outcome(intent.seed, intent.sides)
            return [lead, {"text": f"rolled a {face} on a d{intent.sides}"}]
        case _:
            return []
