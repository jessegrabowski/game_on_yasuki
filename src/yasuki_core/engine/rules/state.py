from dataclasses import dataclass, field

from numpy.random import Generator, default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.battle.records import AttackPhase
from yasuki_core.engine.rules.decisions import DecisionRequest
from yasuki_core.engine.rules.events import GameEvent
from yasuki_core.engine.rules.modifiers import Ongoing
from yasuki_core.engine.rules.turn.structure import (
    ActionRound,
    Moment,
    PHASE_TIMINGS,
    Phase,
)
from yasuki_core.engine.rules.victory import VictoryRule
from yasuki_core.engine.rules.work import WorkItem


def rules_at_start(table: TableState, seat: PlayerId) -> frozenset[VictoryRule]:
    """The victory rules ``seat`` begins subject to: every one its board can support.

    A seat dealt no Provinces cannot lose the ones it does not have, and dealing is the one moment
    that is distinguishable from having lost them all — afterwards the board looks the same either
    way. A hand-built board therefore excuses itself rather than losing on the first check.
    """
    rules = set(VictoryRule)
    if not any(key.owner is seat and key.role is ZoneRole.PROVINCE for key in table.zones):
        rules.discard(VictoryRule.MILITARY_LOSS)
    return frozenset(rules)


@dataclass(slots=True)
class GameState:
    """The mutable state of one rules-driven game.

    Composes the shared :class:`TableState` (zones, decks, cards, positions) with the turn-level
    bookkeeping the rules engine owns: whose turn it is, the current phase, the per-seat gold pool,
    and once-per usage flags. The table stays a pure substrate so the manual sandbox keeps using it
    unchanged; the rules engine layers its own state on top.

    Attributes
    ----------
    table : TableState
        The shared board substrate the game plays on.
    first_player : PlayerId
        The seat that took the first turn, fixed at game start.
    active : PlayerId
        The seat whose turn it currently is.
    turn : int
        The turn counter, starting at 1 and incremented on each new player-turn.
    phase : Phase
        The current phase of the active player's turn.
    round : ActionRound
        The Action Round open in that phase: who holds the opportunity to act, and how close the
        round is to closing.
    gold : dict mapping PlayerId to int
        Each seat's transient gold pool. Gold produced during a cost payment pools here for further
        costs in the same phase and is cleared at the end of every phase.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None if no one holds it. Default None.
    loser : PlayerId or None
        The seat that has lost the game, or None while the game is ongoing. Set when a loss
        condition fires. Default None.
    loss_reason : str or None
        Why that seat lost, worded for a player, or None while the game is ongoing. Set with
        ``loser`` by :meth:`lose`. Default None.
    winner : PlayerId or None
        The seat that has won the game, or None while the game is ongoing. Default None.
    win_reason : str or None
        What that seat won, worded for a player — the victory's designation where the CR gives it
        one. Set with ``winner`` by :meth:`win`. Default None.
    active_rules : dict mapping PlayerId to frozenset of VictoryRule
        The ways each seat can win or lose. :meth:`start` fills it from :func:`rules_at_start`;
        dropping a rule from a seat's set afterwards excuses that seat alone, which is how a card
        reading "you will not lose, or be eliminated, by Dishonor" is expressed. A seat absent from
        the dict is held to nothing. Default empty.
    attack : AttackPhase or None
        The attack declared in the Attack Phase now open, or None — outside that phase, and inside
        it until the active player declares. Ephemeral and rebuilt by replay. Default None.
    once_per : set of str
        Usage flags for once-per-turn and once-per-game abilities (the Inheritance Rule, Proclaim,
        ...), keyed by a caller-chosen string. Default empty.
    straighten_delayed : dict mapping str to int
        Cards that may not straighten, each with the turn its delay was imposed on. A prohibition
        the card imposes for a stretch of time, where "may remain bowed" is a choice offered each
        turn; it blocks an effect that would straighten the card as surely as it blocks the
        straighten step. Lifted once its controller's next Action Phase has ended, which is why the
        turn it began on is recorded. Default empty.
    seed : int
        The seed recorded for deterministic replay, from which ``rng`` is rebuilt. Default 0.
    rng : numpy.random.Generator
        Every draw the rules engine makes. Replay reconstructs it from ``seed``, so re-running the
        same actions repeats the same draws.
    pending : DecisionRequest or None
        The decision the engine is paused on, awaiting an answer from one seat, or None when the
        engine is free to advance. Default None.
    stack : list of WorkItem
        Deferred engine work — the later steps of an action sequence, run once the current decision
        clears. Ephemeral: replay rebuilds it by re-running the engine, so it is never serialized.
        Default empty.
    ongoing : list of Modifier, KeywordGrant, Minimum, ProvinceModifier or LobbyModifier
        The ongoing records in force — every continuous grant a card has created, kept in
        creation order. Ephemeral: rebuilt by replay and never serialized, like ``stack``, but unlike
        it may be non-empty at rest within a turn, so its order is load-bearing. Default empty.
    tokens_created : int
        How many tokens the game has created, which names the next one. Ephemeral and rebuilt by
        replay like ``stack``; it counts creations rather than tokens on the board, so an id is
        never reused by a token created after an earlier one has gone. Default 0.
    created_by : dict mapping str to str
        Each created card to the card that created it, kept for the life of the game so a card can
        still name what it made after the fact. Ephemeral and rebuilt by replay. Default empty.
    delayed : list of (Moment, Effect)
        Effects held until a moment of play arrives — the CR's delayed effects. Each is resolved and
        dropped when its moment comes, whether or not it still has anything to do. Ephemeral and
        rebuilt by replay. Default empty.
    round_stack : list of ActionRound
        The rounds a Response Step or a battle segment has suspended, innermost last. Each opens a
        round of its own over the round beneath, and closing it puts that round back. What is
        suspended is read off :attr:`ActionRound.kind` rather than off this list's depth. Ephemeral
        and rebuilt by replay. Default empty.
    responded : set of str
        The cards that have already taken a Response in the Response Step now open. A card answers a
        given Step once; nothing else rations a Response, which costs no bow. Cleared as each Step
        opens. Ephemeral and rebuilt by replay. Default empty.
    action : Action or None
        The action now resolving, or None outside one — what a card reacting "from a Kharmic action"
        reads to know which action it is reacting to. Ephemeral and rebuilt by replay. Default None.
    action_taken : str
        What the action now resolving is, worded for a player — what a Response Step names as the
        thing it is answering. Empty outside an action. Ephemeral and rebuilt by replay.
    action_is_favor : bool
        Whether the action now resolving has paid a Favor cost, which is what makes it a Favor
        action. Settled during payment rather than at announcement, because an action with an
        alternate cost is one only when the Favor is the half actually paid (ShE datasheet, The
        Favor Icon). Ephemeral and rebuilt by replay. Default False.
    action_events : list of GameEvent
        What the action now resolving has done so far, in the order it happened, cleared as the next
        action begins. A Response reads it to ask what it is responding to — "discarded a Fate card"
        is a fact about the action rather than about the board it left behind. Ephemeral and rebuilt
        by replay. Default empty.
    """

    table: TableState
    first_player: PlayerId
    active: PlayerId
    turn: int
    phase: Phase
    round: ActionRound
    gold: dict[PlayerId, int]
    favor_holder: PlayerId | None = None
    loser: PlayerId | None = None
    loss_reason: str | None = None
    winner: PlayerId | None = None
    win_reason: str | None = None
    active_rules: dict[PlayerId, frozenset[VictoryRule]] = field(default_factory=dict)
    attack: AttackPhase | None = None
    once_per: set[str] = field(default_factory=set)
    straighten_delayed: dict[str, int] = field(default_factory=dict)
    seed: int = 0
    # Excluded from equality: two Generator objects compare by identity, so a replayed game would
    # never equal the one it replayed even with an identically seeded stream.
    rng: Generator = field(default_factory=lambda: default_rng(0), compare=False, repr=False)
    pending: DecisionRequest | None = None
    stack: list[WorkItem] = field(default_factory=list)
    ongoing: list[Ongoing] = field(default_factory=list)
    tokens_created: int = 0
    created_by: dict[str, str] = field(default_factory=dict)
    delayed: list[tuple[Moment, object]] = field(default_factory=list)
    round_stack: list[ActionRound] = field(default_factory=list)
    responded: set[str] = field(default_factory=set)
    action: Action | None = None
    action_taken: str = ""
    action_is_favor: bool = False
    action_events: list[GameEvent] = field(default_factory=list)

    @property
    def awaiting_decision(self) -> bool:
        """Whether the engine is paused on a pending decision."""
        return self.pending is not None

    @property
    def game_over(self) -> bool:
        """Whether the game has ended — a seat has won, or one has lost."""
        return self.loser is not None or self.winner is not None

    @classmethod
    def start(cls, table: TableState, first_player: PlayerId, *, seed: int = 0) -> "GameState":
        """Begin a game on ``table``: turn 1, ``first_player`` active, the Action phase, and an
        empty gold pool for every seat.

        Parameters
        ----------
        table : TableState
            The dealt board to play on.
        first_player : PlayerId
            The seat taking the first turn.
        seed : int, optional
            Seeds the game's generator and is recorded in its log, which is what lets replay
            rebuild an identical one. Default 0.
        """
        return cls(
            table=table,
            first_player=first_player,
            active=first_player,
            turn=1,
            phase=Phase.ACTION,
            round=ActionRound(PHASE_TIMINGS[Phase.ACTION], priority=first_player),
            gold={seat: 0 for seat in table.seats},
            active_rules={seat: rules_at_start(table, seat) for seat in table.seats},
            seed=seed,
            rng=default_rng(seed),
        )

    def lose(self, seat: PlayerId, reason: str, victory: str) -> None:
        """End the game with ``seat`` the loser, for ``reason`` worded for a player, and award the
        last player left the ``victory`` its designation names.

        The CR states Military and Dishonor Victory this way round — a player loses, and the one
        remaining player has thereby won — so the win is derived here rather than reported
        separately by whatever noticed the loss.

        Parameters
        ----------
        seat : PlayerId
            The seat that has lost.
        reason : str
            Why it lost, worded for a player.
        victory : str
            What the surviving seat has won, worded for a player.
        """
        self.loser = seat
        self.loss_reason = reason
        # The one remaining player, which two seats make the other one. A third seat would make
        # this a count of who is left rather than a flip.
        self.win(PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1, victory)

    def win(self, seat: PlayerId, reason: str) -> None:
        """End the game with ``seat`` the winner, ``reason`` naming what it won.

        An Honor Victory is won outright rather than by anyone losing, so this is reachable without
        a loser; :meth:`lose` calls it for the victories the CR derives from an elimination.
        """
        self.winner = seat
        self.win_reason = reason

    def add_gold(self, seat: PlayerId, amount: int) -> None:
        """Add ``amount`` produced gold to ``seat``'s pool."""
        self.gold[seat] += amount

    def spend_gold(self, seat: PlayerId, amount: int) -> bool:
        """Spend ``amount`` from ``seat``'s pool. Return whether the pool covered it; on an
        insufficient pool, leave it untouched and return False."""
        if self.gold[seat] < amount:
            return False
        self.gold[seat] -= amount
        return True

    def clear_gold(self) -> None:
        """Empty every seat's gold pool, as happens at the end of each phase."""
        for seat in self.gold:
            self.gold[seat] = 0

    def mint_token_id(self) -> str:
        """Claim the next id for a token about to be created.

        Counted rather than drawn from the game's generator, so replaying a tape names the same
        tokens the live game did and every id a projection or a log line carries still resolves.
        """
        self.tokens_created += 1
        return f"token-{self.tokens_created}"

    def creations_of(self, card_id: str) -> tuple[str, ...]:
        """The cards ``card_id`` created that are still on the table, oldest first."""
        return tuple(
            created
            for created, creator in self.created_by.items()
            if creator == card_id and created in self.table.cards_by_id
        )

    def use_once(self, key: str) -> bool:
        """Claim the one-time use named ``key``. Return True the first time and record it; return
        False if it was already used."""
        if key in self.once_per:
            return False
        self.once_per.add(key)
        return True

    def has_used(self, key: str) -> bool:
        """Return whether the one-time use named ``key`` has already been claimed."""
        return key in self.once_per


def once_key(card: L5RCard, tag: str, turn: int) -> str:
    """The usage key for ``card``'s ``tag`` this turn — turn-scoped, so it resets each turn without
    clearing ``GameState.once_per``."""
    return f"{card.id}:{tag}:t{turn}"


def claim_once_per_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Claim a once-per-turn use for ``card``'s ``tag``: True the first time this turn, then False."""
    return game.use_once(once_key(card, tag, game.turn))


def used_this_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Whether ``card``'s ``tag`` has been claimed this turn, without claiming it.

    What a cost has to ask. A cost is evaluated to decide whether an action is legal as well as to
    pay for one, so spending the use merely by looking would spend it on every legality check.
    """
    return game.has_used(once_key(card, tag, game.turn))
