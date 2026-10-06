from dataclasses import replace

import pytest

from yasuki_core.engine.rules.rulebook.recruit import RECRUIT, RECRUIT_WITH_INVEST
from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    ability_for,
    ability_label,
    register_ability,
    register_interrupt,
)
from yasuki_core.engine.rules.abilities.model import Interrupt, Interruption, itself
from yasuki_core.engine.rules.vocabulary.decisions import Confirm
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.idioms import PITCH
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import (
    Bow,
    Destroy,
    GrantNegation,
    Effect,
    Move,
    Negated,
    RevokeGrants,
    TakeFavor,
)
from yasuki_core.engine.rules.turn.structure import END_OF_TURN, RoundKind
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.engine.rules.board.queries import has_keyword, rulebook_proxy
from yasuki_core.engine.rules.rulebook.lobby import LOBBY
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, ONYX_LOBBY_PROXY_ID
from yasuki_core.game_pieces.prints import (
    ActionPrint,
    FatePrint,
    RingPrint,
    RulebookPrint,
    StrongholdPrint,
)
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.onyx_edition import (
    CAVALRY_FOLLOWER,
    DENKARU_BONUS,
    DENKARU_PENALTY,
    DRAGON_YOJIMBO,
    LION_ANCESTOR,
    NAGA_FOLLOWER,
    TAMORI_TSUSHIMA_CREATE,
)
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine.rules.abilities.registry import invest_amounts
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    ChooseDiscard,
    ChooseNextTrigger,
    ChooseAmount,
    DecisionResponse,
)
from yasuki_core.engine.rules.gold.discounts import invest_discount, INVEST_DISCOUNTS
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, EnteredPlay
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.stats.ongoing_grants import named_duel_stat
from yasuki_core.engine.rules.duel.procedure import declare_duel
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.game_pieces.counters import PLUS_1F_PLUS_1C
from yasuki_core.engine.rules.rulebook.kharmic import (
    KHARMIC_DRAW,
    KHARMIC_REFILL,
    is_kharmic_action,
)
from yasuki_core.engine.rules.units.composition import unit_force
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.session import EngineSession

from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType, Element, Side

from tests.yasuki_core.engine.builders import (
    datasheet_favor_ability,
    attached,
    attachment,
    contentious_terrain,
    combat_segment,
    flip_stronghold,
    dealt_table,
    end_phase,
    end_turn,
    fate_card,
    focus_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    terrain_at,
    token_template,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability

P1, P2 = PlayerId.P1, PlayerId.P2
ANCIENT_CASTLE = "the_ancient_castle_of_the_lion"


@pytest.fixture(autouse=True)
def _onyx(monkeypatch):
    # The Rings register their Onyx text under the Onyx ruleset, and nothing else here reads a
    # rule the two rulesets differ on, so the whole module plays under it.
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.ONYX)


# --- Fields of Slaughter ---


def _fields_of_slaughter(card_id: str = "fields") -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=card_id,
        name="Fields of Slaughter",
        printed_id="fields_of_slaughter",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )


def _fields_of_slaughter_game() -> GameState:
    """Fields of Slaughter in play for P1 at battlefield 0."""
    game = two_seat_game()
    fields = put_in_play(game, _fields_of_slaughter())
    ops.set_location(game.table, fields, Location.at_battlefield(0))
    return game


@pytest.mark.parametrize(
    ("owner", "location", "gained"),
    [
        (P2, Location.at_battlefield(0), 2),
        (P1, Location.at_battlefield(0), 0),
        (P2, Location.home(P2), 0),
        (P2, Location.at_battlefield(1), 0),
    ],
    ids=["enemy-here", "own-here", "enemy-at-home", "enemy-elsewhere"],
)
def test_fields_of_slaughter_gains_2_honor_only_for_an_enemy_card_destroyed_there(
    owner, location, gained
):
    game = _fields_of_slaughter_game()
    doomed = put_in_play(game, personality("doomed", owner=owner))
    ops.set_location(game.table, doomed, location)

    resolve_effects(game, [Destroy("doomed", P1)])

    assert game.table.seats[P1].honor == gained


def test_fields_of_slaughter_counts_a_created_card_that_leaves_the_table():
    game = _fields_of_slaughter_game()
    token = put_in_play(game, replace(personality("ashigaru", owner=P2), is_token=True))
    ops.set_location(game.table, token, Location.at_battlefield(0))

    resolve_effects(game, [Destroy("ashigaru", P1)])

    assert "ashigaru" not in game.table.cards_by_id
    assert game.table.seats[P1].honor == 2


def test_fields_of_slaughter_enters_play_in_the_engage_segment():
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("a", owner=P1))
    put_in_play(state, personality("d", owner=P2))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _fields_of_slaughter()))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("a@0",)))
    session.submit(P2, DecisionResponse(("d@0",)))
    session.submit(P1, DecisionResponse(("0",)))
    session.act(P2, Pass())

    session.act(P1, PlayStrategy("fields"))

    game = session.game
    assert game.attack.battle_segment is BattleSegment.ENGAGE
    assert location_of(game.table, game.table.cards_by_id["fields"]).battlefield == 0


# --- Imperial Treasurer's Outpost ---


