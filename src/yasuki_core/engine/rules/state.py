from dataclasses import dataclass, field

from numpy.random import Generator, default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.vocabulary.actions import Action
from yasuki_core.engine.rules.battle.records import AttackPhase
from yasuki_core.engine.rules.duel.records import DuelRecord, DuelStep
from yasuki_core.engine.rules.vocabulary.decisions import DecisionRequest
from yasuki_core.engine.rules.vocabulary.game_events import GameEvent
from yasuki_core.engine.rules.vocabulary.looks import Look
from yasuki_core.engine.rules.vocabulary.modifiers import Ongoing
from yasuki_core.engine.rules.turn.structure import ActionRound, Moment, PHASE_TIMINGS, Phase
from yasuki_core.engine.rules.vocabulary.victory import VictoryRule
from yasuki_core.engine.rules.vocabulary.work import Modification, WorkItem


def rules_at_start(table: TableState, seat: PlayerId) -> frozenset[VictoryRule]:
    """The victory rules ``seat`` begins subject to: every one its board can support.

    A seat dealt no Provinces cannot lose the ones it does not have, and dealing is the one moment
    that is distinguishable from having lost them all. Afterwards the board looks the same either
    way. A hand-built board therefore excuses itself rather than losing on the first check.
    """
    rules = set(VictoryRule)
    if not any(key.owner is seat and key.role is ZoneRole.PROVINCE for key in table.zones):
        rules.discard(VictoryRule.MILITARY_LOSS)
    return frozenset(rules)


