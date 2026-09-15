import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    Recruit,
    UseFavorAbility,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID
from yasuki_core.game_pieces.prints import FatePrint, StrongholdPrint
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.onyx_edition import (
    CAVALRY_FOLLOWER,
    LION_ANCESTOR,
    NAGA_FOLLOWER,
)
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine.rules.abilities.registry import invest_amounts
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    ChooseInvestAmount,
    DecisionResponse,
    DiscardToHandSize,
)
from yasuki_core.engine.rules.gold.discounts import invest_discount, INVEST_DISCOUNTS
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.units.composition import unit_force
from yasuki_core.engine.session import EngineSession

from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Side

from tests.yasuki_core.engine.builders import (
    attachment,
    dealt_table,
    end_phase,
    end_turn,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Kitsu Hayako ---


def _hayako_game(*, gold_production=12):
    """Hayako face-up in a Province, under a Stronghold making ``gold_production``."""
    state = TableState.empty_two_seat()
    token_template(
        state,
        LION_ANCESTOR,
        name="Lion Ancestor",
        card_type="Personality",
        keywords=("Ancestor", "Lion Clan", "Samurai", "Spirit"),
        force=2,
        chi=2,
    )
    put_in_play(state, stronghold(P1, gold_production=gold_production))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    hayako = register(
        state, personality("hayako", printed_id="kitsu_hayako", force=2, chi=3, gold_cost=4)
    )
    hayako.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(hayako)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def _ancestors(session):
    return [card for card in session.game.table.battlefield.cards if card.is_token]


def test_the_offer_names_the_two_prices_and_nothing_between():
    """ "Invest :g2: or :g6:" is a pair of prices, not a span: three, four and five buy nothing."""
    session = _hayako_game()

    session.act(P1, Recruit("hayako", invest=True))

    assert isinstance(session.game.pending, ChooseInvestAmount)
    assert session.game.pending.candidates == ("2", "6")


def test_two_gold_raises_one_ancestor():
    session = _hayako_game()

    session.act(P1, Recruit("hayako", invest=True))
    session.submit(P1, DecisionResponse(("2",)))
    payment = session.game.pending
    pay(session, P1)

    assert payment.amount == 6  # his four Gold Cost and the two Invested
    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor"]


def test_six_gold_raises_two_of_them():
    session = _hayako_game()

    session.act(P1, Recruit("hayako", invest=True))
    session.submit(P1, DecisionResponse(("6",)))
    payment = session.game.pending
    pay(session, P1)

    assert payment.amount == 10  # his four Gold Cost and the six Invested
    ancestors = _ancestors(session)
    assert [card.name for card in ancestors] == ["Lion Ancestor", "Lion Ancestor"]
    assert len({card.id for card in ancestors}) == 2  # two Ancestors, not one counted twice


@pytest.fixture
def _discounted_hayako():
    """Two Gold off his Invest, so his two prices become :g0: and :g4:."""

    @invest_discount("kitsu_hayako")
    def _two_less(card, me, opponents):
        return 2

    yield
    INVEST_DISCOUNTS.pop("kitsu_hayako", None)


def test_a_discount_moves_both_prices_and_takes_the_second_ancestor_with_it(_discounted_hayako):
    """The second Ancestor goes with whichever price is higher, not with the printed six: paying the
    top price buys what the top price buys, even after a discount."""
    session = _hayako_game()
    hayako = session.game.table.cards_by_id["hayako"]
    assert invest_amounts(session.game, hayako) == (0, 4)

    session.act(P1, Recruit("hayako", invest=True))
    session.submit(P1, DecisionResponse(("4",)))
    pay(session, P1)

    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor", "Lion Ancestor"]


def test_a_discount_still_leaves_the_cheaper_price_buying_one(_discounted_hayako):
    session = _hayako_game()

    session.act(P1, Recruit("hayako", invest=True))
    session.submit(P1, DecisionResponse(("0",)))
    pay(session, P1)

    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor"]


def test_the_higher_price_is_not_offered_out_of_reach():
    """With only the cheaper price payable there is nothing to choose, so nothing is asked."""
    session = _hayako_game(gold_production=6)  # four for Hayako leaves two, not six

    session.act(P1, Recruit("hayako", invest=True))

    assert session.game.pending.amount == 6  # straight to paying his cost plus the two


def test_hayako_is_not_offered_an_invest_he_cannot_pay_for():
    session = _hayako_game(gold_production=5)  # four for Hayako leaves one

    assert Recruit("hayako", invest=True) not in session.legal_actions(P1)
    assert Recruit("hayako") in session.legal_actions(P1)


def test_kitsu_hayako_replays_to_the_same_board():
    session = _hayako_game()
    session.act(P1, Recruit("hayako", invest=True))
    session.submit(P1, DecisionResponse(("6",)))
    pay(session, P1)

    assert replay(session.log).table == session.game.table


# --- Spearmen of the Akasha ---


def _spearmen_game(*, bearer_keywords=("Naga",)):
    state = dealt_table(hand=sequence.MAX_HAND_SIZE - 1)
    _naga_follower(state)
    if bearer_keywords is not None:
        put_in_play(state, personality("shahai", force=2, chi=2, keywords=bearer_keywords))
    _hand_the_spearmen(state, "spearmen")
    return EngineSession.start(state, P1)


def _naga_follower(state):
    token_template(
        state,
        NAGA_FOLLOWER,
        name="Naga",
        card_type="Follower",
        keywords=("Naga", "Nonhuman"),
        force=1,
    )


def _hand_the_spearmen(state, card_id):
    spearmen = attachment(
        card_id,
        printed_id="spearmen_of_the_akasha",
        attachment_type=AttachmentType.FOLLOWER,
        force=2,
        keywords=("Naga", "Nonhuman", "Kharmic"),
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, spearmen))