def _treasurers_outpost(*, p2_provinces: int) -> EngineSession:
    """P1 holds the Outpost and no Province, beside P2's ``p2_provinces``."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("outpost", printed_id="imperial_treasurers_outpost"))
    for index in range(p2_provinces):
        province_card(state, f"def-prov{index}", seat=P2, index=index)
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("drawn", P1))]
    return EngineSession.start(state, P1)


def test_imperial_treasurers_outpost_draws_a_card_with_compassion():
    session = _treasurers_outpost(p2_provinces=1)

    session.act(P1, ActivateAbility("outpost"))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["drawn"]


def test_imperial_treasurers_outpost_draws_nothing_without_compassion():
    session = _treasurers_outpost(p2_provinces=0)

    session.act(P1, ActivateAbility("outpost"))

    assert session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards == []


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

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))

    assert isinstance(session.game.pending, ChooseAmount)
    assert session.game.pending.candidates == ("2", "6")


def test_two_gold_raises_one_ancestor():
    session = _hayako_game()

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))
    session.submit(P1, DecisionResponse(("2",)))
    payment = session.game.pending
    pay(session, P1)

    assert payment.amount == 6  # his four Gold Cost and the two Invested
    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor"]


def test_six_gold_raises_two_of_them():
    session = _hayako_game()

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))
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

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))
    session.submit(P1, DecisionResponse(("4",)))
    pay(session, P1)

    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor", "Lion Ancestor"]


def test_a_discount_still_leaves_the_cheaper_price_buying_one(_discounted_hayako):
    session = _hayako_game()

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))
    session.submit(P1, DecisionResponse(("0",)))
    pay(session, P1)

    assert [card.name for card in _ancestors(session)] == ["Lion Ancestor"]


def test_the_higher_price_is_not_offered_out_of_reach():
    """With only the cheaper price payable there is nothing to choose, so nothing is asked."""
    session = _hayako_game(gold_production=6)  # four for Hayako leaves two, not six

    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))

    assert session.game.pending.amount == 6  # straight to paying his cost plus the two


def test_hayako_is_not_offered_an_invest_he_cannot_pay_for():
    session = _hayako_game(gold_production=5)  # four for Hayako leaves one

    assert ActivateAbility("hayako", RECRUIT_WITH_INVEST) not in session.legal_actions(P1)
    assert ActivateAbility("hayako", RECRUIT) in session.legal_actions(P1)


def test_kitsu_hayako_replays_to_the_same_board():
    session = _hayako_game()
    session.act(P1, ActivateAbility("hayako", RECRUIT_WITH_INVEST))
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
    assert isinstance(session.game.pending, ChooseDiscard)
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
    assert isinstance(session.game.pending, ChooseNextTrigger)
    session.submit(P1, DecisionResponse(("spearmen",)))
    session.submit(P1, DecisionResponse(("shahai",)))
    session.submit(P1, DecisionResponse(("spearmen2",)))
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
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    state.seats[P1].honor = 10
    put_in_play(state, personality("aoi", printed_id="doji_aoi_soul_of_doji_chitose"))
    put_in_play(state, personality("courtier", personal_honor=2))
    session = EngineSession.start(state, P1)
    lobby = rulebook_proxy(session.game, P1, ONYX_LOBBY_PROXY_ID)
    session.act(P1, ActivateAbility(lobby.id, LOBBY))
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
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
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
        register(
            state,
            L5RCard.of(
                FatePrint, id="fate", printed_id="fate", name="Fate", side=Side.FATE, owner=P1
            ),
        )
    )
    session = EngineSession.start(state, P1)
    TakeFavor(P1).perform(session.game)
    return session


def test_the_estate_takes_the_favor_back_after_its_controller_pays_it():
    session = _estate_holding_the_favor()

    session.act(P1, datasheet_favor_ability("discard_to_draw"))
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
    assert game.additional_grant is None


def test_a_pass_at_the_additional_opportunity_starts_the_count_that_closes_the_round():
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


def test_the_capitals_fear_reads_the_battle_as_it_resolves():
    session = _dark_capital_in_combat()
    game = session.game
    capital, raider = game.table.cards_by_id["capital"], game.table.cards_by_id["raider"]
    effects = ability_for(game, capital).effects(game, capital, raider)

    resolve_effects(game, [Move("guard", Location.home(P2)), *effects])

    assert game.pending is None
    assert not game.table.cards_by_id["guard"].bowed


# --- The Sacred Ground of the Phoenix ---

SACRED_GROUND = "the_sacred_ground_of_the_phoenix"


def _sacred_ground(
    *, flipped: bool = False, production: int = 4, opponent_kharmic: bool = False
) -> EngineSession:
    """P1 has used the Sacred Ground's Open, holding a Kharmic and a plain card in hand and one of
    each face-up in a Province, with gold enough for one paid Kharmic use. P2 has passed the
    window back, unless ``opponent_kharmic`` gives P2 a Kharmic card and the gold to spend it, in
    which case P2 still holds the window."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        state,
        flip_stronghold(
            SACRED_GROUND, card_id="ground", flipped=flipped, gold_production=production
        ),
    )
    hand = state.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(
        register(
            state,
            L5RCard.of(
                FatePrint,
                id="k",
                printed_id="k",
                name="Kharmic Fate",
                side=Side.FATE,
                owner=P1,
                keywords=("Kharmic",),
            ),
        )
    )
    hand.add(register(state, fate_card("plain", P1)))
    province_card(state, "pk", printed_id="plain_holding", keywords=("Kharmic",), index=0)
    province_card(state, "pp", printed_id="plain_holding", index=1)
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("fd", P1))]
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, holding("dd", printed_id="plain_holding"))
    ]
    if opponent_kharmic:
        put_in_play(
            state, holding("P2-sh", printed_id="plain_stronghold", gold_production=2, owner=P2)
        )
        state.zones[ZoneKey(P2, ZoneRole.HAND)].add(
            register(
                state,
                L5RCard.of(
                    FatePrint,
                    id="P2-k",
                    printed_id="P2-k",
                    name="Kharmic Fate",
                    side=Side.FATE,
                    owner=P2,
                    keywords=("Kharmic",),
                ),
            )
        )
        state.decks[DeckKey(P2, Side.FATE)].cards = [register(state, fate_card("P2-fd", P2))]
    session = EngineSession.start(state, P1)
    session.act(P1, ActivateAbility("ground"))
    if not opponent_kharmic:
        session.act(P2, Pass())  # the Open handed the window on; P2 declines it
    return session


def _kharmic_offers(session: EngineSession) -> set[ActivateAbility]:
    return {
        action
        for action in session.legal_actions(P1)
        if isinstance(action, ActivateAbility)
        and action.ability_key in (KHARMIC_DRAW, KHARMIC_REFILL)
    }


def _kharmic_draw_labels(session: EngineSession) -> dict[str, str]:
    """What the menu shows for the Kharmic draw on each hand card that has one."""
    game = session.game
    return {
        card_id: ability_label(game.table.cards_by_id[card_id], ability)
        for card_id in ("k", "plain")
        for ability in abilities_for(game, game.table.cards_by_id[card_id])
        if ability.key == KHARMIC_DRAW
    }


def test_the_license_stands_in_for_kharmic_on_a_kharmic_card_and_adds_it_to_any_other():
    session = _sacred_ground()

    assert _kharmic_offers(session) == {
        ActivateAbility("k", KHARMIC_DRAW),
        ActivateAbility("plain", KHARMIC_DRAW),
        ActivateAbility("pk", KHARMIC_REFILL),
        ActivateAbility("pp", KHARMIC_REFILL),
    }
    assert _kharmic_draw_labels(session) == {
        "k": "Open: Discard this card to draw a card",
        "plain": "Open, :g2:: Discard this card to draw a card",
    }


def test_the_front_is_free_on_a_kharmic_card_and_the_use_revokes_the_license():
    session = _sacred_ground()

    session.act(P1, ActivateAbility("k", KHARMIC_DRAW))

    game = session.game
    assert game.pending is None
    assert [c.id for c in game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards] == ["k"]
    assert [c.id for c in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards] == ["plain", "fd"]
    assert not game.table.cards_by_id["ground"].bowed
    assert game.ongoing == []
    session.act(P2, Pass())
    assert _kharmic_offers(session) == {ActivateAbility("pk", KHARMIC_REFILL)}
    assert _kharmic_draw_labels(session) == {
        "k": "Repeatable Open, :g2:: Discard a Kharmic card to draw a card"
    }


def test_the_front_costs_the_printed_gold_on_a_non_kharmic_card():
    session = _sacred_ground()

    session.act(P1, ActivateAbility("pp", KHARMIC_REFILL))
    pay(session, P1)

    game = session.game
    assert game.table.cards_by_id["ground"].bowed
    province = game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 1)]
    assert [c.id for c in province.cards] == ["dd"] and province.cards[0].face_up
    assert game.ongoing == []


def test_the_license_reaches_a_card_drawn_after_the_open():
    # The license rests on the seat, not on the cards held when the Open resolved.
    session = _sacred_ground()
    TakeFavor(P1).perform(session.game)

    session.act(P1, datasheet_favor_ability("discard_to_draw"))
    session.submit(P1, DecisionResponse(("plain",)))
    session.act(P2, Pass())

    assert ActivateAbility("fd", KHARMIC_DRAW) in session.legal_actions(P1)
    assert session.game.ongoing != []


def test_cancelling_at_the_payment_leaves_the_license():
    session = _sacred_ground()

    session.act(P1, ActivateAbility("plain", KHARMIC_DRAW))
    session.cancel(P1)

    assert ActivateAbility("plain", KHARMIC_DRAW) in session.legal_actions(P1)


