import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    FatePrint,
    HoldingPrint,
    PersonalityPrint,
    StrongholdPrint,
)
from yasuki_core.engine.rules.state import Phase
from tests.yasuki_core.engine.builders import province_card
from tests.yasuki_core.engine.rules.test_kharmic import _table as _kharmic_table
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Recruit,
    Cycle,
    KharmicDraw,
    KharmicRefill,
    Legacy,
    Pass,
)
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine import runner
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import DynastyDiscard
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.runner import Controls, GameRunner, play_game

PASS = Pass()


def _face_up_holding_in_province(state, card_id, gold_cost, printed_id=""):
    holding = _register(
        state,
        L5RCard.of(
            HoldingPrint,
            id=card_id,
            name="H",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_cost=gold_cost,
            printed_id=printed_id,
        ),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    return holding


def _to_dynasty(runner):
    """Walk the human to the Dynasty phase the way the client does — passing, and running the
    opponent whenever it takes the opportunity back."""
    while runner.view().phase is not Phase.DYNASTY:
        if runner.opponent_holds_priority:
            runner.run_opponent()
        else:
            runner.act(PASS)


def _run_opponents_turn(runner):
    """Play the opponent's whole turn, declining the human's Open window inside its Action phase."""
    while runner.view().active is not runner.human:
        if runner.opponent_holds_priority:
            runner.run_opponent()
        else:
            runner.act(PASS)


def _register(state, card):
    state.cards_by_id[card.id] = card
    return card


def _dealt_table(p1_hand: int) -> TableState:
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(
                state,
                L5RCard.of(FatePrint, id=f"{seat.name}-fd", name="F", side=Side.FATE, owner=seat),
            )
        ]
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(p1_hand):
        hand.add(
            _register(
                state,
                L5RCard.of(FatePrint, id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1),
            )
        )
    return state


def _runner(p1_hand: int = 0) -> GameRunner:
    session = EngineSession.start(_dealt_table(p1_hand), PlayerId.P1, seed=3)
    return GameRunner(session, PlayerId.P1)


def test_passing_walks_the_human_through_the_phases():
    runner = _runner()
    assert runner.view().phase is Phase.ACTION

    runner.act(PASS)
    # The opponent may take Open actions in the human's Action phase, so the phase stays open until
    # it has declined its window too.
    assert runner.view().phase is Phase.ACTION
    assert runner.opponent_holds_priority
    runner.run_opponent()
    assert runner.view().phase is Phase.BATTLE

    runner.act(PASS)  # nobody but the active seat may act in the Battle phase
    assert runner.view().phase is Phase.DYNASTY


def test_passing_through_a_quiet_turn_hands_off_then_back():
    runner = _runner(p1_hand=0)  # no discard for either seat
    _to_dynasty(runner)
    runner.act(PASS)  # ends the Dynasty phase, and with it the turn

    assert runner.opponent_holds_priority  # control rests with the opponent, not yet run
    runner.run_opponent()

    # The human holds an Open window inside the opponent's Action phase, so control comes back
    # there rather than at the top of the human's next turn.
    view = runner.view()
    assert view.active is PlayerId.P2 and view.phase is Phase.ACTION
    assert not runner.opponent_holds_priority

    runner.act(PASS)  # decline it
    runner.run_opponent()  # the rest of the opponent's turn

    view = runner.view()
    assert view.active is PlayerId.P1 and view.turn == 3 and view.phase is Phase.ACTION


def test_human_discard_is_left_pending_then_resolved():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)  # 8 held + 1 drawn = 9 at end of turn
    _to_dynasty(runner)
    runner.act(PASS)

    pending = runner.pending
    assert isinstance(pending, DiscardToHandSize) and pending.count == 1
    assert not runner.opponent_holds_priority  # still the human's while the discard is owed
    assert runner.legal_actions() == []  # no free action offered until it is answered

    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.submit([hand[0].id])

    assert runner.pending is None
    assert runner.opponent_holds_priority  # the turn has passed; the caller runs the opponent
    _run_opponents_turn(runner)
    assert runner.view().active is PlayerId.P1 and runner.view().turn == 3


def test_the_opponents_window_inside_the_humans_turn_is_not_a_hand_off():
    # The client pauses on a turn hand-off so the board can be read, and must not pause for the
    # window the opponent takes inside the human's own Action phase.
    runner = _runner()
    runner.act(PASS)

    assert runner.opponent_holds_priority  # the opponent has the opportunity
    assert not runner.is_opponent_turn  # but the turn is still the human's


