import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    Lobby,
    Pass,
    Recruit,
    UseFavorAbility,
)
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import location_of
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
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.session import EngineSession

from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Side

from tests.yasuki_core.engine.builders import (
    attachment,
    combat_segment,
    flip_stronghold,
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

P1, P2 = PlayerId.P1, PlayerId.P2
ANCIENT_CASTLE = "the_ancient_castle_of_the_lion"


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


# --- Doji Aoi, Soul of Doji Chitose ---


def _aoi_after_a_lobby() -> EngineSession:
    """P1 has just Lobbied, bowing a Courtier, with Doji Aoi at home. Lobby is Political under the
    datasheet, so the Response Step that follows is one Aoi may answer."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    state.seats[P1].honor = 10
    put_in_play(state, personality("aoi", printed_id="doji_aoi_soul_of_doji_chitose"))
    put_in_play(state, personality("courtier", personal_honor=2))
    session = EngineSession.start(state, P1)
    session.act(P1, Lobby())
    session.submit(P1, DecisionResponse(("courtier",)))
    return session


def test_doji_aoi_answers_a_political_action_by_straightening_the_personality_she_calls():
    session = _aoi_after_a_lobby()
    assert session.game.table.cards_by_id["courtier"].bowed is True

    session.act(P1, ActivateAbility("aoi"))
    session.submit(P1, DecisionResponse(("courtier",)))

    game = session.game
    courtier = game.table.cards_by_id["courtier"]
    assert courtier.bowed is False
    assert location_of(game.table, courtier) == location_of(
        game.table, game.table.cards_by_id["aoi"]
    )


def test_doji_aoi_offers_her_other_personalities_and_not_herself():
    session = _aoi_after_a_lobby()

    session.act(P1, ActivateAbility("aoi"))

    assert session.game.pending.candidates == ("courtier",)


def test_doji_aoi_is_not_offered_after_an_action_that_is_not_political():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("aoi", printed_id="doji_aoi_soul_of_doji_chitose"))
    put_in_play(state, personality("courtier"))
    put_in_play(state, holding("traders", printed_id="moto_traders"))
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("traders"))

    assert ActivateAbility("aoi") not in session.legal_actions(P1)


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


# --- The Dark Capital of the Spider ---


DARK_CAPITAL = "the_dark_capital_of_the_spider"


def _ancient_castle_in_combat(
    *, attacker: PlayerId = P1, flipped: bool = False, defender_honor: int = 1
) -> EngineSession:
    """The Combat Segment of ``attacker``'s attack: P1's "matsu" (Lion, 3 PH) and "crane" against
    P2's "guard", with the Ancient Castle as P1's Stronghold and the non-acting seat passed."""
    cards = [
        flip_stronghold(ANCIENT_CASTLE, card_id="castle", flipped=flipped),
        personality("matsu", force=2, personal_honor=3, clans=("Lion",)),
        personality("crane", force=2, personal_honor=3, clans=("Crane",)),
        personality("guard", owner=P2, force=2, personal_honor=defender_honor),
    ]
    p1_army, p2_army = {"matsu": 0, "crane": 0}, {"guard": 0}
    if attacker is P1:
        return combat_segment(cards, p1_army, p2_army)
    return combat_segment(cards, p2_army, p1_army, attacker=P2)


def test_the_castle_sends_a_defender_home_and_straightens_itself_for_honor():
    session = _ancient_castle_in_combat()

    session.act(P1, ActivateAbility("castle"))
    session.submit(P1, DecisionResponse(("guard",)))
    game = session.game
    assert game.table.cards_by_id["castle"].bowed
    assert isinstance(game.pending, ChooseCards)
    assert set(game.pending.candidates) == {"matsu", "crane"}
    session.submit(P1, DecisionResponse(("matsu",)))

    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert not game.table.cards_by_id["castle"].bowed
    assert game.table.seats[P1].honor == 1


def test_the_castle_stays_bowed_when_the_second_target_is_declined():
    session = _ancient_castle_in_combat()
    session.act(P1, ActivateAbility("castle"))
    session.submit(P1, DecisionResponse(("guard",)))

    session.submit(P1, DecisionResponse(()))

    game = session.game
    assert game.pending is None
    assert game.table.cards_by_id["castle"].bowed
    assert game.table.seats[P1].honor == 0


def test_the_castle_offers_no_second_target_without_a_higher_personal_honor():
    session = _ancient_castle_in_combat(defender_honor=3)

    session.act(P1, ActivateAbility("castle"))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.pending is None
    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home


def test_the_castle_reaches_only_defending_personalities():
    session = _ancient_castle_in_combat(attacker=P2)

    assert ActivateAbility("castle") not in session.legal_actions(P1)


def test_the_castle_back_adds_a_force_to_attacking_lion_personalities():
    session = _ancient_castle_in_combat(flipped=True)
    game = session.game
    lion_at_home = put_in_play(game, personality("lion_at_home", force=2, clans=("Lion",)))

    assert effective_force(game, game.table.cards_by_id["matsu"]) == 3
    assert effective_force(game, game.table.cards_by_id["crane"]) == 2
    assert effective_force(game, lion_at_home) == 2


def test_the_castle_back_counts_a_lion_at_another_battlefield_as_attacking():
    cards = [
        flip_stronghold(ANCIENT_CASTLE, card_id="castle", flipped=True),
        personality("matsu", force=2, clans=("Lion",)),
        personality("akodo", force=2, clans=("Lion",)),
        personality("guard", owner=P2, force=2),
    ]
    game = combat_segment(cards, {"matsu": 0, "akodo": 1}, {"guard": 0}).game

    assert game.attack.current == 0
    assert effective_force(game, game.table.cards_by_id["akodo"]) == 3


def test_the_castle_back_grants_nothing_while_defending():
    session = _ancient_castle_in_combat(attacker=P2, flipped=True)
    game = session.game

    assert effective_force(game, game.table.cards_by_id["matsu"]) == 2


def test_the_castle_back_gains_the_honor_without_a_second_target():
    session = _ancient_castle_in_combat(flipped=True)

    session.act(P1, ActivateAbility("castle"))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.pending is None
    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert game.table.cards_by_id["castle"].bowed
    assert game.table.seats[P1].honor == 1


def _dark_capital_in_combat(*, flipped: bool = False) -> EngineSession:
    """P1's raider (3F) faces P2's guard (2F) in the Combat Segment, with the Dark Capital as P1's
    Stronghold."""
    cards = [
        flip_stronghold(
            DARK_CAPITAL, card_id="capital", flipped=flipped, gold_production=4, clan="Spider"
        ),
        personality("raider", owner=P1, force=3),
        personality("guard", owner=P2, force=2),
    ]
    return combat_segment(cards, {"raider": 0}, {"guard": 0})


def test_the_capital_gives_its_own_personality_shadowlands_and_fear_equal_to_his_force():
    session = _dark_capital_in_combat()

    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("raider",)))
    choice = session.game.pending
    assert isinstance(choice, ChooseCards) and choice.candidates == ("guard",)
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.pending is None
    assert has_keyword(game, game.table.cards_by_id["raider"], keywords.SHADOWLANDS)
    assert game.table.cards_by_id["guard"].bowed  # Fear 3 reaches the 2F guard
    assert not game.table.cards_by_id["capital"].bowed  # Tireless
    assert game.round.priority is P2


def test_the_capital_gives_an_enemy_shadowlands_and_keeps_the_opportunity_to_act():
    session = _dark_capital_in_combat()

    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.pending is None
    assert has_keyword(game, game.table.cards_by_id["guard"], keywords.SHADOWLANDS)
    assert not game.table.cards_by_id["guard"].bowed
    assert game.round.priority is P1 and game.round.passes == 0
    assert game.additional_action is None


def test_a_pass_at_the_additional_opportunity_does_not_count_toward_closing_the_round():
    session = _dark_capital_in_combat()
    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("guard",)))

    session.act(P1, Pass())

    assert session.game.round.priority is P2 and session.game.round.passes == 1


def test_the_capital_back_fears_as_the_front_does_in_a_battle():
    session = _dark_capital_in_combat(flipped=True)

    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("raider",)))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert game.table.cards_by_id["guard"].bowed
    assert game.round.priority is P2


def test_the_capital_back_takes_an_additional_action_on_its_own_personality_as_an_open():
    game = two_seat_game()
    put_in_play(game, flip_stronghold(DARK_CAPITAL, card_id="capital", flipped=True))
    put_in_play(game, personality("raider", force=3))
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("raider",)))

    game = session.game
    assert game.pending is None
    assert has_keyword(game, game.table.cards_by_id["raider"], keywords.SHADOWLANDS)
    assert game.round.priority is P1 and game.round.passes == 0


def test_the_capital_front_offers_no_open():
    game = two_seat_game()
    put_in_play(game, flip_stronghold(DARK_CAPITAL, card_id="capital"))
    put_in_play(game, personality("raider", force=3))
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("capital") not in session.legal_actions(P1)


def test_the_capital_replays_to_the_same_board():
    session = _dark_capital_in_combat()
    session.act(P1, ActivateAbility("capital"))
    session.submit(P1, DecisionResponse(("raider",)))
    session.submit(P1, DecisionResponse(("guard",)))

    assert replay(session.log) == session.game