def test_the_license_is_gone_at_the_end_of_the_turn():
    session = _sacred_ground()
    end_turn(session)
    session.act(P2, Pass())

    assert _kharmic_offers(session) == {
        ActivateAbility("k", KHARMIC_DRAW),
        ActivateAbility("pk", KHARMIC_REFILL),
    }


def test_the_back_is_free_on_any_card():
    session = _sacred_ground(flipped=True, production=0)

    assert _kharmic_offers(session) == {
        ActivateAbility("k", KHARMIC_DRAW),
        ActivateAbility("plain", KHARMIC_DRAW),
        ActivateAbility("pk", KHARMIC_REFILL),
        ActivateAbility("pp", KHARMIC_REFILL),
    }
    assert _kharmic_draw_labels(session)["plain"] == "Open: Discard this card to draw a card"

    session.act(P1, ActivateAbility("plain", KHARMIC_DRAW))

    assert session.game.pending is None
    assert [c.id for c in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards] == ["k", "fd"]
    session.act(P2, Pass())
    assert _kharmic_offers(session) == set()


def test_a_licensed_use_on_a_non_kharmic_card_reads_as_a_kharmic_action_while_it_resolves(
    reacting,
):
    # A card discarded by the licensed use asks "was that a Kharmic action?" the way Blood of Fu
    # Leng does. The license is revoked only after the action resolves, so the answer is yes.
    session = _sacred_ground()
    state = session.game.table
    probe = L5RCard.of(
        FatePrint, id="probe", name="Probe", printed_id="kharmic_probe", side=Side.FATE, owner=P1
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, probe))

    def saw_a_kharmic_action(ctx):
        if ctx.event.card_id == ctx.card.id and is_kharmic_action(ctx.game):
            ctx.card.set_note("kharmic")
        return []

    reacting(CardDiscarded, "kharmic_probe", saw_a_kharmic_action)

    session.act(P1, ActivateAbility("probe", KHARMIC_DRAW))
    pay(session, P1)

    assert session.game.table.cards_by_id["probe"].note == "kharmic"
    assert session.game.ongoing == []


def test_the_license_is_consumed_after_the_action_and_not_among_its_effects():
    # Nothing in the licensed ability's own effects revokes the license, so an Interrupt to the
    # action has nothing of the license to answer, and what does revoke it cannot be interrupted.
    session = _sacred_ground()
    game = session.game
    plain = game.table.cards_by_id["plain"]
    licensed = ability_for(game, plain, KHARMIC_DRAW)

    assert not any(
        isinstance(effect, RevokeGrants) for effect in licensed.effects(game, plain, plain)
    )
    assert not RevokeGrants("ground").is_interruptible(game)


def test_the_opponents_kharmic_use_leaves_the_license_standing():
    # "The next time you use the rulebook Kharmic ability": P2's use is not P1's.
    session = _sacred_ground(opponent_kharmic=True)

    session.act(P2, ActivateAbility("P2-k", KHARMIC_DRAW))
    pay(session, P2)

    assert len(session.game.ongoing) == 2
    assert ActivateAbility("plain", KHARMIC_DRAW) in session.legal_actions(P1)


def test_the_sacred_ground_replays_to_the_same_board():
    session = _sacred_ground()
    session.act(P1, ActivateAbility("plain", KHARMIC_DRAW))
    pay(session, P1)

    assert replay(session.log) == session.game


# --- The five Rings ---

P2 = PlayerId.P2
MOVE_PROBE = "probe_battle_move_an_enemy_home"


def _ring(card_id: str, printed_id: str, owner: PlayerId = P1) -> L5RCard:
    return L5RCard.of(
        RingPrint,
        id=card_id,
        name=printed_id,
        printed_id=card_id if printed_id is None else printed_id,
        side=Side.FATE,
        owner=owner,
    )


def _ring_game(*in_play: L5RCard, held: tuple[L5RCard, ...] = ()) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    return EngineSession.start(state, P1)


def _answer_until_settled(session: EngineSession, *answers: str) -> None:
    """Answer each decision the action raises: a named answer where one of ``answers`` is among
    the candidates, an empty answer to everything else, payments included."""
    pending = session.game.pending
    while pending is not None:
        named = [each for each in answers if each in getattr(pending, "candidates", ())]
        session.submit(pending.seat, DecisionResponse(tuple(named[:1])))
        pending = session.game.pending


def _in_play(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def _fate_discard(session: EngineSession, seat: PlayerId) -> set[str]:
    pile = session.game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)]
    return {card.id for card in pile.cards}


def test_ring_of_air_straightens_a_bowed_personality_and_bows():
    session = _ring_game(personality("samurai"), _ring("air", "ring_of_air"))
    session.game.table.cards_by_id["samurai"].bow()

    session.act(P1, ActivateAbility("air", "air"))
    _answer_until_settled(session, "samurai")

    cards = session.game.table.cards_by_id
    assert not cards["samurai"].bowed
    assert cards["air"].bowed


def test_ring_of_air_pitched_from_hand_straightens_and_is_discarded():
    session = _ring_game(personality("samurai"), held=(_ring("air", "ring_of_air"),))
    session.game.table.cards_by_id["samurai"].bow()

    session.act(P1, PlayStrategy("air", PITCH))
    _answer_until_settled(session, "samurai")

    assert not session.game.table.cards_by_id["samurai"].bowed
    assert "air" in _fate_discard(session, P1)
    assert "air" not in _in_play(session)


def test_ring_of_the_void_enters_from_hand_and_discards_the_rest_of_the_hand():
    held = (_ring("void", "ring_of_the_void"), fate_card("one", P1), fate_card("two", P1))
    session = _ring_game(held=held)
    assert PlayStrategy("void", "enter") in session.legal_actions(P1)

    session.act(P1, PlayStrategy("void", "enter"))
    _answer_until_settled(session)

    assert "void" in _in_play(session)
    assert _fate_discard(session, P1) == {"one", "two"}
    assert session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards == []


def _hold_the_favor(session: EngineSession, seat: PlayerId) -> None:
    session.game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    resolve_effects(session.game, [TakeFavor(seat)])


def _favor_in_hand(session: EngineSession, seat: PlayerId) -> bool:
    hand = session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
    return any(card.printed_id == IMPERIAL_FAVOR_ID for card in hand)


def test_ring_of_the_void_entering_keeps_the_imperial_favor():
    held = (_ring("void", "ring_of_the_void"), fate_card("one", P1))
    session = _ring_game(held=held)
    _hold_the_favor(session, P1)

    session.act(P1, PlayStrategy("void", "enter"))
    _answer_until_settled(session)

    assert _fate_discard(session, P1) == {"one"}
    assert _favor_in_hand(session, P1)


def test_ring_of_the_void_is_withheld_with_three_rings_in_play():
    rings = [_ring(f"r{index}", "ring_of_air") for index in range(3)]
    session = _ring_game(*rings, held=(_ring("void", "ring_of_the_void"),))

    assert PlayStrategy("void", "enter") not in session.legal_actions(P1)


def test_ring_of_the_void_counts_only_its_holders_rings():
    theirs = [_ring(f"r{index}", "ring_of_air", P2) for index in range(3)]
    session = _ring_game(*theirs, held=(_ring("void", "ring_of_the_void"),))

    assert PlayStrategy("void", "enter") in session.legal_actions(P1)


def _void_draw_game(*, opponent_holds: int) -> EngineSession:
    session = _ring_game(
        _ring("void", "ring_of_the_void"),
        held=tuple(fate_card(f"theirs{index}", P2) for index in range(opponent_holds)),
    )
    state = session.game.table
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("top", P1))]
    return session