def test_running_the_opponent_stops_on_a_finished_game():
    runner = _runner()
    runner.act(PASS)  # hands the Action-phase window to the opponent
    assert runner.opponent_holds_priority
    runner.session.game.loser = PlayerId.P2  # the game ends while the opponent holds the window

    runner.run_opponent()  # returns rather than spinning on a game that offers nobody an action

    assert runner.opponent_holds_priority  # nothing moved


def test_opponents_overfull_turn_auto_discards_without_prompting():
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(
                state,
                L5RCard.of(FatePrint, id=f"{seat.name}-fd", name="F", side=Side.FATE, owner=seat),
            )
        ]
    p2_hand = state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)]
    for i in range(flow.MAX_HAND_SIZE):
        p2_hand.add(
            _register(
                state,
                L5RCard.of(FatePrint, id=f"P2-h{i}", name="H", side=Side.FATE, owner=PlayerId.P2),
            )
        )
    runner = GameRunner(EngineSession.start(state, PlayerId.P1), PlayerId.P1)

    _to_dynasty(runner)
    runner.act(PASS)  # end P1's quiet turn
    _run_opponents_turn(runner)  # P2's overfull turn auto-passes and auto-discards

    assert runner.view().active is PlayerId.P1 and runner.view().turn == 3
    assert runner.pending is None  # the opponent's discard resolved without a prompt
    p2_after = runner.session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards
    assert len(p2_after) == flow.MAX_HAND_SIZE  # 8 held + 1 drawn = 9, auto-trimmed to 8


def test_runner_inputs_stay_replayable():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)
    _to_dynasty(runner)
    runner.act(PASS)
    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.submit([hand[0].id])
    _run_opponents_turn(runner)

    assert replay(runner.session.log) == runner.session.game


def test_province_menu_offers_recruit_with_cost_and_dynasty_discard():
    state = _dealt_table(0)
    state.battlefield.add(
        _register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=PlayerId.P1,
                gold_production=8,
            ),
        )
    )
    _face_up_holding_in_province(state, "P1-buy", gold_cost=5)
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)

    labels = [label for label, _ in runner.province_menu("P1-buy")]
    assert labels == ["Recruit: Pay 5 gold", "Discard from province"]


def test_province_menu_offers_proclaim_for_an_own_clan_personality():
    state = _dealt_table(0)
    state.battlefield.add(
        _register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=PlayerId.P1,
                clan="Crab",
                gold_production=8,
            ),
        )
    )
    person = _register(
        state,
        L5RCard.of(
            PersonalityPrint,
            id="P1-person",
            name="Hero",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_cost=5,
            clan="Crab",
            personal_honor=2,
        ),
    )
    person.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(person)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)

    labels = [label for label, _ in runner.province_menu("P1-person")]
    assert labels == [
        "Recruit: Pay 5 gold",
        "Recruit & Proclaim: Pay 5 gold, gain 2 honor",
        "Discard from province",
    ]


def test_province_menu_drops_recruit_when_it_is_unaffordable():
    state = _dealt_table(0)
    _face_up_holding_in_province(state, "P1-buy", gold_cost=9)  # no producer to pay with
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)

    labels = [label for label, _ in runner.province_menu("P1-buy")]
    assert labels == ["Discard from province"]


def test_province_menu_is_empty_for_a_stronghold():
    # A stronghold has no gold_cost; clicking it must not reach recruit_cost.
    state = _dealt_table(0)
    state.battlefield.add(
        _register(
            state,
            L5RCard.of(
                StrongholdPrint, id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1
            ),
        )
    )
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    assert runner.province_menu("P1-SH") == []


def _dynasty_runner_with_producer(card_id, printed_id, gold_cost):
    state = _dealt_table(0)
    state.battlefield.add(
        _register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=PlayerId.P1,
                gold_production=8,
            ),
        )
    )
    _face_up_holding_in_province(state, card_id, gold_cost=gold_cost, printed_id=printed_id)
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)
    return runner


def test_province_menu_offers_invest_as_a_second_option():
    runner = _dynasty_runner_with_producer("qm", "questionable_market", gold_cost=1)
    labels = [label for label, _ in runner.province_menu("qm")]
    assert labels == [
        "Recruit: Pay 1 gold",
        "Invest: Pay 3 gold",
        "Discard from province",
    ]


def test_province_menu_labels_a_variable_invest_as_a_range():
    runner = _dynasty_runner_with_producer("rh", "rebuilt_harbor", gold_cost=1)
    labels = [label for label, _ in runner.province_menu("rh")]
    assert "Invest: Pay 2–4 gold" in labels  # base 1 plus 1 to 3 invested


def _runner_with_a_province(p1_hand: int = 0) -> GameRunner:
    """A runner whose seat holds one face-up Province card, so Cycle has something to offer."""
    state = _dealt_table(p1_hand)
    _face_up_holding_in_province(state, "P1-pv", gold_cost=1)
    return GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)