def _trim_the_spearmen(session, card_ids=("spearmen",)):
    end_turn(session)
    assert isinstance(session.game.pending, DiscardToHandSize)
    session.submit(P1, DecisionResponse(card_ids))


def test_trimming_the_hand_offers_the_spearmen_a_naga_to_join():
    """The end-of-turn trim is a discard from hand, which the card names."""
    session = _spearmen_game()

    _trim_the_spearmen(session)

    assert isinstance(session.game.pending, ChooseCards)
    assert session.game.pending.candidates == ("shahai",)
    assert session.game.active is P1, "the turn waits for the answer"


def test_banishing_the_spearmen_equips_the_naga_follower():
    session = _spearmen_game()
    _trim_the_spearmen(session)

    session.submit(P1, DecisionResponse(("shahai",)))

    game = session.game
    follower = attachments_of(game, game.table.cards_by_id["shahai"])[0]
    assert follower.name == "Naga"
    banished = game.table.zones[ZoneKey(P1, ZoneRole.FATE_BANISH)]
    assert [card.id for card in banished.cards] == ["spearmen"]
    assert game.active is PlayerId.P2, "the turn passes once the offer is answered"


def test_two_spearmen_discarded_together_are_each_offered_a_naga():
    """Discarded at one instant, so both offers survive."""
    state = dealt_table(hand=sequence.MAX_HAND_SIZE - 1)
    _naga_follower(state)
    for bearer in ("shahai", "shahai2"):
        put_in_play(state, personality(bearer, force=2, chi=2, keywords=("Naga",)))
    _hand_the_spearmen(state, "spearmen")
    _hand_the_spearmen(state, "spearmen2")
    session = EngineSession.start(state, P1)

    _trim_the_spearmen(session, ("spearmen", "spearmen2"))
    session.submit(P1, DecisionResponse(("shahai",)))
    session.submit(P1, DecisionResponse(("shahai2",)))

    game = session.game
    for bearer in ("shahai", "shahai2"):
        carried = attachments_of(game, game.table.cards_by_id[bearer])
        assert [follower.name for follower in carried] == ["Naga"]
    banished = game.table.zones[ZoneKey(P1, ZoneRole.FATE_BANISH)]
    assert sorted(card.id for card in banished.cards) == ["spearmen", "spearmen2"]


def test_declining_leaves_the_spearmen_lying_in_the_discard():
    session = _spearmen_game()
    _trim_the_spearmen(session)

    session.submit(P1, DecisionResponse(()))

    game = session.game
    assert attachments_of(game, game.table.cards_by_id["shahai"]) == ()
    discard = game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["spearmen"]


