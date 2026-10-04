from collections.abc import Iterator
from dataclasses import dataclass, replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard, ZoneView, redact, ViewSnapshot
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.duel.procedure import duel_stat
from yasuki_core.engine.rules.duel.records import DuelRecord
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.stats.calculation import effective_stat, is_modified
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.stats.stat_grants import stat_granters
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.battle.records import BattleOutcome
from yasuki_core.engine.rules.turn.structure import Phase, RoundKind
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, DuelStep, Segment
from yasuki_core.engine.rules.vocabulary.decisions import DecisionRequest, FocusOrStrike
from yasuki_core.engine.rules.legality import legacy_candidates
from yasuki_core.engine.rules.board.queries import terrains_at, units_at
from yasuki_core.engine.rules.units.composition import unit_force
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint


@dataclass(frozen=True, slots=True)
class UnitView:
    """A Personality and the cards attached to him: the CR's unit, as a seat sees it.

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
        The card standing in that Province, redacted like any other. A face-down Dynasty card is a
        back to the seat attacking it. None when the Province is empty.
    fortifications : tuple of L5RCard or HiddenCard
        The cards attached to that Province, in attach order, redacted like the occupant. They stand
        at the battlefield with it and are already counted in ``strength``.
    strength : int
        The Province's effective Strength, which the attacking Force must clear to destroy it.
    terrains : tuple of L5RCard or HiddenCard
        The Terrains in play here, in play order. They stand at the battlefield in neither army.
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
        ``outcome.destroyed``, which carries the same cards as ids, and public because a destroyed
        card is sitting in a discard both seats may read.
    """

    province: ZoneKey
    occupant: L5RCard | HiddenCard | None
    fortifications: tuple[L5RCard | HiddenCard, ...]
    strength: int
    terrains: tuple[L5RCard | HiddenCard, ...]
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
    battle_segment : BattleSegment or None
        Which segment of the battle at ``current`` is open, or None when no battle is being fought.
        This occurs between battles and during a battle's resolution, which is not an Action Round.
    current : int or None
        The battlefield a battle is being fought at, or None between battles.
    battlefields : tuple of BattlefieldView
        One per Defender Province, in Province order.
    """

    attacker: PlayerId
    defender: PlayerId
    segment: Segment
    battle_segment: BattleSegment | None
    current: int | None
    battlefields: tuple[BattlefieldView, ...]


@dataclass(frozen=True, slots=True)
class DuelistView:
    """One side of a duel, as a seat sees it.

    Attributes
    ----------
    seat : PlayerId
        The Personality's controller.
    duelist : L5RCard, HiddenCard or None
        The Personality in the duel, or None once it has left play. A duelist leaving is what ends
        a duel without resolution, and the record outlives it.
    attached : tuple of L5RCard or HiddenCard
        The Followers, Items and Spells on the Personality, in the order they were attached. A duel
        is fought by the whole unit, so a client draws them with him.
    focused : tuple of L5RCard or HiddenCard
        What this side has focused, in the order it focused. A card the viewer may not identify
        arrives as a back, which is every card the other side focused before the reveal.
    duel_stat : int or None
        The stat this duel compares for the Personality, which both seats may read. None once the
        Personality has left play, which is what ends a duel without resolution.
    total : int or None
        The duel stat plus the Focus Values of the focused cards this viewer may read, so a seat's
        own total moves as it focuses and the other's moves only for a card focused face up. Taken
        from the outcome once the duel is decided, since the duel's last step discards the cards a
        live total is summed from. None where the duel ended before reaching one.
    """

    seat: PlayerId
    duelist: L5RCard | HiddenCard | None
    attached: tuple[L5RCard | HiddenCard, ...]
    focused: tuple[L5RCard | HiddenCard, ...]
    duel_stat: int | None
    total: int | None


@dataclass(frozen=True, slots=True)
class DuelView:
    """The duel on the game, as a seat sees it.

    Stays non-None after the duel has ended, because the record does: a client showing the result
    needs it after the engine has moved on.

    Attributes
    ----------
    challenger : DuelistView
        The side that issued the challenge.
    challenged : DuelistView
        The side that was challenged.
    step : DuelStep
        Which step of the procedure the duel reached.
    option : PlayerId or None
        The seat being asked to focus or strike, or None when no such question is open.
    source_name : str
        The name of the card that created the duel.
    ordinal : int
        Which duel of the game this is, counting from one. Two duels running the same Personalities
        to the same result are still two duels, and this is what tells them apart.
    source : L5RCard, HiddenCard or None
        The card that created the duel, where the table still holds it. A Strategy that created one
        sits in its resolution area until the duel is over, so this is where it is drawn.
    winners : tuple of PlayerId
        The seats whose Personalities won. Empty on a duel both lost, and on one not yet decided.
    losers : tuple of PlayerId
        The seats whose Personalities lost, which is both of them on a tie and neither on a duel
        that ended without resolution.
    decided : bool
        Whether the duel reached an outcome. ``winners`` is empty both for a duel nobody won and for
        one not yet decided, so this is what tells those apart.
    """

    challenger: DuelistView
    challenged: DuelistView
    step: DuelStep
    option: PlayerId | None
    ordinal: int
    source_name: str
    source: L5RCard | HiddenCard | None
    winners: tuple[PlayerId, ...]
    losers: tuple[PlayerId, ...]
    decided: bool


@dataclass(frozen=True, slots=True)
class GameView:
    """A per-seat projection of a :class:`~.GameState`. This includes everything one seat is
    entitled to see.

    The table is redacted for the viewer (the opponent's hand, face-down cards, and deck contents
    appear as backs). The turn-level rules fields are public to both seats, and a pending decision
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
        Every seat's gold pool, public to both seats.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None.
    pending : DecisionRequest or None
        The decision the viewer must answer, or None when nothing is awaited from this viewer.
        This includes when the engine is instead waiting on the other seat.
    legacy_pool : tuple of L5RCard
        The viewer's own Legacy cards a search would still find, sorted by card id rather than left
        in deck order. Empty means a Legacy search would whiff and lose the game. Never populated
        for the other seat.
    dynasty_deck : tuple of L5RCard
        The cards left in the viewer's own dynasty deck, sorted by card id rather than left in deck
        order. A seat built its deck and so knows what remains in it, but where those cards sit
        in the shuffle is the part it must not learn, which is what the sort strips. Never
        populated for the other seat.
    responding_to : str or None
        The action, battle or duel an open window for Responses answers, worded for a player, or
        None when no window is open.
        A seat holding no Response still sees it: the window is the whole table's, and a seat is
        passing on something it should be told the name of.
    interrupting : str or None
        The action an open Interrupt step is held against, worded for a player, or None when no
        step is open. Shown to every seat for the same reason.
    attack : AttackView or None
        The attack in progress, or None outside one. Public to both seats: who is attacking
        whom, and which units stand where, is on the table for everyone to see. A Province's
        occupant is redacted like any other card.
    duel : DuelView or None
        The duel on the game, or None where none has been declared this turn. Non-None after a
        duel has ended, for a client showing its result.
    stats : dict mapping str to dict
        Each modified card's effective stats by id, the inner dict keyed by :class:`~.Stat`. Read it
        through :meth:`stat` rather than directly. A card no modifier reaches is absent, and the
        method supplies its printed value.
    unit_force : dict mapping str to int
        Each identifiable in-play Personality's unit Force by his card id, totalled the way a battle
        resolves it: a bowed Personality contributes nothing, a bowed Follower drops out, and an
        Item's modifier rides on the Personality either way. It says what a unit would contribute,
        not whether it may be sent. A bowed Personality cannot be assigned at all, and his entry
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
    interrupting: str | None
    legacy_pool: tuple[L5RCard, ...]
    dynasty_deck: tuple[L5RCard, ...]
    attack: AttackView | None
    duel: DuelView | None
    stats: dict[str, dict[Stat, int]]
    unit_force: dict[str, int]

    def stat(self, card: L5RCard, stat: Stat) -> int:
        """``card``'s effective ``stat``. This includes counters, granted modifiers and all. Reading
        the card's own attribute instead yields the printed number, since modifiers live on the
        game.
        """
        modified = self.stats.get(card.id)
        if modified is not None:
            return modified[stat]
        printed = getattr(card, stat.value, None)
        return 0 if printed is None else printed  # absent, or printed as a dash


