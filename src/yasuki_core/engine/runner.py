from collections.abc import Iterable, Iterator
from typing import NamedTuple, Protocol

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities, legality
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    Cycle,
    DynastyDiscard,
    KharmicDraw,
    KharmicRefill,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.agents import Agent, AutoAgent
from yasuki_core.engine.rules.decisions import (
    ChooseLegacyCard,
    DecisionRequest,
    DecisionResponse,
)
from yasuki_core.engine.rules.log import Act, Answer
from yasuki_core.engine.rules.policies import Policy
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard

# The places a search can look. Every search dialog offers all three, and disables the ones the
# search in hand does not reach.
PROVINCES_PANE, DECK_PANE, DISCARD_PANE = "Provinces", "Deck", "Discard"
SEARCH_PANES = (PROVINCES_PANE, DECK_PANE, DISCARD_PANE)


class SearchView(NamedTuple):
    """A pending choice presented as a search through the piles rather than a board selection.

    Attributes
    ----------
    panes : dict mapping str to list of L5RCard
        The cards each of :data:`SEARCH_PANES` offers, in that order. A pane the search does not
        reach maps to an empty list, and the dialog shows it disabled rather than hiding it.
    choosable : set of str
        The ids across every pane the seat may actually take.
    """

    panes: dict[str, list[L5RCard]]
    choosable: set[str]