def test_ring_of_the_void_draws_and_keeps_the_card_while_not_ahead():
    session = _void_draw_game(opponent_holds=1)

    session.act(P1, ActivateAbility("void", "void"))

    assert session.game.pending is None
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["top"]


def test_ring_of_the_void_discards_a_card_once_the_hand_is_the_largest():
    session = _void_draw_game(opponent_holds=0)

    session.act(P1, ActivateAbility("void", "void"))

    assert session.game.pending is None
    assert "top" in _fate_discard(session, P1)


@pytest.mark.parametrize("favor_holder", [P1, P2], ids=["own-favor", "opponents-favor"])
def test_ring_of_the_void_does_not_count_or_discard_the_imperial_favor(favor_holder):
    session = _void_draw_game(opponent_holds=0)
    _hold_the_favor(session, favor_holder)

    session.act(P1, ActivateAbility("void", "void"))

    assert session.game.pending is None
    assert "top" in _fate_discard(session, P1)
    assert session.game.favor_holder is favor_holder


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


MOVE_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: move a target enemy Personality home",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [Move(target.id, Location.home(target.owner))],
)


def _battle(
    *,
    raider_force: int = 2,
    raider_printed_id: str | None = None,
    in_play: tuple[L5RCard, ...] = (),
    held: tuple[L5RCard, ...] = (),
) -> EngineSession:
    """P1 attacks P2's Province with a raider; P2 defends with a guard of Force 3. Left in the
    Combat Segment with P1 holding the opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=raider_force, printed_id=raider_printed_id))
    put_in_play(state, personality("guard", owner=P2, force=3))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    if session.game.round.priority is not P1:
        session.act(P2, Pass())
    return session


def _resolve_the_battle(session: EngineSession) -> None:
    while session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())


def _fire_battle(*, raider_force: int) -> EngineSession:
    # An enemy Holding is the target, because resolution does not destroy it either way.
    return _battle(
        raider_force=raider_force,
        in_play=(_ring("fire", "ring_of_fire"), holding("farm", owner=P2)),
    )


def test_ring_of_fire_destroys_the_target_after_a_battle_its_holder_lost():
    session = _fire_battle(raider_force=1)

    session.act(P1, ActivateAbility("fire", "fire"))
    _answer_until_settled(session, "farm")
    _resolve_the_battle(session)

    assert "farm" not in _in_play(session)


def test_ring_of_fire_spares_the_target_after_a_battle_its_holder_won():
    session = _fire_battle(raider_force=5)

    session.act(P1, ActivateAbility("fire", "fire"))
    _answer_until_settled(session, "farm")
    _resolve_the_battle(session)

    assert "farm" in _in_play(session)


def test_ring_of_fire_spares_the_target_after_a_tie():
    session = _fire_battle(raider_force=3)

    session.act(P1, ActivateAbility("fire", "fire"))
    _answer_until_settled(session, "farm")
    _resolve_the_battle(session)

    assert "farm" in _in_play(session)


def test_ring_of_water_moves_a_personality_to_the_battlefield_and_another_home():
    session = _battle(in_play=(_ring("water", "ring_of_water"), personality("reserve")))

    session.act(P1, ActivateAbility("water", "water"))
    _answer_until_settled(session, "reserve")
    table = session.game.table
    assert location_of(table, table.cards_by_id["reserve"]).battlefield == 0

    session.act(P2, Pass())
    table.cards_by_id["water"].unbow()
    session.act(P1, ActivateAbility("water", "water"))
    _answer_until_settled(session, "raider")

    assert location_of(table, table.cards_by_id["raider"]).is_home


def test_ring_of_earth_negates_the_battle_actions_move_from_play():
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _battle(
            raider_printed_id=MOVE_PROBE, in_play=(_ring("earth", "ring_of_earth", P2),)
        )
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))
        assert session.game.round.kind is RoundKind.INTERRUPT

        session.act(P2, PlayInterrupt("earth"))
        _answer_until_settled(session)

        table = session.game.table
        assert location_of(table, table.cards_by_id["guard"]).battlefield == 0
        assert table.cards_by_id["earth"].bowed


def test_ring_of_earth_pitched_from_hand_negates_the_move_and_is_discarded():
    with probe_ability(MOVE_PROBE, MOVE_ABILITY):
        session = _battle(raider_printed_id=MOVE_PROBE, held=(_ring("earth", "ring_of_earth", P2),))
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        session.act(P2, PlayInterrupt("earth"))
        _answer_until_settled(session)

        table = session.game.table
        assert location_of(table, table.cards_by_id["guard"]).battlefield == 0
        assert "earth" in _fate_discard(session, P2)


FAVOR_PROBE = "favor_probe_onyx"
register_ability(
    FAVOR_PROBE,
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Favor Open: nothing",
        cost=no_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        hits_every_target=True,
        repeatable=True,
    ),
)


def _air_in_hand_game() -> EngineSession:
    return _ring_game(
        holding("favor", printed_id=FAVOR_PROBE, keywords=(keywords.FAVOR,)),
        held=(_ring("air", "ring_of_air"),),
    )


def test_ring_of_air_is_offered_after_the_second_favor_action_of_the_turn():
    session = _air_in_hand_game()

    session.act(P1, ActivateAbility("favor"))
    assert session.game.pending is None
    session.act(P2, Pass())
    session.act(P1, ActivateAbility("favor"))

    assert isinstance(session.game.pending, Confirm) and session.game.pending.seat is P1
    assert project(session.game, P2).pending is None


def _earth_battle(
    *,
    attacker: PlayerId,
    raider_force: int = 1,
    assign_raider: bool = True,
) -> EngineSession:
    """``attacker`` attacks the other seat's first Province with a raider of ``raider_force``; the
    Defender holds a guard of Force 3 and a second Province, so a lost battle does not end the
    game. Ring of Earth waits in P1's hand. Left on the resolution's first question, or on the
    choice of the next battlefield when it asks none."""
    defender = P2 if attacker is P1 else P1
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=defender, index=0)
    province_card(state, "def-prov1", seat=defender, index=1)
    province_card(state, "atk-prov0", seat=attacker, index=0)
    put_in_play(state, personality("raider", owner=attacker, force=raider_force))
    put_in_play(state, personality("guard", owner=defender, force=3))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _ring("earth", "ring_of_earth")))
    session = EngineSession.start(state, attacker)
    end_phase(session)
    session.act(attacker, DeclareAttack())
    session.submit(attacker, DecisionResponse(("raider@0",) if assign_raider else ()))
    session.submit(defender, DecisionResponse(("guard@0",)))
    session.submit(attacker, DecisionResponse(("0",)))
    while session.game.pending is None and session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())
    return session


def test_ring_of_earth_is_offered_after_a_battle_at_the_owners_province():
    session = _earth_battle(attacker=P2)

    assert isinstance(session.game.pending, Confirm) and session.game.pending.seat is P1
    session.submit(P1, DecisionResponse(("earth",)))

    assert "earth" in _in_play(session)


def test_ring_of_earth_is_not_offered_after_a_battle_at_the_enemys_province():
    # The Onyx text drops the Attacker clause for "at your Province", which the Attacker's is not.
    session = _earth_battle(attacker=P1)

    assert not isinstance(session.game.pending, Confirm)


register_interrupt(
    "negate_terrain_probe",
    Interrupt(
        label="Interrupt: negate the action's effects",
        answers=Effect,
        interrupt=lambda game, source, effect: Interruption(Negated(effect)),
        answers_every=True,
    ),
)


def _water_combat(
    *,
    raider_force: int = 9,
    defenders: tuple[str, ...] = ("guard@0",),
    held: dict[PlayerId, tuple[L5RCard, ...]],
    their_terrain: PlayerId | None = None,
) -> EngineSession:
    """P1 attacks P2's first Province with a raider of ``raider_force`` against a guard of Force 3,
    P2 assigning ``defenders``, with ``held`` in each seat's hand and, when ``their_terrain`` names
    a seat, that seat's Terrain already at the battlefield. P2 keeps a second Province. Paused as
    the Combat Segment opens, with the Defender holding the first opportunity."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("raider", owner=P1, force=raider_force))
    put_in_play(state, personality("guard", owner=P2, force=3))
    for seat, cards in held.items():
        for card in cards:
            state.zones[ZoneKey(seat, ZoneRole.HAND)].add(register(state, card))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(defenders))
    session.submit(P1, DecisionResponse(("0",)))
    if their_terrain is not None:
        terrain_at(session.game, "old-ground", battlefield=0, owner=their_terrain)
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    return session