def _identifiable_ids(table: ViewSnapshot) -> set[str]:
    """The ids ``table`` lets its viewer identify. A card redacted to a :class:`~.HiddenCard`, and
    one the snapshot omits, are both absent. The snapshot has already decided entitlement, and
    reading it back is what keeps that decision in one place."""
    ids = {
        card.id for zone in table.zones.values() for card in zone.cards if isinstance(card, L5RCard)
    }
    ids.update(entry.card.id for entry in table.battlefield if isinstance(entry.card, L5RCard))
    ids.update(deck.top.id for deck in table.decks.values() if deck.top is not None)
    return ids


def _responding_to(game: GameState) -> str | None:
    """What the open window for Responses answers: the duel in a duel window, the battle's
    Resolution Segment when its resolution opened a Response Step, the action taken otherwise, or
    None where no window is open."""
    if game.round.kind is RoundKind.DUEL_WINDOW:
        return "the duel"
    if game.round.kind is not RoundKind.RESPONSE:
        return None
    attack = game.attack
    if attack is not None and attack.battle_segment is BattleSegment.RESOLUTION:
        segment = ruleset.ACTIVE.battle_segment_name(BattleSegment.RESOLUTION)
        return f"the battle's {segment}"
    return game.action_taken


def _modified_cards(game: GameState, identifiable: set[str]) -> Iterator[L5RCard]:
    """Every identifiable card any active modifier reaches.

    Only some modifier sources are recorded on the game: a counter and a granted effect are, while
    an attachment's printed modifier, a Sensei's grant to its Stronghold and a Kensai's raised
    weapon limit are derived from the board as it stands. :func:`~.is_modified` reads every source
    :func:`~.active_modifiers` knows about, so it is what decides.

    A card no modifier reaches has only its printed stats, which :meth:`GameView.stat` reads
    straight off it. A card the viewer may not identify is skipped: its stats would say what it is,
    and a view carries only what its seat is entitled to.
    """
    granters = stat_granters(game)
    for card in game.table.cards_by_id.values():
        if card.id in identifiable and is_modified(game, card, granters=granters):
            yield card