class GameRunner:
    """Drives a single-player rules game through an :class:`EngineSession`.

    The human advances their own turn a phase at a time; when the turn ends, the AI-reserved
    opponent's turn auto-runs until control returns to the human. A decision the human owes is left
    pending for the UI to present; the opponent's decisions are answered by its :class:`Agent`.

    Attributes
    ----------
    session : EngineSession
        The authoritative session this runner drives.
    human : PlayerId
        The seat the human plays.
    """

    def __init__(self, session: EngineSession, human: PlayerId, opponent: Agent | None = None):
        self.session = session
        self.human = human
        self._opponent = opponent or AutoAgent()

    def view(self) -> GameView:
        """Return the human's projection — what the board, phase bar, and panels render."""
        return self.session.project(self.human)

    def legal_actions(self) -> list[Action]:
        """Return the actions the human may take right now (empty when it is not their turn)."""
        return self.session.legal_actions(self.human)

    def province_menu(self, card_id: str) -> list[tuple[str, Action]]:
        """The labeled actions offered for a face-up province card, for its left-click menu: a plain
        Recruit plus its second purchase option where one exists — Invest for an Invest holding,
        Proclaim for an own-clan Personality (all labeled with their gold) — a Dynasty Discard, and
        the Kharmic ability that spends the card. Empty when the card offers nothing right now."""
        game = self.session.game
        card = game.table.cards_by_id[card_id]
        # Deferred until a Recruit action confirms this is a recruitable card: recruit_cost reads
        # gold_cost, which only Dynasty/Fate cards carry. Clicking a card that only offers an
        # activated ability (e.g. a stronghold) must not reach it.
        base: int | None = None
        items: list[tuple[str, Action]] = []
        for action in self.legal_actions():
            if getattr(action, "card_id", None) != card_id:
                continue
            if isinstance(action, Recruit):
                if base is None:
                    base = legality.recruit_cost(game, card)
                if action.invest:
                    items.append((self._invest_label(card, base), action))
                elif action.proclaim:
                    label = f"Recruit & Proclaim: Pay {base} gold, gain {card.personal_honor} honor"
                    items.append((label, action))
                else:
                    items.append((f"Recruit: Pay {base} gold", action))
            elif isinstance(action, DynastyDiscard):
                items.append(("Discard from province", action))
            elif isinstance(action, KharmicRefill):
                items.append(
                    (
                        f"Kharmic: Pay {legality.KHARMIC_COST} gold to refill this Province face-up",
                        action,
                    )
                )
        return items

    def hand_menu(self, card_id: str) -> list[tuple[str, Action]]:
        """The labeled actions offered for one of the human's hand cards, for its left-click menu.
        Empty when the card offers nothing right now."""
        return [
            (f"Kharmic: Pay {legality.KHARMIC_COST} gold to draw a card", action)
            for action in self.legal_actions()
            if isinstance(action, KharmicDraw) and action.card_id == card_id
        ]

    @staticmethod
    def _invest_label(card, base: int) -> str:
        invest = abilities.invest_for(card)
        if invest.minimum == invest.maximum:
            return f"Invest: Pay {base + invest.minimum} gold"
        return f"Invest: Pay {base + invest.minimum}–{base + invest.maximum} gold"

    def ability_menu(self, card_id: str) -> list[tuple[str, Action]]:
        """The activated-ability action offered for an in-play card the human controls, labelled with
        the ability's description, when it is legal to use now. Empty otherwise."""
        for action in self.legal_actions():
            if isinstance(action, ActivateAbility) and action.card_id == card_id:
                ability = abilities.ability_for(self.session.game.table.cards_by_id[card_id])
                label = ability.label if ability is not None else "Activate ability"
                return [(label, action)]
        return []

    def board_menu(self) -> list[tuple[str, Action]]:
        """The labeled rulebook abilities, for a right-click on the empty board. These belong to no
        card, so the board is the only place they can be offered. Empty when none is legal now."""
        labels = {
            Legacy(): "Legacy: banish a card to search for a Legacy card",
            Cycle(): "Cycle: put Province cards on the bottom of your deck",
        }
        return [(labels[action], action) for action in self.legal_actions() if action in labels]

    def legacy_search_pool(self) -> list:
        """The cards the human's Legacy search looks through — its whole dynasty deck plus its
        face-down province cards — for a search dialog to display."""
        return legality.legacy_search_pool(self.session.game, self.human)

    def search_view(self) -> SearchView | None:
        """How to present the pending decision when its candidates are not on the board, or None
        when they all are and the board can carry the selection.

        A choice reaching into a deck or a discard pile has nothing for the player to click, so it
        needs a dialog listing the piles instead. Picking a Province is excepted: the seat points at
        a board position, which it can do whether or not the card sitting there is face-up.
        """
        pending = self.pending
        if pending is None or not pending.candidates:
            return None
        table = self.session.game.table
        if any(card_id not in table.cards_by_id for card_id in pending.candidates):
            return None  # not cards at all — an Invest amount is answered by buttons
        legacy = isinstance(pending, ChooseLegacyCard)
        if not legacy:
            reachable = self._on_the_board()
            if all(card_id in reachable for card_id in pending.candidates):
                return None
        # The Legacy pool is wider than its candidates: every card searched is shown, and only the
        # Legacy cards among them can be taken.
        pool = (
            self.legacy_search_pool()
            if legacy
            else [table.cards_by_id[card_id] for card_id in pending.candidates]
        )
        return SearchView(self._panes(pool), set(pending.candidates))

    def _province_card_ids(self) -> set[str]:
        """Every card sitting in one of the human's Provinces, face-up or not."""
        table = self.session.game.table
        return {
            card.id
            for key, zone in table.zones.items()
            if key.owner is self.human and key.role is ZoneRole.PROVINCE
            for card in zone.cards
        }

    def _on_the_board(self) -> set[str]:
        """The human's cards a click can reach: what is in play, what is in hand, and whatever sits
        in a Province. A Province card counts face-down as well as face-up — the seat picks the
        Province by where it is, not by knowing what is in it."""
        table = self.session.game.table
        return (
            {card.id for card in table.battlefield.cards}
            | {card.id for card in table.zones[ZoneKey(self.human, ZoneRole.HAND)].cards}
            | self._province_card_ids()
        )

    def _panes(self, pool: Iterable[L5RCard]) -> dict[str, list[L5RCard]]:
        """``pool`` bucketed into the three panes a search dialog offers, by where each card sits.
        A pane nothing was found in stays present and empty, so the dialog can disable it."""
        table = self.session.game.table
        provinces = self._province_card_ids()
        discards = {
            card.id
            for role in (ZoneRole.DYNASTY_DISCARD, ZoneRole.FATE_DISCARD)
            for card in table.zones[ZoneKey(self.human, role)].cards
        }
        panes: dict[str, list[L5RCard]] = {name: [] for name in SEARCH_PANES}
        for card in pool:
            if card.id in provinces:
                panes[PROVINCES_PANE].append(card)
            elif card.id in discards:
                panes[DISCARD_PANE].append(card)
            else:
                panes[DECK_PANE].append(card)
        return panes

    @property
    def loser(self) -> PlayerId | None:
        """The seat that has lost the game, or None while it is ongoing."""
        return self.session.game.loser

    @property
    def is_opponent_turn(self) -> bool:
        """Whether the turn itself belongs to the AI-reserved opponent — as opposed to the human
        merely having handed the opportunity on inside a phase of its own turn."""
        return self.session.game.active is not self.human

    @property
    def opponent_holds_priority(self) -> bool:
        """Whether the opportunity to act rests with the AI-reserved opponent, so the UI should run
        it. True for the whole of the opponent's turn, and for its window inside each of the human's
        Action phases."""
        return self.session.game.round.priority is not self.human

    @property
    def pending(self) -> DecisionRequest | None:
        """The decision the human must answer, or None when nothing is awaited from them."""
        pending = self.session.game.pending
        return pending if pending is not None and pending.seat is self.human else None

    def act(self, action: Action) -> None:
        """Perform the human's chosen action. Does not run the opponent — the caller checks
        :attr:`opponent_holds_priority` afterwards and runs it so the change stays visible."""
        self.session.act(self.human, action)

    def undo_last(self) -> bool:
        """Undo the human's last action if it was a Dynasty Discard and nothing has happened since.
        Return whether anything was undone, so the caller can re-render only when it did."""
        return self.session.undo_last(self.human)

    def submit(self, choices: Iterable[str], boosted: Iterable[str] = ()) -> None:
        """Answer the human's pending decision with the chosen ids, and the subset whose bow-time
        production boost was taken (Outlying Farms paying boosted)."""
        self.session.submit(self.human, DecisionResponse(tuple(choices), tuple(boosted)))

    def cancel(self) -> None:
        """Back out of the human's pending decision, undoing the action that raised it."""
        self.session.cancel(self.human)

    def run_opponent(self) -> None:
        """Act for the opponent until the opportunity returns to the human.

        Covers both cases the same way: the opponent's own turn, and the window it holds inside the
        human's Action phase. It passes every opportunity — it is driven by an :class:`Agent`, which
        answers decisions rather than choosing actions — and lets that Agent answer anything it owes.
        """
        game = self.session.game
        while game.round.priority is not self.human and not game.game_over:
            pending = game.pending
            if pending is not None:
                response = self._opponent.decide(pending, self.session.project(pending.seat))
                self.session.submit(pending.seat, response)
            else:
                self.session.act(game.round.priority, Pass())