def _play_terrain(session: EngineSession, seat: PlayerId, card_id: str) -> None:
    session.act(seat, PlayStrategy(card_id))


def _fight_out(session: EngineSession) -> None:
    """Pass until the battle asks its first question after resolving, or moves on."""
    while session.game.pending is None and session.game.attack.current is not None:
        session.act(session.game.round.priority, Pass())


def _water_offered_to(session: EngineSession, seat: PlayerId) -> bool:
    pending = session.game.pending
    return isinstance(pending, Confirm) and pending.seat is seat


def test_ring_of_water_is_offered_after_playing_and_destroying_a_terrain_and_winning():
    session = _water_combat(
        held={P1: (_ring("water", "ring_of_water"), contentious_terrain("mine"))},
        their_terrain=P2,
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _fight_out(session)

    assert _water_offered_to(session, P1)
    session.submit(P1, DecisionResponse(("water",)))
    assert "water" in _in_play(session)


def test_ring_of_water_is_offered_to_a_defender_who_played_and_destroyed_a_terrain_and_won():
    session = _water_combat(
        raider_force=1,
        held={P2: (_ring("water", "ring_of_water", P2), contentious_terrain("theirs", owner=P2))},
        their_terrain=P1,
    )
    _play_terrain(session, P2, "theirs")
    _fight_out(session)

    assert _water_offered_to(session, P2)


def test_ring_of_water_is_offered_when_resolution_destroys_only_the_province():
    session = _water_combat(
        defenders=(),
        held={P1: (_ring("water", "ring_of_water"), contentious_terrain("mine"))},
        their_terrain=P2,
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _fight_out(session)

    outcome = session.game.attack.battlefields[0].outcome
    assert outcome.destroyed == () and outcome.province_destroyed
    assert _water_offered_to(session, P1)


def test_ring_of_water_is_offered_after_a_tie_that_destroyed_the_enemy_army():
    # Contentious Terrain's +1F brings the raider to 3 against the guard's 3. On a tie each side
    # destroys the other's army (CR, Battle Resolution), so P1 destroyed cards with no winner.
    session = _water_combat(
        raider_force=2,
        held={P1: (_ring("water", "ring_of_water"), contentious_terrain("mine"))},
        their_terrain=P2,
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _fight_out(session)

    assert session.game.attack.battlefields[0].outcome.winner is None
    assert _water_offered_to(session, P1)


def test_ring_of_water_is_not_offered_without_destroying_a_terrain():
    session = _water_combat(
        held={P1: (_ring("water", "ring_of_water"), contentious_terrain("mine"))}
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _fight_out(session)

    assert not _water_offered_to(session, P1)


def test_ring_of_water_is_not_offered_when_only_the_opponent_destroyed_a_terrain():
    # P1's Terrain enters on empty ground, then P2's destroys it. P1 still wins the battle.
    session = _water_combat(
        held={
            P1: (_ring("water", "ring_of_water"), contentious_terrain("mine")),
            P2: (contentious_terrain("theirs", owner=P2),),
        },
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _play_terrain(session, P2, "theirs")
    _fight_out(session)

    info = session.game.attack.battlefields[0]
    assert info.terrains_destroyed == frozenset({(P2, "mine")})
    assert not _water_offered_to(session, P1)


def test_ring_of_water_is_not_offered_when_resolution_destroyed_only_your_own_cards():
    # Contentious Terrain's +1F leaves the raider at 2 against the guard's 3, so the Defender wins.
    session = _water_combat(
        raider_force=1,
        held={P1: (_ring("water", "ring_of_water"), contentious_terrain("mine"))},
        their_terrain=P2,
    )
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    _fight_out(session)

    assert not _water_offered_to(session, P1)


def test_a_terrain_whose_entry_is_negated_still_counts_as_played():
    # Playing is putting the card into the resolution area (CR, Play), which happens whether or not
    # the Terrain's own effects are negated.
    negator = L5RCard.of(
        ActionPrint,
        id="negator",
        name="Negator",
        printed_id="negate_terrain_probe",
        side=Side.FATE,
        owner=P2,
        gold_cost=0,
    )
    session = _water_combat(held={P1: (contentious_terrain("mine"),), P2: (negator,)})
    session.act(P2, Pass())
    _play_terrain(session, P1, "mine")
    session.act(P2, PlayInterrupt("negator"))

    table = session.game.table
    assert not any(card.id == "mine" for card in table.battlefield.cards)
    assert session.game.attack.battlefields[0].terrains_played == frozenset({(P1, "mine")})


# --- Mirumoto Higashi ---


def _higashi_game() -> GameState:
    """Mirumoto Higashi in P1's play over a three-card Fate deck."""
    game = two_seat_game()
    put_in_play(game, personality("higashi", printed_id="mirumoto_higashi"))
    game.table.decks[DeckKey(P1, Side.FATE)].cards = [
        register(game.table, fate_card(f"deck{index}", P1)) for index in range(3)
    ]
    return game


def _enters_play(game: GameState, card: L5RCard) -> None:
    put_in_play(game, register(game.table, card))
    fire(game, EnteredPlay(card.id))


def _hand_size(game: GameState) -> int:
    return len(game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards)


def test_mirumoto_higashi_draws_once_per_turn_after_you_put_a_ring_into_play():
    game = _higashi_game()

    _enters_play(game, _ring("first", "generic_ring"))
    _enters_play(game, _ring("second", "generic_ring"))

    assert _hand_size(game) == 1


@pytest.mark.parametrize(
    "entering",
    [
        _ring("theirs", "generic_ring", P2),
        L5RCard.of(
            ActionPrint,
            id="way",
            printed_id="way_of_the_dragon_experienced",
            name="Way of the Dragon",
            side=Side.FATE,
            owner=P1,
        ),
    ],
    ids=["opponents_ring", "way_of_the_dragon"],
)
def test_mirumoto_higashi_ignores_what_is_not_your_ring_for_a_trait(entering):
    game = _higashi_game()

    _enters_play(game, entering)

    assert _hand_size(game) == 0


# --- Togashi's Library ---


def _library_game(*, clan: str = ruleset.DRAGON, top_focus: int = 2) -> EngineSession:
    """P1 a ``clan`` player with Togashi's Library and a 3C samurai in play, over a Fate deck whose
    top card has Focus Value ``top_focus``."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, clan=clan, gold_production=5))
    put_in_play(state, register(state, holding("library", printed_id="togashis_library")))
    put_in_play(state, register(state, personality("samurai", chi=3)))
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card("under", P1)),
        register(state, focus_card("top", P1, top_focus)),
    ]
    return EngineSession.start(state, P1)


@pytest.mark.parametrize(("clan", "offered"), [(ruleset.DRAGON, True), (ruleset.CRANE, False)])
def test_togashis_library_may_only_be_recruited_by_a_dragon_clan_player(clan, offered):
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, clan=clan, gold_production=5))
    province_card(state, "library", printed_id="togashis_library", gold_cost=2)
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)

    assert (ActivateAbility("library", RECRUIT) in session.legal_actions(P1)) is offered


@pytest.mark.parametrize(
    ("top_focus", "drawn"), [(2, True), (3, False)], ids=["focus_below_chi", "focus_at_chi"]
)
def test_togashis_library_draws_the_top_card_only_below_the_targets_chi(top_focus, drawn):
    session = _library_game(top_focus=top_focus)

    session.act(P1, ActivateAbility("library"))
    session.submit(P1, DecisionResponse(("samurai",)))

    hand = {card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards}
    deck = [card.id for card in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    assert ("top" in hand) is drawn
    assert deck == (["under"] if drawn else ["top", "under"])


# --- Hida Haikeru ---


def _haikeru_in_combat(*, rival_force: int, rival_chi: int) -> EngineSession:
    """The Combat Segment of P1's attack, Haikeru facing one enemy Personality whose Force and Chi
    are given, so a duel decided on the wrong stat picks the other winner."""
    cards = [
        personality("haikeru", printed_id="hida_haikeru", force=5, chi=2),
        personality("rival", owner=P2, force=rival_force, chi=rival_chi),
    ]
    return combat_segment(cards, {"haikeru": 0}, {"rival": 0})


def _duel_the_rival(session: EngineSession) -> EngineSession:
    """Take Haikeru's ability against the rival and carry the duel to its end."""
    session.act(P1, ActivateAbility("haikeru"))
    session.submit(P1, DecisionResponse(("rival",)))
    return session


def test_haikerus_duel_compares_force_and_bows_the_loser():
    # Chi is reversed against Force, so a duel decided on the arc's default stat gives the rival
    # the win and leaves it unbowed.
    session = _duel_the_rival(_haikeru_in_combat(rival_force=1, rival_chi=9))

    duel = session.game.duel
    assert duel.outcome.winners == (P1,)
    assert duel.outcome.totals == {P1: 5, P2: 1}
    assert session.game.table.cards_by_id["rival"].bowed


def test_haikeru_losing_his_own_duel_bows_nobody():
    # "Bow the target if they lose" is the only consequence the card carries, so a Haikeru who
    # loses leaves both Personalities standing.
    session = _duel_the_rival(_haikeru_in_combat(rival_force=9, rival_chi=1))

    duel = session.game.duel
    assert duel.outcome.losers == (P1,)
    assert not session.game.table.cards_by_id["rival"].bowed
    assert not session.game.table.cards_by_id["haikeru"].bowed


def test_a_tie_on_force_bows_the_target_because_both_personalities_lose():
    # A tie the Duelist tiebreak cannot separate is lost by both (CR, Duel), and the target losing
    # is what the card reads.
    session = _duel_the_rival(_haikeru_in_combat(rival_force=5, rival_chi=1))

    duel = session.game.duel
    assert duel.outcome.winners == ()
    assert set(duel.outcome.losers) == {P1, P2}
    assert session.game.table.cards_by_id["rival"].bowed


def test_haikerus_duel_stat_does_not_outlive_the_duel():
    # The override is scoped to the duel's end rather than the turn's, so a second duel between the
    # same Personalities compares the arc's default again.
    session = _duel_the_rival(_haikeru_in_combat(rival_force=1, rival_chi=9))

    assert named_duel_stat(session.game, "haikeru") is None
    assert named_duel_stat(session.game, "rival") is None


def test_haikeru_replays_to_the_same_board():
    session = _duel_the_rival(_haikeru_in_combat(rival_force=1, rival_chi=9))

    assert replay(session.log).table == session.game.table


# --- Hida War College (Experienced) ---


@pytest.mark.parametrize(("clan", "offered"), [(ruleset.CRAB, True), (ruleset.CRANE, False)])
def test_hida_war_college_may_only_be_recruited_by_a_crab_clan_player(clan, offered):
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, clan=clan, gold_production=5))
    province_card(state, "college", printed_id="hida_war_college_experienced", gold_cost=2)
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)

    assert (ActivateAbility("college", RECRUIT) in session.legal_actions(P1)) is offered


@pytest.mark.parametrize(
    ("p1_army", "p2_army", "p1_attacks", "force"),
    [
        ({"hero": 0}, {"guard": 0}, True, 5),
        ({"hero": 0}, {"guard": 0, "reserve": 0}, True, 7),
        ({"hero": 0}, {"guard": 0}, False, 7),
    ],
    ids=["attacking", "outnumbered", "defending"],
)
def test_hida_war_college_gives_more_force_to_a_defending_or_outnumbered_personality(
    p1_army, p2_army, p1_attacks, force
):
    cards = [
        holding("college", printed_id="hida_war_college_experienced"),
        personality("hero", force=3),
        personality("guard", owner=P2),
        personality("reserve", owner=P2),
    ]
    if p1_attacks:
        session = combat_segment(cards, p1_army, p2_army)
    else:
        session = combat_segment(cards, p2_army, p1_army, attacker=P2, defender_passes=False)

    session.act(P1, ActivateAbility("college"))
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["hero"]) == force
    assert game.table.cards_by_id["college"].bowed
    assert game.round.priority is P1 and game.round.passes == 0


# --- Hida Yurike, Soul of Hida Rikyu ---

YURIKE = "hida_yurike_soul_of_hida_rikyu"


def _yurike_battle() -> EngineSession:
    """Yurike (5F) with a Follower, against a 4F guard with a 1F Follower, whose unit totals as
    much as hers, and a 6F brute."""
    cards = [
        personality("yurike", printed_id=YURIKE, force=5),
        personality("guard", owner=P2, force=4),
        personality("brute", owner=P2, force=6),
    ]
    session = combat_segment(cards, {"yurike": 0}, {"guard": 0, "brute": 0})
    follower = AttachmentType.FOLLOWER
    attached(session.game, attachment("ashigaru", attachment_type=follower), "yurike")
    attached(
        session.game, attachment("spear", owner=P2, attachment_type=follower, force=1), "guard"
    )
    return session


def test_yurike_bows_a_unit_with_no_more_force_than_hers():
    session = _yurike_battle()

    session.act(P1, ActivateAbility("yurike", "bow"))
    assert session.game.pending.candidates == ("guard",)
    session.submit(P1, DecisionResponse(("guard",)))

    cards = session.game.table.cards_by_id
    assert cards["guard"].bowed and cards["spear"].bowed
    assert cards["yurike"].bowed


def test_yurike_bows_her_follower_to_straighten_herself():
    session = _yurike_battle()
    resolve_effects(session.game, [Bow("yurike")])

    session.act(P1, ActivateAbility("yurike", "straighten"))
    session.submit(P1, DecisionResponse(("ashigaru",)))

    cards = session.game.table.cards_by_id
    assert cards["ashigaru"].bowed
    assert not cards["yurike"].bowed


def test_yurike_stays_bowed_when_her_followers_bowing_is_negated():
    session = _yurike_battle()
    negation = Negation("guard", END_OF_TURN, effect_kind=Bow, subject_id="ashigaru")
    resolve_effects(session.game, [Bow("yurike"), GrantNegation(negation)])

    session.act(P1, ActivateAbility("yurike", "straighten"))
    session.submit(P1, DecisionResponse(("ashigaru",)))

    assert session.game.table.cards_by_id["yurike"].bowed


# --- Kaiu Denkaru ---


def _denkaru_battle(*, defending: bool) -> EngineSession:
    cards = [
        personality("denkaru", printed_id="kaiu_denkaru", force=4),
        personality("guard", owner=P2, force=4),
    ]
    if defending:
        return combat_segment(
            cards, {"guard": 0}, {"denkaru": 0}, attacker=P2, defender_passes=False
        )
    return combat_segment(cards, {"denkaru": 0}, {"guard": 0})


def test_an_attacking_denkaru_gives_an_enemy_minus_2_force():
    session = _denkaru_battle(defending=False)

    session.act(P1, ActivateAbility("denkaru"))
    assert session.game.pending.maximum == 1
    session.submit(P1, DecisionResponse((DENKARU_PENALTY,)))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["guard"]) == 2
    assert effective_force(game, game.table.cards_by_id["denkaru"]) == 4


