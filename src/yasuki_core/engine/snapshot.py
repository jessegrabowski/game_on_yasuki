from dataclasses import dataclass, field, replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.table import TableState, SeatInfo, ZoneKey, DeckKey, BoardPos
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.serialization import (
    encode_card,
    decode_card,
    encode_zone_key,
    decode_zone_key,
    encode_deck_key,
    decode_deck_key,
    encode_seat,
    decode_seat,
    encode_attach_target,
    decode_attach_target,
)

# The start-of-game table snapshot: a deep-copied capture of a dealt table, the rebuild that turns
# it back into a live TableState, and its JSON codec. Product-neutral foundation — the manual sim's
# action log and the rules engine's game log both seed a replay from it.


@dataclass(slots=True)
class InitialRecord:
    """A complete table snapshot that seeds a replay.

    Captures the full state at the log head — seats, every owned zone and deck with its ordered
    contents, and the battlefield with positions — so a replay rebuilds the table exactly and then
    folds the recorded tape onto it.

    Attributes
    ----------
    seats : dict mapping PlayerId to SeatInfo
        Each seat's status (name, honor, ready, connected).
    decklists : dict mapping DeckKey to list of L5RCard
        The ordered contents of each fate and dynasty deck.
    zones : dict mapping ZoneKey to list of L5RCard
        The contents of every owned zone, including provinces.
    battlefield : list of L5RCard
        The shared battlefield's cards.
    positions : dict mapping str to BoardPos
        Battlefield card positions, keyed by card id.
    attachments : dict mapping str to (str or ZoneKey)
        The attachment graph, keyed by attached card id, mapping to a parent card id or province.
    creatable_tokens : dict mapping str to L5RCard
        Token templates the loaded decks can create, keyed by token card id, so a replayed token
        spawn resolves against the same templates without a database call.
    setup_seeds : dict mapping str to int
        Named RNG seeds used during setup that no logged entry carries.
    """

    seats: dict[PlayerId, SeatInfo]
    decklists: dict[DeckKey, list[L5RCard]]
    zones: dict[ZoneKey, list[L5RCard]] = field(default_factory=dict)
    battlefield: list[L5RCard] = field(default_factory=list)
    positions: dict[str, BoardPos] = field(default_factory=dict)
    attachments: dict[str, str | ZoneKey] = field(default_factory=dict)
    creatable_tokens: dict[str, L5RCard] = field(default_factory=dict)
    setup_seeds: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_state(
        cls, state: TableState, setup_seeds: dict[str, int] | None = None
    ) -> "InitialRecord":
        """Snapshot ``state`` into an initial record, deep-copying every card so later in-place
        mutation of the live table never touches the snapshot.

        Parameters
        ----------
        state : TableState
            The table to capture.
        setup_seeds : dict mapping str to int, optional
            Named setup seeds to record. Default empty.
        """
        return cls(
            seats={pid: replace(info) for pid, info in state.seats.items()},
            decklists={
                key: [replace(card) for card in deck.cards] for key, deck in state.decks.items()
            },
            zones={
                key: [replace(card) for card in zone.cards] for key, zone in state.zones.items()
            },
            battlefield=[replace(card) for card in state.battlefield.cards],
            positions=dict(state.positions),
            attachments=dict(state.attachments),
            creatable_tokens={tid: replace(card) for tid, card in state.creatable_tokens.items()},
            setup_seeds=dict(setup_seeds or {}),
        )


def build_initial_state(initial: InitialRecord) -> TableState:
    """Rebuild a full ``TableState`` from an initial record: the recorded seats, decks, zones,
    battlefield, and positions, with every card deep-copied so the record stays pristine and
    repeated builds are independent."""
    state = TableState.empty_two_seat()
    for pid, info in initial.seats.items():
        state.seats[pid] = replace(info)
    for key, cards in initial.decklists.items():
        state.decks[key].cards = _restore_cards(state, cards)
    for key, cards in initial.zones.items():
        zone = state.zones.get(key)
        if zone is None:
            zone = ProvinceZone(owner=key.owner)  # provinces are the only on-demand zone
            state.zones[key] = zone
        zone.cards = _restore_cards(state, cards)
    state.battlefield.cards = _restore_cards(state, initial.battlefield)
    state.positions = dict(initial.positions)
    state.attachments = dict(initial.attachments)
    state.creatable_tokens = {tid: replace(card) for tid, card in initial.creatable_tokens.items()}
    return state


def _restore_cards(state: TableState, cards: list[L5RCard]) -> list[L5RCard]:
    copied = [replace(card) for card in cards]
    for card in copied:
        state.cards_by_id[card.id] = card
    return copied


def encode_initial(initial: InitialRecord) -> dict:
    """Encode an ``InitialRecord`` to JSON-ready plain data."""
    return {
        "seats": [
            {"seat": pid.name, "info": encode_seat(info)} for pid, info in initial.seats.items()
        ],
        "decklists": [
            {"deck": encode_deck_key(key), "cards": [encode_card(card) for card in cards]}
            for key, cards in initial.decklists.items()
        ],
        "zones": [
            {"zone": encode_zone_key(key), "cards": [encode_card(card) for card in cards]}
            for key, cards in initial.zones.items()
        ],
        "battlefield": [encode_card(card) for card in initial.battlefield],
        "positions": {card_id: [pos.x, pos.y] for card_id, pos in initial.positions.items()},
        "attachments": {
            card_id: encode_attach_target(target) for card_id, target in initial.attachments.items()
        },
        "creatable_tokens": {
            tid: encode_card(card) for tid, card in initial.creatable_tokens.items()
        },
        "setup_seeds": dict(initial.setup_seeds),
    }


def decode_initial(payload: dict) -> InitialRecord:
    """Rebuild the ``InitialRecord`` encoded by ``encode_initial``."""
    seats = {PlayerId[item["seat"]]: decode_seat(item["info"]) for item in payload["seats"]}
    decklists = {
        decode_deck_key(item["deck"]): [decode_card(card) for card in item["cards"]]
        for item in payload["decklists"]
    }
    zones = {
        decode_zone_key(item["zone"]): [decode_card(card) for card in item["cards"]]
        for item in payload["zones"]
    }
    battlefield = [decode_card(card) for card in payload["battlefield"]]
    positions = {card_id: BoardPos(*xy) for card_id, xy in payload["positions"].items()}
    attachments = {
        card_id: decode_attach_target(target)
        for card_id, target in payload.get("attachments", {}).items()
    }
    creatable_tokens = {
        tid: decode_card(card) for tid, card in payload.get("creatable_tokens", {}).items()
    }
    return InitialRecord(
        seats=seats,
        decklists=decklists,
        zones=zones,
        battlefield=battlefield,
        positions=positions,
        attachments=attachments,
        creatable_tokens=creatable_tokens,
        setup_seeds=dict(payload["setup_seeds"]),
    )