@dataclass(slots=True)
class GameState:
    """The mutable state of one rules-driven game.

    Composes the shared :class:`~.TableState` (zones, decks, cards, positions) with the turn-level
    bookkeeping the rules engine owns: whose turn it is, the current phase, the per-seat gold pool,
    and once-per usage flags. The table stays a pure substrate so the manual sandbox keeps using it
    unchanged. The rules engine layers its own state on top.

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
        What that seat won, worded for a player: the victory's designation where the CR gives it
        one. Set with ``winner`` by :meth:`win`. Default None.
    active_rules : dict mapping PlayerId to frozenset of VictoryRule
        The ways each seat can win or lose. :meth:`start` fills it from :func:`~.rules_at_start`.
        Dropping a rule from a seat's set afterwards excuses that seat alone, which is how a card
        reading "you will not lose, or be eliminated, by Dishonor" is expressed. A seat absent from
        the dict is held to nothing. Default empty.
    attack : AttackPhase or None
        The attack declared in the Attack Phase now open: None outside that phase and inside it
        until the active player declares. Ephemeral and rebuilt by replay. Default None.
    duel : DuelRecord or None
        The duel being fought, or the last one fought once it has ended, so what resolves after a
        duel can still read how it went. None until the first one. A duel happens inside a battle
        or outside one, so this is not scoped to a phase the way ``attack`` is. Ephemeral and
        rebuilt by replay, and set through :meth:`begin_duel` rather than by assignment.
        Default None.
    once_per : set of str
        Usage flags for once-per-turn and once-per-game abilities (the Inheritance Rule, Proclaim,
        ...), keyed by a caller-chosen string. Default empty.
    straighten_delayed : dict mapping str to int
        Cards that may not straighten, each with the turn its delay was imposed on. A prohibition
        the card imposes for a stretch of time, where "may remain bowed" is a choice offered each
        turn. It blocks an effect that would straighten the card as surely as it blocks the
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
        Deferred engine work: the later steps of an action sequence, run once the current decision
        clears. Ephemeral: replay rebuilds it by re-running the engine, so it is never serialized.
        Default empty.
    look : Look or None
        The cards a seat is looking at in a deck, or None when nobody is. Opened by
        :class:`~.LookAtTop` and closed by :class:`~.EndLook`. While one is open no decision may
        be backed out of, since the seat has read cards it cannot unread. Ephemeral and rebuilt by
        replay. Default None.
    ongoing : list of Ongoing
        The ongoing records in force: every continuous grant a card has created, kept in creation
        order. Ephemeral: rebuilt by replay and never serialized, like ``stack``, but unlike it may
        be non-empty at rest within a turn, so its order is load-bearing. Default empty.
    tokens_created : int
        How many tokens the game has created, which names the next one. Ephemeral and rebuilt by
        replay like ``stack``. It counts creations rather than tokens on the board, so an id is
        never reused by a token created after an earlier one has gone. Default 0.
    created_by : dict mapping str to str
        Each created card to the card that created it, kept for the life of the game so a card can
        still name what it made after the fact. Ephemeral and rebuilt by replay. Default empty.
    delayed : list of (Moment, Effect)
        Effects held until a moment of play arrives: the CR's delayed effects. Each is resolved and
        dropped when its moment comes, whether or not it still has anything to do. Ephemeral and
        rebuilt by replay. Default empty.
    round_stack : list of ActionRound
        The rounds a Response Step or a battle segment has suspended, innermost last. Each opens a
        round of its own over the round beneath, and closing it puts that round back. What is
        suspended is read off ``ActionRound.kind`` rather than off this list's depth. Ephemeral
        and rebuilt by replay. Default empty.
    responded : set of str
        The cards that have already taken a Response in the Response Step now open. A card answers a
        given Step once. Nothing else rations a Response, which costs no bow. Cleared as each Step
        opens. Ephemeral and rebuilt by replay. Default empty.
    action : Action or None
        The action now resolving, or None outside one: what a card reacting "from a Kharmic action"
        reads to know which action it is reacting to. Ephemeral and rebuilt by replay. Default None.
    action_taken : str
        What the action now resolving is, worded for a player: what a Response Step names as the
        thing it is answering. Empty outside an action. Ephemeral and rebuilt by replay.
    action_seat : PlayerId or None
        The seat that announced the action now resolving, or None outside one. Ephemeral and
        rebuilt by replay. Default None.
    action_targets : tuple of str
        The cards the action now resolving has been pointed at, in the order its abilities hit
        them: the target a seat chose, or every card an untargeted ability reached. A card picked
        inside a later question is not among them. Ephemeral and rebuilt by replay. Default empty.
    action_is_favor : bool
        Whether the action now resolving has paid a Favor cost, which is what makes it a Favor
        action. Settled during payment rather than at announcement, because an action with an
        alternate cost is one only when the Favor is the half actually paid (ShE datasheet, The
        Favor Icon). Ephemeral and rebuilt by replay. Default False.
    action_events : list of GameEvent
        What the action now resolving has done so far, in the order it happened, cleared as the next
        action begins. What an Interrupt or a Response does inside its own round is left out. A
        Response reads it to ask what it is responding to: "discarded a Fate card" is a fact about
        the action rather than about the board it left behind. Ephemeral and rebuilt by replay.
    action_resolved : bool
        Whether the action now resolving has announced its :class:`~.ActionResolved`, so the
        announcement is made once however many answers hand the opportunity on. Ephemeral and
        rebuilt by replay. Default False.
    turn_events : tuple of GameEvent
        Every event of the turn so far, in the order it happened, including what Interrupt and
        Response steps did. What a card folds over to count what happened this turn, as "after
        you resolve two or more Favor actions in one turn" does. Reset as the next turn begins.
        Ephemeral and rebuilt by replay. Default empty.
    conditions_holding : frozenset of (str, str)
        Each card and watch whose condition held when the board last settled, so the condition is
        announced as fulfilled only when it turns true. Ephemeral and rebuilt by replay. Default
        empty.
    announced_from_hand : frozenset of str
        The cards announced out of a hand that have not yet landed: a Strategy in its resolution
        area and an attachment in its entering-play area, both out of play and out of the hand (CR,
        Resolution Area; CR, Entering-Play Areas). The engine keeps them in the hand zone until
        they land, and a count of a hand leaves them out. Ephemeral and rebuilt by replay. Default
        empty.
    asked_outside_action : bool
        Whether the question now pending arose outside any action, as a debug step's does, so
        answering it, and what follows from the answer, hands no opportunity on. Ephemeral and
        rebuilt by replay. Default False.
    interrupts_taken : set of (str, PlayerId)
        The once-per-action rulebook Interrupts taken against the action now resolving, as the
        Interrupt's key and the seat that took it. Cleared as the next action begins. Ephemeral
        and rebuilt by replay. Default empty.
    additional_action : PlayerId or None
        The seat granted an additional action by the action now resolving, which keeps the
        opportunity to act once it is done (CR, Additional Action). Spent as the opportunity is
        handed on. Ephemeral and rebuilt by replay. Default None.
    interrupts_offered : bool
        Whether the action now resolving has opened its Interrupt step. An action opens one,
        over the effects it first hands to step E, and what it defers behind them resolves without
        another (CR, Action Sequence step D). Cleared as the next action begins. Ephemeral and
        rebuilt by replay. Default False.
    modifications : list of Modification
        What the Interrupts taken against the action now resolving make of its effects, each
        bound to the effect it answers and applied as that effect comes up to resolve. Cleared as
        the next action begins. Ephemeral and rebuilt by replay. Default empty.
    hidden_card_shown : bool
        Whether the action now resolving has shown a seat a hidden card, as a search does. No
        decision it raises may be backed out of after that, since a seat cannot unsee what it was
        shown. Cleared once the action resolves and as the next one begins. Ephemeral and rebuilt
        by replay. Default False.
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
    duel: DuelRecord | None = None
    once_per: set[str] = field(default_factory=set)
    straighten_delayed: dict[str, int] = field(default_factory=dict)
    seed: int = 0
    # Excluded from equality: two Generator objects compare by identity, so a replayed game would
    # never equal the one it replayed even with an identically seeded stream.
    rng: Generator = field(default_factory=lambda: default_rng(0), compare=False, repr=False)
    pending: DecisionRequest | None = None
    stack: list[WorkItem] = field(default_factory=list)
    look: Look | None = None
    ongoing: list[Ongoing] = field(default_factory=list)
    tokens_created: int = 0
    created_by: dict[str, str] = field(default_factory=dict)
    delayed: list[tuple[Moment, object]] = field(default_factory=list)
    round_stack: list[ActionRound] = field(default_factory=list)
    responded: set[str] = field(default_factory=set)
    action: Action | None = None
    action_taken: str = ""
    action_seat: PlayerId | None = None
    action_targets: tuple[str, ...] = ()
    action_is_favor: bool = False
    action_events: list[GameEvent] = field(default_factory=list)
    action_resolved: bool = False
    turn_events: tuple[GameEvent, ...] = ()
    conditions_holding: frozenset[tuple[str, str]] = frozenset()
    announced_from_hand: frozenset[str] = frozenset()
    asked_outside_action: bool = False
    interrupts_taken: set[tuple[str, PlayerId]] = field(default_factory=set)
    additional_action: PlayerId | None = None
    interrupts_offered: bool = False
    modifications: list[Modification] = field(default_factory=list)
    hidden_card_shown: bool = False

    @property
    def awaiting_decision(self) -> bool:
        """Whether the engine is paused on a pending decision."""
        return self.pending is not None

    @property
    def game_over(self) -> bool:
        """Whether the game has ended: a seat has won or one has lost."""
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

        The CR states Military and Dishonor Victory this way round: a player loses and the one
        remaining player has thereby won, so the win is derived here rather than reported
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
        a loser. :meth:`lose` calls it for the victories the CR derives from an elimination.
        """
        self.winner = seat
        self.win_reason = reason

    def begin_duel(self, duel: DuelRecord) -> None:
        """Record ``duel`` as the duel being fought, replacing a duel that has already ended.

        Raise ``RuntimeError`` if one is still being fought: nothing in this era creates a duel
        inside another, so a second one is a bug in whatever failed to end the first rather than a
        nesting to support.
        """
        if self.duel is not None and self.duel.step is not DuelStep.ENDED:
            raise RuntimeError("a duel is already being fought")
        self.duel = duel

    def add_gold(self, seat: PlayerId, amount: int) -> None:
        """Add ``amount`` produced gold to ``seat``'s pool."""
        self.gold[seat] += amount

    def spend_gold(self, seat: PlayerId, amount: int) -> bool:
        """Spend ``amount`` from ``seat``'s pool. Return whether the pool covered it. On an
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
        """Claim the one-time use named ``key``. Return True the first time and record it, or
        False if it was already used."""
        if key in self.once_per:
            return False
        self.once_per.add(key)
        return True

    def has_used(self, key: str) -> bool:
        """Return whether the one-time use named ``key`` has already been claimed."""
        return key in self.once_per

    def show_to(self, card: L5RCard, seat: PlayerId) -> None:
        """Let ``seat`` identify ``card``. Showing it a card it had not yet seen sets
        ``hidden_card_shown``."""
        if seat in card.peekers:
            return
        card.add_peeker(seat)
        self.hidden_card_shown = True


def once_key(card: L5RCard, tag: str, turn: int) -> str:
    """The usage key for ``card``'s ``tag`` this turn: turn-scoped, so it resets each turn without
    clearing ``GameState.once_per``."""
    return f"{card.id}:{tag}:t{turn}"


def seat_once_key(seat: PlayerId, tag: str, turn: int) -> str:
    """The usage key for ``seat``'s ``tag`` this turn, for a limit that rests on the player rather
    than on a card ("if you have not played another Flashy Technique this turn")."""
    return f"{tag}:{seat.name}:t{turn}"


def claim_once_per_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Claim a once-per-turn use for ``card``'s ``tag``: True the first time this turn, then
    False."""
    return game.use_once(once_key(card, tag, game.turn))


def used_this_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Whether ``card``'s ``tag`` has been claimed this turn, without claiming it.

    What a cost has to ask. A cost is evaluated to decide whether an action is legal as well as to
    pay for one, so spending the use merely by looking would spend it on every legality check.
    """
    return game.has_used(once_key(card, tag, game.turn))
