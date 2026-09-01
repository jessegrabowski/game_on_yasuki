from collections.abc import Iterator
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard, redact, ViewSnapshot
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.economy import (
    active_modifiers,
    effective_province_strength,
    effective_stat,
)
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import BattleOutcome, GameState, Phase, RoundKind, Segment
from yasuki_core.engine.rules.decisions import DecisionRequest
from yasuki_core.engine.rules.legality import legacy_candidates
from yasuki_core.engine.rules.units import unit_force, units_at
from yasuki_core.engine.table import DeckKey, ZoneKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint


@dataclass(frozen=True, slots=True)
class UnitView:
    """A Personality and the cards attached to him — the CR's unit, as a seat sees it.

    Attributes
    ----------
    leader : L5RCard
        The Personality the unit is built around.
    attached : tuple of L5RCard
        His Followers, Items and Spells, in the order they were attached.
    """

    leader: L5RCard
    attached: tuple[L5RCard, ...]


@dataclass(frozen=True, slots=True)
class BattlefieldView:
    """One battlefield of a declared attack, and the two armies standing at it.

    Attributes
    ----------
    province : ZoneKey
        The Defender Province the battlefield sits at.
    occupant : L5RCard or HiddenCard or None
        The card standing in that Province, redacted like any other — a face-down Dynasty card is a
        back to the seat attacking it. None when the Province is empty.
    strength : int
        The Province's effective Strength, which the attacking Force must clear to destroy it.
    attacking : tuple of UnitView
        The Attacker's units here.
    defending : tuple of UnitView
        The Defender's units here.
    attacking_force : int
        The attacking army's Force as resolution would total it.
    defending_force : int
        The defending army's Force as resolution would total it.
    fought : bool
        Whether a battle has already been fought here.
    outcome : BattleOutcome or None
        What the battle fought here did, or None until one has been.
    destroyed_names : tuple of str
        The names of the cards that battle destroyed, in the order they went. Named apart from
        ``outcome.destroyed``, which carries the same cards as ids; public because a destroyed card
        is sitting in a discard both seats may read.
    """

    province: ZoneKey
    occupant: L5RCard | HiddenCard | None
    strength: int
    attacking: tuple[UnitView, ...]
    defending: tuple[UnitView, ...]
    attacking_force: int
    defending_force: int
    fought: bool
    outcome: BattleOutcome | None
    destroyed_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttackView:
    """The attack in progress, as a seat sees it.

    Attributes
    ----------
    attacker : PlayerId
        The seat that declared.
    defender : PlayerId
        The seat being attacked.
    segment : Segment
        Which segment of the Attack Phase is open.
    current : int or None
        The battlefield a battle is being fought at, or None between battles.
    battlefields : tuple of BattlefieldView
        One per Defender Province, in Province order.
    """

    attacker: PlayerId
    defender: PlayerId
    segment: Segment
    current: int | None
    battlefields: tuple[BattlefieldView, ...]