def test_an_unopposed_denkaru_offers_nothing():
    cards = [
        personality("denkaru", printed_id="kaiu_denkaru", force=4),
        personality("guard", owner=P2, force=4),
    ]
    session = combat_segment(cards, {"denkaru": 0}, {"guard": 1})

    assert ActivateAbility("denkaru") not in session.legal_actions(P1)


def test_a_defending_denkaru_may_do_both():
    session = _denkaru_battle(defending=True)

    session.act(P1, ActivateAbility("denkaru"))
    session.submit(P1, DecisionResponse((DENKARU_BONUS, DENKARU_PENALTY)))
    session.submit(P1, DecisionResponse(("guard",)))

    game = session.game
    assert effective_force(game, game.table.cards_by_id["guard"]) == 2
    assert effective_force(game, game.table.cards_by_id["denkaru"]) == 6


# --- The Indomitable Fortress of the Crab ---

INDOMITABLE = "the_indomitable_fortress_of_the_crab"


def _indomitable_battle(
    *, flipped: bool = False, outnumbered: bool = False, wall: bool = True
) -> EngineSession:
    """P1's bowed hero, carrying a bowed Follower, opposed by one or two of P2's Personalities, with
    the Indomitable Fortress as P1's Stronghold and, by default, an unbowed Fortification."""
    cards = [
        flip_stronghold(INDOMITABLE, flipped=flipped),
        personality("hero"),
        personality("guard", owner=P2),
        personality("reserve", owner=P2),
    ]
    if wall:
        cards.append(holding("wall", keywords=(keywords.FORTIFICATION,)))
    enemies = {"guard": 0, "reserve": 0} if outnumbered else {"guard": 0}
    session = combat_segment(cards, {"hero": 0}, enemies)
    follower = attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER)
    attached(session.game, follower, "hero")
    resolve_effects(session.game, [Bow("hero"), Bow("ashigaru")])
    return session