def test_board_menu_offers_legacy_in_the_dynasty_phase():
    # Asserted as label-and-action pairs: the menu pairs each ability with its own wording, and a
    # swap would leave every action-only assertion passing while the player reads the wrong entry.
    runner = _runner(p1_hand=1)  # a hand card to pay the banish cost
    _to_dynasty(runner)

    assert runner.board_menu() == [("Legacy: banish a card to search for a Legacy card", Legacy())]


def test_board_menu_offers_cycle_on_the_opening_turn():
    # Both rulebook abilities live here now, so the menu has to sort them by what is legal rather
    # than by which zone was clicked — Cycle is the Action phase's, Legacy the Dynasty phase's.
    runner = _runner_with_a_province()

    assert runner.board_menu() == [
        ("Cycle: put Province cards on the bottom of your deck", Cycle())
    ]


def test_board_menu_is_empty_when_no_rulebook_ability_is_legal():
    runner = _runner_with_a_province(p1_hand=1)
    runner.act(PASS)  # Action -> Battle, which is neither ability's phase

    assert runner.board_menu() == []


def _runner_with_in_play(card) -> GameRunner:
    state = _dealt_table(0)
    state.battlefield.add(_register(state, card))
    return GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)


def test_ability_menu_offers_millet_farm_activation_in_play():
    millet = L5RCard.of(
        HoldingPrint,
        id="millet",
        name="Millet Farm",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id="millet_farm",
        keywords=("Farm",),
        gold_production=1,
    )
    runner = _runner_with_in_play(millet)  # Action phase by default
    assert [label for label, _ in runner.ability_menu("millet")] == [
        "Bow: give a Farm +2 Gold Production"
    ]


def test_ability_menu_is_empty_for_a_card_with_no_ability():
    plain = L5RCard.of(
        HoldingPrint,
        id="plain",
        name="Plain",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_production=2,
    )
    runner = _runner_with_in_play(plain)
    assert runner.ability_menu("plain") == []


class _AlwaysDiscards:
    """Takes a Dynasty Discard whenever one is offered. Stands in for any policy that keeps finding
    something to do, which is what holds a round open."""

    name = "always-discards"

    def choose(self, view, actions):
        return next((a for a in actions if isinstance(a, DynastyDiscard)), actions[0])


def test_a_round_that_never_closes_raises_instead_of_running_forever(monkeypatch):
    # A round ends only when every seat passes consecutively, so a policy that always acts keeps it
    # open. Without the ceiling a Monte Carlo run wedges silently instead of failing.
    monkeypatch.setattr(runner, "MAX_ACTIONS_PER_ROUND", 2)
    state = _dealt_table(0)
    for index in range(4):
        province_card(state, f"prov{index}", printed_id="plain_holding", index=index)
    session = EngineSession.start(state, PlayerId.P1)
    controls = {seat: Controls(_AlwaysDiscards(), AutoAgent()) for seat in PlayerId}

    with pytest.raises(RuntimeError, match="ran past 2 actions"):
        play_game(session, controls, turn_limit=4)


def test_each_kharmic_form_hangs_off_the_card_it_spends():
    # The click that opens the menu is the choice of card, so the Fate form belongs to a hand card
    # and the Dynasty form to a Province card — neither to the board.
    game_runner = GameRunner(EngineSession.start(_kharmic_table(), PlayerId.P1), PlayerId.P1)

    hand = game_runner.hand_menu("P1-k0")
    province = game_runner.province_menu("P1-pk0")

    assert [action for _, action in hand] == [KharmicDraw("P1-k0")]
    assert KharmicRefill("P1-pk0") in [action for _, action in province]
    # Kharmic stays a rulebook action in the engine, matching the CR. Where it surfaces is a client
    # decision, and it spends a card the player names — so it belongs on that card, not on the board
    # with Cycle and Legacy, which act on whole zones.
    board = [action for _, action in game_runner.board_menu()]
    assert not any(isinstance(action, (KharmicDraw, KharmicRefill)) for action in board)
    # The menu has to say what it costs; tracked against the constant so the two cannot drift.
    assert all(f"{legality.KHARMIC_COST} gold" in label for label, _ in hand)


def test_a_hand_card_offers_nothing_when_kharmic_is_unaffordable():
    state = _kharmic_table(production=1)
    game_runner = GameRunner(EngineSession.start(state, PlayerId.P1), PlayerId.P1)

    assert game_runner.hand_menu("P1-k0") == []


def test_a_menu_only_offers_the_card_it_was_opened_on():
    # The menus filter by card id; without that a click on one Kharmic card would offer to spend
    # every other one too.
    state = _kharmic_table(hand_kharmic=2, production=4)
    game_runner = GameRunner(EngineSession.start(state, PlayerId.P1), PlayerId.P1)

    assert [action for _, action in game_runner.hand_menu("P1-k1")] == [KharmicDraw("P1-k1")]