class Controls(NamedTuple):
    """What drives one seat with no human at it.

    Attributes
    ----------
    policy : Policy
        Chooses which action the seat takes.
    agent : Agent
        Answers the decisions those actions raise. May be the same object as ``policy`` when a
        strategy wants its payments to agree with its choices.
    """

    policy: Policy
    agent: Agent


# How many actions one Action Round may take before the run gives up. A round ends when every seat
# passes consecutively, so a policy that always finds something to take keeps it open forever. No
# legitimate round comes near this; it is a defect detector, not a rule of the game.
MAX_ACTIONS_PER_ROUND = 200


class Observer(Protocol):
    """Watches a driven game at both ends of each turn.

    Turn boundaries are where the board is read, because they are the only moments it is canonical.
    Read after an arbitrary action instead, a producer bowed to pay stops counting and the reading
    depends on where in the turn it was taken.

    Actions are not reported here — the game log already records every one with the seat that took
    it, so an observer that wants them reads the tape between these two calls.

    The two ends answer different questions. As a turn begins,
    :func:`~yasuki_core.engine.rules.flow._begin_turn` has straightened the active seat and revealed
    its provinces, so the board shows what it has to spend. As one ends, the board shows what it
    did: producers bowed to pay are still bowed, and a province it cleared holds a face-down
    replacement.
    """

    def turn_began(self, game: GameState) -> None:
        """Called once ``game.active``'s turn has begun, with the board it starts from."""
        ...

    def turn_ended(self, game: GameState, seat: PlayerId) -> None:
        """Called once ``seat``'s turn is over, with the board it left behind.

        By then the next turn has already begun, but ``seat`` is no longer active and nothing has
        touched what it owns — only the new active seat straightens and reveals.
        """
        ...