@pytest.mark.parametrize("outnumbered", [False, True], ids=["even", "outnumbered"])
def test_the_indomitable_fortress_straightens_attachments_only_while_outnumbered(outnumbered):
    session = _indomitable_battle(outnumbered=outnumbered)

    session.act(P1, ActivateAbility("sh", "battle"))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert not cards["hero"].bowed
    assert cards["ashigaru"].bowed is not outnumbered


def test_a_bowed_indomitable_fortress_acts_by_bowing_your_fortification():
    session = _indomitable_battle()
    resolve_effects(session.game, [Bow("sh")])
    assert ActivateAbility("sh", "battle") not in session.legal_actions(P1)

    session.act(P1, ActivateAbility("sh", "battle_bowing_a_fortification"))
    session.submit(P1, DecisionResponse(("wall",)))
    session.submit(P1, DecisionResponse(("hero",)))

    cards = session.game.table.cards_by_id
    assert cards["wall"].bowed
    assert not cards["hero"].bowed


def test_the_indomitable_fortress_cannot_bow_for_tireless_without_an_unbowed_fortification():
    session = _indomitable_battle(wall=False)

    assert ActivateAbility("sh", "battle_bowing_a_fortification") not in session.legal_actions(P1)


def test_either_way_of_taking_the_indomitable_fortress_spends_its_one_use():
    session = _indomitable_battle()

    session.act(P1, ActivateAbility("sh", "battle"))
    session.submit(P1, DecisionResponse(("hero",)))
    session.act(P2, Pass())

    legal = session.legal_actions(P1)
    assert ActivateAbility("sh", "battle") not in legal
    assert ActivateAbility("sh", "battle_bowing_a_fortification") not in legal


def test_the_indomitable_fortress_back_is_tireless():
    session = _indomitable_battle(flipped=True)
    resolve_effects(session.game, [Bow("sh")])

    session.act(P1, ActivateAbility("sh"))
    session.submit(P1, DecisionResponse(("hero",)))

    assert not session.game.table.cards_by_id["hero"].bowed


@pytest.mark.parametrize(
    ("flipped", "face_up"), [(True, [True, False]), (False, [False, False])], ids=["back", "front"]
)
def test_the_indomitable_fortress_back_refills_face_up_after_the_first_fortification_only(
    flipped, face_up
):
    state = TableState.empty_two_seat()
    put_in_play(state, flip_stronghold(INDOMITABLE, flipped=flipped))
    put_in_play(state, holding("mine", gold_production=6))
    for index, wall in enumerate(("first-wall", "second-wall")):
        province_card(state, wall, keywords=(keywords.FORTIFICATION,), gold_cost=2, index=index)
    refills = [register(state, holding(f"refill-{n}")) for n in range(2)]
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = refills
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)

    for wall in ("first-wall", "second-wall"):
        session.act(P1, ActivateAbility(wall, RECRUIT))
        pay(session, P1)

    refilled = [
        session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)].cards[0].face_up
        for index in (0, 1)
    ]
    assert refilled == face_up


# --- Togashi Hiyoku ---


def _hiyoku_in_combat(*, rival_chi: int, hiyoku_chi: int = 4) -> EngineSession:
    """The Combat Segment of P1's attack, Hiyoku facing one enemy Personality.

    Neither carries Duelist: the builder takes the printed id for the handler lookup and not the
    printed keywords, so equal Chi is a tie the tiebreak cannot separate.
    """
    cards = [
        personality("hiyoku", printed_id="togashi_hiyoku", force=2, chi=hiyoku_chi),
        personality("rival", owner=P2, force=2, chi=rival_chi),
    ]
    return combat_segment(cards, {"hiyoku": 0}, {"rival": 0})


def _duel_with_hiyoku(session: EngineSession) -> EngineSession:
    session.act(P1, ActivateAbility("hiyoku"))
    session.submit(P1, DecisionResponse(("rival",)))
    return session


def test_hiyoku_winning_a_duel_in_battle_takes_a_token_and_the_follow_up():
    session = _duel_with_hiyoku(_hiyoku_in_combat(rival_chi=1))

    game = session.game
    assert game.table.cards_by_id["hiyoku"].counters[PLUS_1F_PLUS_1C.key] == 1
    assert game.pending is None
    assert (game.round.priority, game.round.granted_by) == (P1, "hiyoku")