def test_only_a_naga_personality_is_offered():
    session = _spearmen_game()
    put_in_play(session.game, personality("bushi", force=3, chi=2, keywords=("Samurai",)))

    _trim_the_spearmen(session)

    assert session.game.pending.candidates == ("shahai",)


def test_nothing_is_offered_with_nobody_to_carry_the_follower():
    session = _spearmen_game(bearer_keywords=None)

    _trim_the_spearmen(session)

    assert session.game.pending is None
    assert session.game.active is PlayerId.P2  # the turn passed with nothing to ask


def test_a_discard_from_play_raises_nothing():
    """ "From your hand or deck": a discard off the board is not one."""
    game = _spearmen_game().game

    fire(game, CardDiscarded("spearmen", Side.FATE, P1))

    assert game.pending is None


# --- Utaku Gorou, Stablemaster ---


def _gorou_game():
    """Gorou in play with a Samurai to mount and a Courtier who does not qualify."""
    game = two_seat_game()
    token_template(
        game, CAVALRY_FOLLOWER, name="Cavalry", card_type="Follower", keywords=("Cavalry",), force=1
    )
    put_in_play(
        game,
        personality(
            "gorou", printed_id="utaku_gorou_stablemaster", force=2, chi=2, keywords=("Samurai",)
        ),
    )
    put_in_play(game, personality("bushi", force=3, chi=2, keywords=("Samurai",)))
    put_in_play(game, personality("courtier", force=1, chi=3, keywords=("Courtier",)))
    return EngineSession.start(game.table, P1)


def test_utaku_gorou_bows_to_mount_a_samurai():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("bushi",)))

    game = session.game
    bushi = game.table.cards_by_id["bushi"]
    horse = attachments_of(game, bushi)[0]
    assert horse.name == "Cavalry"
    assert set(horse.keywords) == {"Cavalry"}
    assert game.table.cards_by_id["gorou"].bowed is True  # the cost
    assert unit_force(game, bushi) == 4  # his 3, plus the Follower's own 1
    # One Follower, to the Samurai chosen. Gorou is a legal target himself and gets nothing.
    assert attachments_of(game, game.table.cards_by_id["gorou"]) == ()


def test_utaku_gorou_offers_only_samurai():
    """ "Your target Samurai Personality," but the Courtier is no horseman, and Gorou himself is."""
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))

    assert set(session.game.pending.candidates) == {"gorou", "bushi"}


def test_utaku_gorou_is_withheld_while_bowed():
    session = _gorou_game()
    session.game.table.cards_by_id["gorou"].bow()

    assert ActivateAbility("gorou") not in session.legal_actions(P1)


def test_utaku_gorou_replays_to_the_same_board():
    session = _gorou_game()
    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("bushi",)))

    assert replay(session.log).table == session.game.table


# --- The Palatial Estate of the Crane ---


def _estate_holding_the_favor() -> EngineSession:
    """P1's Stronghold is the Palatial Estate, P1 holds the Favor and a Fate card to spend."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="estate",
            name="The Palatial Estate of the Crane",
            printed_id="the_palatial_estate_of_the_crane",
            side=Side.DYNASTY,
            owner=P1,
        ),
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(state, L5RCard.of(FatePrint, id="fate", name="Fate", side=Side.FATE, owner=P1))
    )
    session = EngineSession.start(state, P1)
    TakeFavor(P1).perform(session.game)
    return session


def test_the_estate_takes_the_favor_back_after_its_controller_pays_it():
    session = _estate_holding_the_favor()

    session.act(P1, UseFavorAbility("discard_to_draw"))
    session.submit(P1, DecisionResponse(("fate",)))
    assert session.game.favor_holder is None
    session.act(P1, ActivateAbility("estate"))

    assert session.game.favor_holder is P1


def test_the_estate_is_not_offered_after_an_action_that_paid_no_favor():
    session = _estate_holding_the_favor()
    put_in_play(session.game, holding("traders", printed_id="moto_traders"))

    session.act(P1, ActivateAbility("traders"))

    assert ActivateAbility("estate") not in session.legal_actions(P1)