def project(game: GameState, viewer: PlayerId) -> GameView:
    """Project ``game`` into the view ``viewer`` is entitled to: the board redacted for the viewer,
    the public rules fields, the pending decision only if this viewer is the one to answer it, the
    viewer's own Legacy pool and remaining dynasty deck, and the effective stats of every card
    carrying a modifier."""
    pending = game.pending if game.pending is not None and game.pending.seat is viewer else None
    table = _without_the_resolution_area(game, redact(game.table, viewer))
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
        responding_to=_responding_to(game),
        interrupting=(game.action_taken if game.round.kind is RoundKind.INTERRUPT else None),
        legacy_pool=tuple(sorted(legacy_candidates(game, viewer), key=lambda card: card.id)),
        dynasty_deck=tuple(
            sorted(game.table.decks[DeckKey(viewer, Side.DYNASTY)].cards, key=lambda card: card.id)
        ),
        attack=attack,
        duel=_project_duel(game, table),
        stats={
            card.id: {stat: effective_stat(game, card, stat) for stat in Stat}
            for card in _modified_cards(game, _identifiable_ids(table))
        },
        unit_force=_unit_forces(game, _identifiable_ids(table)),
    )


def _unit_forces(game: GameState, identifiable: set[str]) -> dict[str, int]:
    """Every identifiable in-play Personality's unit Force, as a battle would count it.

    Taken from :func:`~yasuki_core.engine.rules.units.composition.unit_force` rather than summed
    from ``GameView.stats``, because a unit's total is not a sum of its cards' Force: a Follower
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


def _fortifications(table: ViewSnapshot, province: ZoneKey) -> tuple[L5RCard | HiddenCard, ...]:
    """The cards attached to ``province`` as the snapshot's viewer sees them, in attach order.

    Read out of the redacted snapshot, so one the viewer may not identify arrives as a back rather
    than not at all.
    """
    attached = [card_id for card_id, key in table.province_attachments.items() if key == province]
    return _as_seen(table, attached)


def _as_seen(table: ViewSnapshot, card_ids: list[str]) -> tuple[L5RCard | HiddenCard, ...]:
    """The cards in play among ``card_ids`` as the snapshot's viewer sees them, in that order."""
    in_play: dict[str, L5RCard | HiddenCard] = {}
    for placed in table.battlefield:
        card = placed.card
        # A card the viewer cannot identify keeps its id under a different name, and it still has to
        # be found here: an unidentifiable card in play reaches the client as a back, not as a gap.
        in_play[_card_id(card)] = card
    return tuple(in_play[card_id] for card_id in card_ids if card_id in in_play)


def _without_the_resolution_area(game: GameState, table: ViewSnapshot) -> ViewSnapshot:
    """``table`` with every card announced out of a hand taken out of it.

    A card played from hand sits in a resolution area until it lands (CR, Resolution Area), which is
    what :func:`~yasuki_core.engine.rules.board.seats.cards_in_hand` already counts. The zone it is
    drawn from still holds it, so a client rendering that zone shows a Strategy sitting in the hand
    of the player resolving it. The projection is where the two are reconciled, once, rather than in
    each client.
    """
    announced = game.announced_from_hand
    if not announced:
        return table
    zones = {
        key: ZoneView(tuple(card for card in zone.cards if _card_id(card) not in announced))
        if key.role is ZoneRole.HAND
        else zone
        for key, zone in table.zones.items()
    }
    return replace(table, zones=zones)


def _card_id(card: L5RCard | HiddenCard) -> str:
    """A card's id, whether or not the viewer may identify it."""
    return card.card_id if isinstance(card, HiddenCard) else card.id