@dataclass(frozen=True, slots=True)
class GameView:
    """A per-seat projection of a :class:`GameState` — everything one seat is entitled to see.

    The table is redacted for the viewer (the opponent's hand, face-down cards, and deck contents
    appear as backs); the turn-level rules fields are public to both seats; and a pending decision
    reaches only the seat that must answer it.

    Attributes
    ----------
    viewer : PlayerId
        The seat this view is built for.
    table : ViewSnapshot
        The viewer's redacted view of the board.
    turn : int
        The current turn number.
    active : PlayerId
        The seat whose turn it is.
    phase : Phase
        The current phase.
    first_player : PlayerId
        The seat that took the first turn.
    gold : dict mapping PlayerId to int
        Every seat's gold pool — public to both seats.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None.
    pending : DecisionRequest or None
        The decision the viewer must answer, or None when nothing is awaited from this viewer —
        including when the engine is instead waiting on the other seat.
    legacy_pool : tuple of L5RCard
        The viewer's own Legacy cards a search would still find, sorted by card id rather than left
        in deck order. Empty means a Legacy search would whiff and lose the game. Never populated
        for the other seat.
    dynasty_deck : tuple of L5RCard
        The cards left in the viewer's own dynasty deck, sorted by card id rather than left in deck
        order. A seat built its deck and so knows what remains in it; where those cards sit in the
        shuffle is the part it must not learn, which is what the sort strips. Never populated for
        the other seat.
    responding_to : str or None
        The action an open Response Step answers, worded for a player, or None when no Step is open.
        A seat holding no Response still sees it: the Step is the whole table's, and a seat is
        passing on something it should be told the name of.
    attack : AttackView or None
        The attack in progress, or None outside one. Public to both seats: who is attacking
        whom, and which units stand where, is on the table for everyone to see. A Province's
        occupant is redacted like any other card.
    stats : dict mapping str to dict
        Each modified card's effective stats by id, the inner dict keyed by :class:`Stat`. Read it
        through :meth:`stat` rather than directly — a card no modifier reaches is absent, and the
        method supplies its printed value.
    unit_force : dict mapping str to int
        Each identifiable in-play Personality's unit Force by his card id, totalled the way a battle
        resolves it: a bowed Personality contributes nothing, a bowed Follower drops out, and an
        Item's modifier rides on the Personality either way. It says what a unit would contribute,
        not whether it may be sent — a bowed Personality cannot be assigned at all, and his entry
        still counts his unbowed Followers. A seat's army is the sum over the units it may assign.
    """

    viewer: PlayerId
    table: ViewSnapshot
    turn: int
    active: PlayerId
    phase: Phase
    first_player: PlayerId
    gold: dict[PlayerId, int]
    favor_holder: PlayerId | None
    pending: DecisionRequest | None
    responding_to: str | None
    legacy_pool: tuple[L5RCard, ...]
    dynasty_deck: tuple[L5RCard, ...]
    attack: AttackView | None
    stats: dict[str, dict[Stat, int]]
    unit_force: dict[str, int]

    def stat(self, card: L5RCard, stat: Stat) -> int:
        """``card``'s effective ``stat`` — counters, granted modifiers and all. Reading the card's
        own attribute instead yields the printed number, since modifiers live on the game.
        """
        modified = self.stats.get(card.id)
        if modified is not None:
            return modified[stat]
        printed = getattr(card, stat.value, None)
        return 0 if printed is None else printed  # absent, or printed as a dash


def _identifiable_ids(table: ViewSnapshot) -> set[str]:
    """The ids ``table`` lets its viewer identify. A card redacted to a :class:`HiddenCard`, and one
    the snapshot omits, are both absent — the snapshot has already decided entitlement, and reading
    it back is what keeps that decision in one place."""
    ids = {
        card.id for zone in table.zones.values() for card in zone.cards if isinstance(card, L5RCard)
    }
    ids.update(entry.card.id for entry in table.battlefield if isinstance(entry.card, L5RCard))
    ids.update(deck.top.id for deck in table.decks.values() if deck.top is not None)
    return ids


def _modified_cards(game: GameState, identifiable: set[str]) -> Iterator[L5RCard]:
    """Every identifiable card any active modifier reaches.

    Only some modifier sources are recorded on the game: a counter and a granted effect are, while
    an attachment's printed modifier, a Sensei's grant to its Stronghold and a Kensai's raised
    weapon limit are derived from the board as it stands. :func:`active_modifiers` is what knows
    about all of them, so it is what decides.

    A card no modifier reaches has only its printed stats, which :meth:`GameView.stat` reads
    straight off it. A card the viewer may not identify is skipped: its stats would say what it is,
    and a view carries only what its seat is entitled to.
    """
    for card in game.table.cards_by_id.values():
        if card.id in identifiable and _is_modified(game, card):
            yield card


def _is_modified(game: GameState, card: L5RCard) -> bool:
    """Whether any active modifier reaches ``card``, over any stat."""
    return any(next(active_modifiers(game, card, stat), None) is not None for stat in Stat)