def test_the_follow_up_goes_to_the_opponent_who_won():
    # "The winner may take an additional action" names the winner, not Hiyoku's controller, and the
    # challenged seat can be the one who won.
    session = _duel_with_hiyoku(_hiyoku_in_combat(rival_chi=9))

    game = session.game
    assert (game.round.priority, game.round.granted_by) == (P2, "hiyoku")
    assert game.additional_grant is None
    assert PLUS_1F_PLUS_1C.key not in game.table.cards_by_id["hiyoku"].counters


def test_declining_the_follow_up_hands_the_opportunity_on():
    session = _duel_with_hiyoku(_hiyoku_in_combat(rival_chi=1))

    session.act(P1, Pass())

    assert (session.game.round.priority, session.game.round.granted_by) == (P2, None)


def test_a_duel_neither_personality_wins_offers_nothing():
    # A tie the Duelist tiebreak cannot separate is lost by both, so there is no winner to ask.
    session = _duel_with_hiyoku(_hiyoku_in_combat(rival_chi=4))

    assert session.game.pending is None
    assert session.game.additional_grant is None
    assert PLUS_1F_PLUS_1C.key not in session.game.table.cards_by_id["hiyoku"].counters


def test_hiyoku_takes_no_token_for_a_duel_won_outside_a_battle():
    # "Wins a duel during battle" is the whole condition, and a duel can be fought with no attack
    # on at all.
    game = two_seat_game()
    put_in_play(game, personality("hiyoku", printed_id="togashi_hiyoku", chi=9))
    put_in_play(game, personality("rival", owner=P2, chi=1))

    declare_duel(game, challenger_duelist="hiyoku", challenged_duelist="rival", source="hiyoku")
    run_stack(game)

    assert game.duel.outcome.winners == (P1,)
    assert PLUS_1F_PLUS_1C.key not in game.table.cards_by_id["hiyoku"].counters


def test_hiyoku_takes_no_token_for_a_duel_he_is_not_in():
    # "Hiyoku wins a duel" is Hiyoku's own duel, and his seat winning another Personality's is not
    # the same thing.
    cards = [
        personality("hiyoku", printed_id="togashi_hiyoku", force=2, chi=4),
        personality("second", force=2, chi=9),
        personality("rival", owner=P2, force=2, chi=1),
    ]
    session = combat_segment(cards, {"hiyoku": 0, "second": 0}, {"rival": 0})

    declare_duel(
        session.game, challenger_duelist="second", challenged_duelist="rival", source="second"
    )
    run_stack(session.game)

    assert session.game.duel.outcome.winners == (P1,)
    assert PLUS_1F_PLUS_1C.key not in session.game.table.cards_by_id["hiyoku"].counters


def test_hiyoku_replays_to_the_same_board():
    session = _duel_with_hiyoku(_hiyoku_in_combat(rival_chi=1))
    session.act(P1, Pass())

    assert replay(session.log).table == session.game.table


# --- Tamori Tsushima ---


def _element_ring(card_id: str, element: Element) -> L5RCard:
    return L5RCard.of(
        RingPrint,
        id=card_id,
        name=card_id,
        printed_id=card_id,
        side=Side.FATE,
        owner=P1,
        element=element,
        keywords=(element.value,),
    )


def _tsushima_game(*, held: tuple[L5RCard, ...] = (), in_play: tuple[L5RCard, ...] = ()):
    """P1's Dynasty phase, with Tsushima face-up in P1's first Province, a Stronghold to Recruit him
    and a Holding to pay for his Response."""
    state = TableState.empty_two_seat()
    token_template(
        state,
        DRAGON_YOJIMBO,
        name="Dragon Yojimbo",
        card_type="Personality",
        keywords=("Samurai", "Yojimbo"),
        force=2,
        chi=2,
    )
    put_in_play(state, register(state, stronghold(P1, gold_production=3)))
    put_in_play(state, register(state, holding("mine", gold_production=3)))
    for card in in_play:
        put_in_play(state, register(state, card))
    for card in held:
        state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, card))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    tsushima = register(
        state, personality("tsushima", printed_id="tamori_tsushima", force=2, chi=2, gold_cost=3)
    )
    tsushima.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(tsushima)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    session.act(P1, ActivateAbility("tsushima", RECRUIT))
    pay(session, P1)
    return session


def _respond_with_tsushima(session: EngineSession) -> None:
    session.act(P1, ActivateAbility("tsushima"))
    pay(session, P1)


def test_tsushima_creates_and_recruits_a_yojimbo_without_further_cost():
    session = _tsushima_game()

    _respond_with_tsushima(session)

    (yojimbo,) = (card for card in session.game.table.battlefield.cards if card.is_token)
    assert yojimbo.name == "Dragon Yojimbo"
    assert EnteredPlay(yojimbo.id, recruited=True) in session.game.turn_events
    assert session.game.pending is None


def test_tsushima_with_a_ring_in_hand_may_still_create_the_yojimbo():
    session = _tsushima_game(held=(_element_ring("void", Element.VOID),))

    _respond_with_tsushima(session)
    session.submit(P1, DecisionResponse((TAMORI_TSUSHIMA_CREATE,)))

    assert any(card.is_token for card in session.game.table.battlefield.cards)
    assert "void" not in _in_play(session)


def test_a_ring_tsushima_puts_into_play_does_not_count_towards_enlightenment():
    others = (Element.AIR, Element.EARTH, Element.FIRE, Element.WATER)
    session = _tsushima_game(
        held=(_element_ring("void", Element.VOID),),
        in_play=tuple(_element_ring(element.value, element) for element in others),
    )

    _respond_with_tsushima(session)
    session.submit(P1, DecisionResponse(("void",)))

    assert "void" in _in_play(session)
    assert session.game.game_over is False


def test_tsushima_offers_his_rings_and_his_yojimbo_as_one_question():
    session = _tsushima_game(held=(_element_ring("void", Element.VOID),))

    _respond_with_tsushima(session)

    pending = session.game.pending
    assert pending.candidates == ("void",)
    assert pending.options == (TAMORI_TSUSHIMA_CREATE,)
    assert pending.prompt() == "Pick a Ring to put into play"
    # What words the Ring's own entry, since one click is the whole answer and nothing is confirmed.
    assert pending.pick_label == (
        "Put this Ring into play, it does not count towards an Enlightenment Victory"
    )


# --- Daigotsu Rin ---


def test_rin_puts_an_undead_follower_from_the_fate_deck_into_the_discard_pile():
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, gold_production=4)))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, attachment(card_id, attachment_type=attachment_type, keywords=carried))
        for card_id, attachment_type, carried in (
            ("zombie", AttachmentType.FOLLOWER, ("Undead",)),
            ("ashigaru", AttachmentType.FOLLOWER, ()),
            ("bone_blade", AttachmentType.ITEM, ("Undead",)),
        )
    ]
    rin = register(state, personality("rin", printed_id="daigotsu_rin", force=3, gold_cost=4))
    rin.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(rin)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    session.act(P1, ActivateAbility("rin", RECRUIT))
    pay(session, P1)

    session.act(P1, ActivateAbility("rin"))
    assert session.game.pending.candidates == ("zombie",)
    session.submit(P1, DecisionResponse(("zombie",)))

    table = session.game.table
    assert [card.id for card in table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards] == ["zombie"]
    assert {card.id for card in table.decks[DeckKey(P1, Side.FATE)].cards} == {
        "ashigaru",
        "bone_blade",
    }