def run_game(
    session: EngineSession,
    controls: dict[PlayerId, Controls],
    *,
    turn_limit: int,
    observer: Observer | None = None,
) -> Iterator[Act | Answer]:
    """
    Play ``session`` a step at a time, yielding each input as the engine accepts it.

    Nothing happens until the iterator is advanced, and stopping early leaves the game exactly where
    it stopped — which is what lets a caller pause, inspect between steps, or cancel a run. A turn
    abandoned that way is never closed, so an observer never sees it end and a recorder does not
    report it.

    Parameters
    ----------
    session : EngineSession
        The session to drive. Left at whatever state play reached.
    controls : dict mapping PlayerId to Controls
        What drives each seat. Every seat that could act must appear.
    turn_limit : int
        The last turn to play. Games do not end on their own except by the Legacy whiff, so this
        is what bounds a run.
    observer : Observer, optional
        Told when each turn begins and ends, including the first and the last. Default None, which
        costs nothing.

    Yields
    ------
    Act or Answer
        The input just applied, in the vocabulary the game log records — an action a policy chose,
        or a decision an agent answered.

    Raises
    ------
    RuntimeError
        If a seat has no legal action, a policy returns one it was not offered, or one Action Round
        runs past :data:`MAX_ACTIONS_PER_ROUND` without closing.
    """
    game = session.game
    watched: int | None = None
    playing: PlayerId | None = None
    round_actions = 0
    # A round is identified by the phase of the turn it belongs to: the record itself is frozen and
    # replaced on every yield, so it cannot be compared by identity.
    open_round: tuple[int, Phase] | None = None
    while not game.game_over and game.turn <= turn_limit:
        if observer is not None and game.turn != watched:
            if playing is not None:
                observer.turn_ended(game, playing)
            watched, playing = game.turn, game.active
            observer.turn_began(game)
        pending = game.pending
        if pending is not None:
            seat = pending.seat
            response = controls[seat].agent.decide(pending, session.project(seat))
            session.submit(seat, response)
            yield Answer(seat, response)
            continue

        seat = game.round.priority
        actions = session.legal_actions(seat)
        if not actions:
            raise RuntimeError(f"{seat.name} has no legal action in {game.phase}")
        chosen = controls[seat].policy.choose(session.project(seat), actions)
        if chosen not in actions:
            raise RuntimeError(f"{seat.name}'s policy chose {chosen}, which was not offered")
        here = (game.turn, game.phase)
        round_actions = round_actions + 1 if here == open_round else 1
        open_round = here
        if round_actions > MAX_ACTIONS_PER_ROUND:
            raise RuntimeError(
                f"an Action Round in {game.phase} ran past {MAX_ACTIONS_PER_ROUND} actions; "
                f"{seat.name} last chose {chosen}"
            )
        session.act(seat, chosen)
        yield Act(seat, chosen)

    # The turn the run stopped on has begun but never been closed by the loop.
    if observer is not None and playing is not None:
        observer.turn_ended(game, playing)


def play_game(
    session: EngineSession,
    controls: dict[PlayerId, Controls],
    *,
    turn_limit: int,
    observer: Observer | None = None,
) -> None:
    """
    Play ``session`` to its end or to ``turn_limit``, whichever comes first, mutating it in place.

    Stops only on those two conditions. A driver that inferred its own stopping point would
    silently truncate a run. Drives :func:`run_game` to exhaustion; take that instead when a caller
    needs to act between steps.

    Parameters
    ----------
    session : EngineSession
        The session to drive. Left at whatever state play reached.
    controls : dict mapping PlayerId to Controls
        What drives each seat. Every seat that could act must appear.
    turn_limit : int
        The last turn to play. Games do not end on their own except by the Legacy whiff, so this
        is what bounds a run.
    observer : Observer, optional
        Told when each turn begins and ends, including the first and the last. Default None, which
        costs nothing.

    Raises
    ------
    RuntimeError
        If a seat has no legal action, or a policy returns one it was not offered.
    """
    for _ in run_game(session, controls, turn_limit=turn_limit, observer=observer):
        pass