def project(game: GameState, viewer: PlayerId) -> GameView:
    """Project ``game`` into the view ``viewer`` is entitled to: the board redacted for the viewer,
    the public rules fields, the pending decision only if this viewer is the one to answer it, the
    viewer's own Legacy pool and remaining dynasty deck, and the effective stats of every card
    carrying a modifier."""
    pending = game.pending if game.pending is not None and game.pending.seat is viewer else None
    table = redact(game.table, viewer)
    attack = _project_attack(game, table)
    return GameView(
        viewer=viewer,
        table=table,
        turn=game.turn,
        active=game.active,
        phase=game.phase,
        first_player=game.first_player,
        gold=dict(game.gold),
        favor_holder=game.favor_holder,
        pending=pending,
        responding_to=(game.action_taken if game.round.kind is RoundKind.RESPONSE else None),
        legacy_pool=tuple(sorted(legacy_candidates(game, viewer), key=lambda card: card.id)),
        dynasty_deck=tuple(
            sorted(game.table.decks[DeckKey(viewer, Side.DYNASTY)].cards, key=lambda card: card.id)
        ),
        attack=attack,
        stats={
            card.id: {stat: effective_stat(game, card, stat) for stat in Stat}
            for card in _modified_cards(game, _identifiable_ids(table))
        },
        unit_force=_unit_forces(game, _identifiable_ids(table)),
    )


def _unit_forces(game: GameState, identifiable: set[str]) -> dict[str, int]:
    """Every identifiable in-play Personality's unit Force, as a battle would count it.

    Taken from :func:`~yasuki_core.engine.rules.units.unit_force` rather than summed from
    :attr:`GameView.stats`, because a unit's total is not a sum of its cards' Force: a Follower
    brings its own, an Item brings a modifier already inside the Personality's, and bowing removes
    some of them and not others.
    """
    return {
        card.id: unit_force(game, card, in_battle_resolution=True)
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint) and card.id in identifiable
    }


def unit_view(game: GameState, personality: L5RCard) -> UnitView:
    """``personality`` and the cards attached to him, as a client draws the unit."""
    return UnitView(leader=personality, attached=tuple(attachments_of(game, personality)))


def _units(game: GameState, battlefield: int, seat: PlayerId) -> tuple[UnitView, ...]:
    """``seat``'s units at ``battlefield``, each with the cards attached to its Personality."""
    return tuple(unit_view(game, personality) for personality in units_at(game, battlefield, seat))


def _occupant(table: ViewSnapshot, province: ZoneKey) -> L5RCard | HiddenCard | None:
    """The card standing in ``province`` as the snapshot's viewer sees it, or None if it is empty.

    Read out of the redacted snapshot rather than the table, so a face-down Dynasty card reaches the
    seat attacking it as a back.
    """
    zone = table.zones.get(province)
    return zone.cards[0] if zone is not None and zone.cards else None


def _destroyed_names(game: GameState, outcome: BattleOutcome | None) -> tuple[str, ...]:
    """The names of the cards ``outcome`` destroyed, or nothing when no battle has been fought."""
    if outcome is None:
        return ()
    cards = game.table.cards_by_id
    return tuple(cards[card_id].name for card_id in outcome.destroyed if card_id in cards)


def _project_attack(game: GameState, table: ViewSnapshot) -> AttackView | None:
    """The attack in progress as ``table``'s viewer sees it, or None outside one.

    The Force totals are the ones resolution would use, so a client showing them shows what the
    battle is actually about to do rather than a figure of its own.
    """
    attack = game.attack
    if attack is None:
        return None
    return AttackView(
        attacker=attack.attacker,
        defender=attack.defender,
        segment=attack.segment,
        current=attack.current,
        battlefields=tuple(
            BattlefieldView(
                province=info.province,
                occupant=_occupant(table, info.province),
                strength=effective_province_strength(game, info.province),
                attacking=_units(game, index, attack.attacker),
                defending=_units(game, index, attack.defender),
                attacking_force=battle.army_force(game, index, attack.attacker),
                defending_force=battle.army_force(game, index, attack.defender),
                fought=index in attack.fought,
                outcome=info.outcome,
                destroyed_names=_destroyed_names(game, info.outcome),
            )
            for index, info in enumerate(attack.battlefields)
        ),
    )