def _project_duel(game: GameState, table: ViewSnapshot) -> DuelView | None:
    """The duel on the game as ``table``'s viewer sees it, or None where none has been declared.

    Each side's focused cards are pulled through the snapshot, so the other side's arrive as backs
    until the strike turns them face up. The totals follow the same line: they stay None until the
    reveal, because a total is the Focus Values added up.
    """
    duel = game.duel
    if duel is None:
        return None
    option = game.pending.seat if isinstance(game.pending, FocusOrStrike) else None
    outcome = duel.outcome
    return DuelView(
        challenger=_project_duelist(game, table, duel, duel.challenger),
        challenged=_project_duelist(game, table, duel, duel.challenged),
        step=duel.step,
        option=option,
        ordinal=game.duels_begun,
        source_name=_card_name(game, duel.source),
        source=game.table.cards_by_id.get(duel.source),
        winners=() if outcome is None else outcome.winners,
        losers=() if outcome is None else outcome.losers,
        decided=outcome is not None,
    )


def _project_duelist(
    game: GameState, table: ViewSnapshot, duel: DuelRecord, seat: PlayerId
) -> DuelistView:
    """One side of ``duel`` as the snapshot's viewer sees it."""
    wanted = duel.duelist_of(seat)
    # Off the battlefield rather than `cards_by_id`, which indexes the discard piles: a destroyed
    # duelist would otherwise keep publishing a stat for a Personality the view says is gone.
    duelist = next((card for card in game.table.battlefield.cards if card.id == wanted), None)
    seen = _focused_as_seen(game, table, duel, seat)
    attached = () if duelist is None else attachments_of(game, duelist)
    return DuelistView(
        seat=seat,
        duelist=_as_seen(table, [wanted])[0] if duelist is not None else None,
        attached=tuple(_as_seen(table, [card.id for card in attached])),
        focused=seen,
        duel_stat=duel_stat(game, duelist) if duelist is not None else None,
        total=_duel_total(game, duel, seat, duelist, seen),
    )


def _duel_total(
    game: GameState,
    duel: DuelRecord,
    seat: PlayerId,
    duelist: L5RCard | None,
    seen: tuple[L5RCard | HiddenCard, ...],
) -> int | None:
    """The number this side shows: its duel stat plus the Focus Values of the focused cards this
    viewer may read.

    A seat reads its own focused cards, so its own total moves as it focuses, while the other's
    moves only for a card focused face up. A decided duel's own record is preferred, because the
    last step of a duel discards the cards a live total is summed from. An outcome carrying no
    totals is a duel that ended before the reveal, which has no total to show.
    """
    outcome = duel.outcome
    if outcome is not None:
        return outcome.totals.get(seat)
    if duelist is None:
        return None
    read = (card for card in seen if isinstance(card, L5RCard))
    return duel_stat(game, duelist) + sum(effective_stat(game, card, Stat.FOCUS) for card in read)


def _focused_as_seen(
    game: GameState, table: ViewSnapshot, duel: DuelRecord, seat: PlayerId
) -> tuple[L5RCard | HiddenCard, ...]:
    """What ``seat`` has focused, in order, as the snapshot's viewer may see it.

    A card the viewer cannot identify is a back, which is how a seat reads its opponent's face-down
    focus stack. Once the duel's last step has discarded them the areas are gone, so the cards come
    from the outcome's own record instead: a decided duel can still be read for as long as the
    record stands, and by then every one of them is face up in a public pile.
    """
    zone = table.zones.get(ZoneKey(seat, ZoneRole.FOCUS))
    if zone is not None:
        return tuple(zone.cards)
    outcome = duel.outcome
    if outcome is None:
        return ()
    by_id = game.table.cards_by_id
    return tuple(by_id[card_id] for card_id in outcome.focused.get(seat, ()) if card_id in by_id)


def _card_name(game: GameState, card_id: str) -> str:
    """The name of ``card_id``, or the id itself for a card the table no longer holds."""
    card = game.table.cards_by_id.get(card_id)
    return card.name if card is not None else card_id


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
        battle_segment=attack.battle_segment,
        current=attack.current,
        battlefields=tuple(
            BattlefieldView(
                province=info.province,
                occupant=_occupant(table, info.province),
                fortifications=_fortifications(table, info.province),
                strength=effective_province_strength(game, info.province),
                terrains=_as_seen(table, [card.id for card in terrains_at(game, index)]),
                attacking=_units(game, index, attack.attacker),
                defending=_units(game, index, attack.defender),
                attacking_force=resolution.army_force(game, index, attack.attacker),
                defending_force=resolution.army_force(game, index, attack.defender),
                fought=index in attack.fought,
                outcome=info.outcome,
                destroyed_names=_destroyed_names(game, info.outcome),
            )
            for index, info in enumerate(attack.battlefields)
        ),
    )