def test_a_card_without_the_keyword_offers_no_kharmic():
    # Kharmic spends a Kharmic card. A plain card in the same zone must not carry the offer, or the
    # menu would invite an action the engine rejects.
    state = _kharmic_table()
    province_card(state, "P1-plain", printed_id="plain_holding", index=2)
    game_runner = GameRunner(EngineSession.start(state, PlayerId.P1), PlayerId.P1)

    offered = [action for _, action in game_runner.province_menu("P1-plain")]

    assert not any(isinstance(action, (KharmicDraw, KharmicRefill)) for action in offered)


def _ruins_runner() -> GameRunner:
    """A runner with Repairing the Ruins face-up in a Province and a findable Holding in each of the
    two piles it searches."""
    state = TableState.empty_two_seat()
    province_card(state, "ruins", printed_id="repairing_the_ruins")
    mine = _register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="mine",
            name="Mine",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id="mine",
            gold_cost=2,
        ),
    )
    kobune = _register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="kobune",
            name="Kobune",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id="kobune",
            gold_cost=2,
        ),
    )
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [mine]
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].add(kobune)
    return GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)


def test_a_search_through_hidden_piles_is_presented_as_a_dialog_not_a_board_selection():
    """Repairing the Ruins' candidates sit in a deck and a discard pile, so there is nothing on the
    board to click — without a search view the ability is unanswerable."""
    runner_ = _ruins_runner()
    runner_.act(ActivateAbility("ruins"))

    search = runner_.search_view()
    assert search is not None
    assert [card.id for card in search.panes["Deck"]] == ["mine"]
    assert [card.id for card in search.panes["Discard"]] == ["kobune"]
    assert search.panes["Provinces"] == []  # offered by the nav bar, but disabled
    assert search.choosable == {"mine", "kobune"}


def test_a_board_targeting_ability_takes_no_search_dialog():
    millet = L5RCard.of(
        HoldingPrint,
        id="millet",
        name="Millet Farm",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id="millet_farm",
        keywords=("Farm",),
        gold_production=1,
    )
    runner_ = _runner_with_in_play(millet)
    runner_.act(ActivateAbility("millet"))

    assert runner_.pending is not None  # it is asking for a target
    assert runner_.search_view() is None  # but the board carries the selection


def test_a_legacy_search_keeps_its_wider_pool_of_everything_it_looked_through():
    """Legacy shows the whole searched pile with only the Legacy cards takeable, so its pool is
    broader than its candidates — the derived routing must not narrow it to the candidates."""
    state = _dealt_table(p1_hand=1)  # a hand card pays the banish cost
    deck = state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    for index, (card_id, keywords) in enumerate([("legacy-card", ("Legacy",)), ("plain-card", ())]):
        deck.cards.append(
            _register(
                state,
                L5RCard.of(
                    HoldingPrint,
                    id=card_id,
                    name=card_id,
                    side=Side.DYNASTY,
                    owner=PlayerId.P1,
                    keywords=keywords,
                    gold_cost=index,
                ),
            )
        )
    # A face-down Province card: the Legacy placement sacrifices one, and it is picked by where it
    # sits rather than by what it is.
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(
        _register(
            state,
            L5RCard.of(
                HoldingPrint, id="pv", name="P", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=1
            ),
        )
    )
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province

    runner_ = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    runner_.session.game.table.cards_by_id["pv"].turn_face_down()
    _to_dynasty(runner_)
    runner_.act(Legacy())

    # The banish cost is paid from hand, which the board shows — that stays a board selection.
    assert runner_.search_view() is None
    runner_.submit(["P1-h0"])

    search = runner_.search_view()
    assert search is not None
    assert "plain-card" in {card.id for card in search.panes["Deck"]}  # shown, but not takeable
    assert search.choosable == {"legacy-card"}

    # Choosing it asks which Province to sacrifice — a board pick, not a second search dialog.
    runner_.submit(["legacy-card"])
    assert runner_.pending is not None
    assert runner_.search_view() is None


def test_a_decision_over_amounts_is_not_mistaken_for_a_search():
    """A variable Invest asks for a number, so its candidates are amounts rather than card ids.
    Looking them up as cards would raise instead of leaving the prompt to answer itself."""
    runner_ = _dynasty_runner_with_producer("rh", "rebuilt_harbor", gold_cost=1)
    runner_.act(Recruit("rh", invest=True))

    assert runner_.pending.candidates == ("1", "2", "3")  # amounts, not cards
    assert runner_.search_view() is None
