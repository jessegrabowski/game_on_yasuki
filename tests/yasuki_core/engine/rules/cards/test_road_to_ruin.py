import pytest

from yasuki_core.engine.rules.rulebook.recruit import RECRUIT
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import Location, TableState, DeckKey, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Equip,
    Pass,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.board.queries import attack_targets
from yasuki_core.engine.rules.cards.road_to_ruin import UNITY_CHI, UNITY_FORCE
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.cards.road_to_ruin import (
    FORGOTTEN_DEAD,
    UNICORN_EXPEDITION_FOLLOW_UP,
    UNICORN_EXPEDITION_STRAIGHTEN,
)
from yasuki_core.engine.rules.effects import (
    AttachCard,
    Bow,
    DelayStraighten,
    Destroy,
    Dishonor,
    MeleeAttack,
    Move,
)
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed, Straightened
from yasuki_core.engine.rules.vocabulary.decisions import (
    DecisionResponse,
)
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Negation
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import MINUS_1F
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, HoldingPrint, RingPrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    end_phase,
    end_turn,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    sensei,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1
P2 = PlayerId.P2


def _ruins_game(*, in_deck=("mine",), in_discard=(), in_play=(), unique=()):
    """A session with P1's Repairing the Ruins face-up in a Province, and Holdings salted
    through the zones it searches. Ids double as printed ids, so a card in play blocks the
    copy of itself."""
    state = TableState.empty_two_seat()
    province_card(state, "ruins", printed_id="repairing_the_ruins")

    def a_holding(card_id):
        if card_id in unique:
            return L5RCard.of(
                HoldingPrint,
                id=card_id,
                name=card_id,
                side=Side.DYNASTY,
                owner=P1,
                printed_id=card_id,
                is_unique=True,
            )
        return holding(card_id, printed_id=card_id, gold_production=3, gold_cost=2)

    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, a_holding(card_id)) for card_id in in_deck
    ]
    discard = state.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    for card_id in in_discard:
        discard.add(register(state, a_holding(card_id)))
    for card_id in in_play:
        put_in_play(state, a_holding(card_id))
    return EngineSession.start(state, P1)


def test_repairing_the_ruins_is_offered_from_its_province():
    """The card acts from the Province it sits face-up in, and never enters play."""
    session = _ruins_game()
    assert ActivateAbility("ruins") in session.legal_actions(P1)


def test_it_searches_the_dynasty_deck_and_the_discard_pile():
    session = _ruins_game(in_deck=("mine",), in_discard=("kobune",))
    session.act(P1, ActivateAbility("ruins"))

    assert set(session.game.pending.candidates) == {"mine", "kobune"}


def test_it_rebuilds_its_own_province_with_the_holding_it_finds():
    session = _ruins_game()
    session.act(P1, ActivateAbility("ruins"))
    session.submit(P1, DecisionResponse(("mine",)))

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]

    assert [card.id for card in province.cards] == ["mine"]
    assert session.game.table.cards_by_id["mine"].face_up
    assert "ruins" in {card.id for card in discard.cards}


def test_a_different_holding_in_play_blocks_nothing():
    """'...of which you do not control any copies.' Control is judged per printed id, so an
    unrelated Holding in play leaves the deck's copy findable."""
    session = _ruins_game(in_deck=("mine",), in_play=("mine_copy",))
    session.act(P1, ActivateAbility("ruins"))
    assert set(session.game.pending.candidates) == {"mine"}


def test_it_will_not_find_a_holding_a_copy_of_which_is_in_play():
    session = _ruins_game(in_deck=("mine",), in_play=("mine",))
    assert ActivateAbility("ruins") not in session.legal_actions(P1)


def test_it_will_not_find_a_unique_holding():
    session = _ruins_game(in_deck=("mine",), unique=("mine",))
    assert ActivateAbility("ruins") not in session.legal_actions(P1)


def test_it_is_not_offered_with_nothing_left_to_find():
    """An ability with no legal target is never offered, so the Event is not spent for nothing."""
    session = _ruins_game(in_deck=())
    assert ActivateAbility("ruins") not in session.legal_actions(P1)


def test_rebuilding_a_province_replays_to_the_same_state():
    session = _ruins_game()
    session.act(P1, ActivateAbility("ruins"))
    session.submit(P1, DecisionResponse(("mine",)))
    assert replay(session.log) == session.game


def test_a_holding_pulled_from_the_deck_is_permanently_dearer():
    """'...and permanently give it +1 Gold Cost if it was not from your discard pile.'"""
    session = _ruins_game(in_deck=("mine",))
    session.act(P1, ActivateAbility("ruins"))
    session.submit(P1, DecisionResponse(("mine",)))

    mine = session.game.table.cards_by_id["mine"]
    assert mine.gold_cost == 2  # printed, untouched
    assert effective_gold_cost(session.game, mine) == 3


@pytest.mark.parametrize("chosen, cost", [("mine", 3), ("kobune", 2)])
def test_the_rider_follows_the_chosen_cards_own_zone(chosen, cost):
    """Both zones are stocked, so reading "is the discard pile empty" rather than "is this card in
    it" would price the two the same."""
    session = _ruins_game(in_deck=("mine",), in_discard=("kobune",))
    session.act(P1, ActivateAbility("ruins"))
    session.submit(P1, DecisionResponse((chosen,)))

    assert effective_gold_cost(session.game, session.game.table.cards_by_id[chosen]) == cost


def test_the_rebuilt_holding_still_has_to_be_recruited_at_the_dearer_price():
    """The Holding lands face-up in the Province, not in play, so the rider is what the seat
    pays."""
    session = _ruins_game(in_deck=("mine",))
    session.act(P1, ActivateAbility("ruins"))
    session.submit(P1, DecisionResponse(("mine",)))

    assert recruit_cost(session.game, session.game.table.cards_by_id["mine"]) == 3


def _outlying_game(*, target_cost=2, with_producer=True):
    """A Dynasty-phase session with P1's Outlying Farms (gp 2) in play, an optional 8-gold producer,
    and a face-up target Holding in a province to recruit."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(
                HoldingPrint,
                id="refill",
                printed_id="refill",
                name="R",
                side=Side.DYNASTY,
                owner=P1,
            ),
        )
    ]
    if with_producer:
        put_in_play(
            state,
            L5RCard.of(
                HoldingPrint,
                id="sh",
                printed_id="sh",
                name="SH",
                side=Side.DYNASTY,
                owner=P1,
                gold_production=8,
            ),
        )
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="of",
            name="Outlying Farms",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="outlying_farms",
            keywords=("Farm",),
            gold_production=2,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="plain_holding",
            gold_cost=target_cost,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)  # Action phase
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def _recruited(session, card_id):
    return session.game.table.cards_by_id[card_id] in session.game.table.battlefield.cards


def _in_dynasty_discard(session, card_id):
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    return card_id in {c.id for c in discard.cards}


def test_the_payment_quotes_outlying_farms_at_its_plain_yield_and_its_ceiling():
    """The payment carries the extra separately from what the Farm makes now, because the seat has
    not been asked yet. The question comes in the window, as it bows."""
    session = _outlying_game()
    session.act(P1, ActivateAbility("target", RECRUIT))

    pending = session.game.pending
    assert dict(pending.produced)["of"] == 2
    assert pending.grantable == (("of", 2),)


def test_bowing_outlying_farms_opens_its_window_before_the_yield_is_read():
    session = _outlying_game(with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))

    session.submit(P1, DecisionResponse(("of",)))

    pending = session.game.pending
    assert pending.question == ("Give Outlying Farms +2GP? It is destroyed after it bows.")
    assert pending.candidates == ("of",)
    assert not session.game.table.cards_by_id["of"].bowed  # the yield is still unread


def test_a_grant_the_payment_cannot_do_without_refuses_no_as_an_answer():
    """Affordability counted the grant to offer the recruit, so announcing it commits the seat. The
    question stops saying no is an option, leaving cancelling as the way out."""
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))

    pending = session.game.pending
    assert not pending.accepts(DecisionResponse(()))
    assert pending.accepts(DecisionResponse(("of",)))
    assert pending.cancellable


def test_a_grant_the_payment_does_not_need_can_still_be_declined():
    """Nothing is committed when another producer covers the cost, so the Farm's window is the plain
    optional question the card prints."""
    session = _outlying_game(target_cost=10)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))

    assert session.game.pending.accepts(DecisionResponse(()))


def test_backing_out_at_the_window_leaves_the_board_as_it_was():
    """The seat announced a Recruit and only then learned the price was the Farm. Cancelling has to
    put back everything the announcement moved, not just the question."""
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))

    session.cancel(P1)

    of = session.game.table.cards_by_id["of"]
    assert of in session.game.table.battlefield.cards and not of.bowed
    assert not _recruited(session, "target")
    assert session.game.table.cards_by_id["target"].face_up  # still on offer in its province
    assert session.game.pending is None
    assert session.game.gold[P1] == 0


def test_the_grant_makes_the_extra_gold_needed_to_afford_a_recruit():
    # The whole point: Outlying Farms alone (base 2) covers a cost-4 recruit only if it grants
    # itself. The recruit is offered, bowing it opens the window, and yes pays and destroys it.
    session = _outlying_game(target_cost=4, with_producer=False)
    assert ActivateAbility("target", RECRUIT) in session.legal_actions(P1)

    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(("of",)))  # yes

    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")  # destroyed after bowing granted
    assert session.game.gold[P1] == 0


def test_the_grant_is_banked_and_outlying_farms_destroyed_even_when_unneeded():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(("of",)))  # yes, though 2 already covers

    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")
    assert session.game.gold[P1] == 2  # 4 produced, 2 spent, 2 excess banked


def test_declining_bows_outlying_farms_for_its_plain_yield():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(()))  # no

    assert _recruited(session, "target")
    of = session.game.table.cards_by_id["of"]
    assert of in session.game.table.battlefield.cards and of.bowed  # bowed, not destroyed
    assert session.game.gold[P1] == 0


def test_the_price_is_not_paid_by_a_farm_that_was_never_asked():
    """The destruction is the price of the grant, not of bowing. A Farm bowed while some other
    producer covers the cost keeps its window, answers no, and lives."""
    session = _outlying_game(target_cost=10)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(()))  # no
    session.submit(P1, DecisionResponse(("sh",)))

    assert _recruited(session, "target")
    assert not _in_dynasty_discard(session, "of")


def test_the_outlying_farms_grant_replays_to_the_same_state():
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, ActivateAbility("target", RECRUIT))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(("of",)))
    assert replay(session.log) == session.game


# --- Dull Tanto ---


def _tanto_game(*, target_owner=P1):
    """P1's Dull Tanto attached to his own Personality, with a second Personality to target."""
    game = two_seat_game()
    put_in_play(game, personality("bearer", force=3, chi=3))
    put_in_play(game, personality("victim", force=4, chi=3, owner=target_owner))
    attached(game, attachment("tanto", printed_id="dull_tanto", keywords=("Weapon",)), "bearer")
    return EngineSession.start(game.table, P1)


def test_dull_tanto_gives_the_target_two_minus_one_force_tokens():
    session = _tanto_game(target_owner=PlayerId.P2)

    session.act(P1, ActivateAbility("tanto"))
    session.submit(P1, DecisionResponse(("victim",)))

    victim = session.game.table.cards_by_id["victim"]
    assert victim.counters[MINUS_1F.key] == 2
    assert effective_force(session.game, victim) == 2  # printed 4, two -1F tokens
    assert session.game.table.cards_by_id["tanto"] not in session.game.table.battlefield.cards


def test_dull_tanto_may_target_its_own_bearer():
    """The card says "a target Personality" and narrows it no further, so the Personality carrying
    the Item is a legal target."""
    session = _tanto_game()

    assert ActivateAbility("tanto") in session.legal_actions(P1)
    session.act(P1, ActivateAbility("tanto"))

    assert "bearer" in session.project(P1).pending.candidates


def test_dull_tanto_does_not_bow_the_personality_carrying_it():
    """Its cost is nothing at all: destroying the Item is an effect the ability emits, not a price
    paid to announce it."""
    session = _tanto_game(target_owner=PlayerId.P2)

    session.act(P1, ActivateAbility("tanto"))
    session.submit(P1, DecisionResponse(("victim",)))

    assert session.game.table.cards_by_id["bearer"].bowed is False


# --- The Forgotten ---


def _forgotten_game(*, bearers=("bearer",)):
    """The Forgotten waiting in hand, with ``bearers`` Personalities to carry what it raises."""
    game = two_seat_game()
    token_template(
        game,
        FORGOTTEN_DEAD,
        name="Forgotten Dead",
        card_type="Follower",
        keywords=("Nonhuman", "Shadowlands", "Undead"),
        force=1,
    )
    for card_id in bearers:
        put_in_play(game, personality(card_id, force=2, chi=3))
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, attachment("forgotten", printed_id="the_forgotten", force=1)))
    return game


def _dead_of(game):
    return [card for card in game.table.battlefield.cards if card.is_token]


def test_the_forgotten_raises_another_of_the_dead_as_it_arrives():
    game = _forgotten_game()

    resolve_effects(game, [AttachCard("forgotten", "bearer")])
    submit(game, DecisionResponse(("bearer",)))

    assert [card.name for card in _dead_of(game)] == ["Forgotten Dead"]
    assert game.table.seats[PlayerId.P1].honor == -2


def test_the_forgotten_raises_another_when_it_falls():
    """The half that needs a card to hear its own destruction announced from the discard pile."""
    game = _forgotten_game(bearers=("bearer", "spare"))
    resolve_effects(game, [AttachCard("forgotten", "bearer")])
    submit(game, DecisionResponse(("bearer",)))

    resolve_effects(game, [Destroy("forgotten", PlayerId.P1)])
    submit(game, DecisionResponse(("spare",)))

    assert len(_dead_of(game)) == 2  # one for the arrival, one for the fall
    assert game.table.seats[PlayerId.P1].honor == -4


def test_the_forgotten_pays_the_honor_even_with_nobody_left_to_carry_them():
    """It charges before it asks for a target, so a board with no Personality still costs 2."""
    game = _forgotten_game(bearers=())
    put_in_play(game, personality("doomed", force=2, chi=3))
    resolve_effects(game, [AttachCard("forgotten", "doomed")])
    submit(game, DecisionResponse(("doomed",)))

    resolve_effects(game, [Destroy("doomed", PlayerId.P1)])  # the unit goes down together

    assert game.table.seats[PlayerId.P1].honor == -4
    assert game.pending is None  # nobody was asked, because nobody was left


def test_another_follower_falling_raises_nothing():
    game = _forgotten_game()
    resolve_effects(game, [AttachCard("forgotten", "bearer")])
    submit(game, DecisionResponse(("bearer",)))
    spear = register(game.table, attachment("spear", force=1))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(spear)
    resolve_effects(game, [AttachCard("spear", "bearer")])

    resolve_effects(game, [Destroy("spear", PlayerId.P1)])

    assert len(_dead_of(game)) == 1
    assert game.table.seats[PlayerId.P1].honor == -2


# --- Verdant Wilds ---


def _wilds_game():
    """P1's Verdant Wilds unbowed, with a bowed Holding of its own seat's and one of P2's to
    aim at."""
    game = two_seat_game()
    put_in_play(game, holding("wilds", owner=P1, printed_id="verdant_wilds", gold_production=5))
    session = EngineSession.start(game.table, P1)
    # Bowed after the turn opens: its straighten step would stand them back up.
    put_in_play(session.game, holding("mine", owner=P1)).bow()
    put_in_play(session.game, holding("theirs", owner=PlayerId.P2)).bow()
    return session


def test_verdant_wilds_aims_only_at_its_own_seats_bowed_cards():
    """ "Your target card" is one this seat owns, and straightening presupposes a bowed one. The
    Wilds is not on its own list: it bows to pay, so straightening itself would undo the cost."""
    session = _wilds_game()

    session.act(P1, ActivateAbility("wilds"))

    assert session.project(P1).pending.candidates == ("mine",)


def test_verdant_wilds_straightens_the_card_it_targets():
    session = _wilds_game()

    session.act(P1, ActivateAbility("wilds"))
    session.submit(P1, DecisionResponse(("mine",)))

    assert not session.game.table.cards_by_id["mine"].bowed
    assert session.game.table.cards_by_id["wilds"].bowed  # it paid its own bow


def test_verdant_wilds_cannot_straighten_a_card_forbidden_to_straighten():
    """A granted Jade Mine may not straighten until after its next Action Phase, and an ability that
    would straighten it finds it immovable. Failing to move it does not lift the prohibition, and it
    stays a legal target. The ban belongs to the Mine, not to whatever aims at it."""
    session = _wilds_game()
    resolve_effects(session.game, [DelayStraighten("mine")])

    session.act(P1, ActivateAbility("wilds"))
    assert session.project(P1).pending.candidates == ("mine",)
    session.submit(P1, DecisionResponse(("mine",)))

    assert session.game.table.cards_by_id["mine"].bowed
    assert "mine" in session.game.straighten_delayed


# --- "Is That All?" ---

TRINKET_PROBE = "probe_trinket"


def _is_that_all_battle(*, guard_force: int = 3, guard_follower: bool = False) -> EngineSession:
    """P1's bowed 4F hero facing P2's guard, with "Is That All?" in P1's hand."""
    is_that_all = L5RCard.of(
        ActionPrint,
        id="is-that-all",
        printed_id="is_that_all",
        name='"Is That All?"',
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    cards = [personality("hero", force=4), personality("guard", owner=P2, force=guard_force)]
    session = combat_segment(cards, {"hero": 0}, {"guard": 0}, in_hand=[is_that_all])
    if guard_follower:
        follower = attachment("ashigaru", owner=P2, attachment_type=AttachmentType.FOLLOWER)
        attached(session.game, follower, "guard")
    resolve_effects(session.game, [Bow("hero")])
    return session


@pytest.mark.parametrize(
    ("guard_force", "guard_follower", "feared", "bowed", "straightened"),
    [
        (3, False, "guard", True, True),
        (5, False, "guard", False, False),
        (3, True, "ashigaru", True, False),
    ],
    ids=["bows_a_personality", "too_strong", "bows_a_follower"],
)
def test_is_that_all_straightens_your_personality_only_after_bowing_an_enemy_personality(
    guard_force, guard_follower, feared, bowed, straightened
):
    session = _is_that_all_battle(guard_force=guard_force, guard_follower=guard_follower)

    session.act(P1, PlayStrategy("is-that-all", "fear"))
    session.submit(P1, DecisionResponse(("hero",)))
    session.submit(P1, DecisionResponse((feared,)))

    cards = session.game.table.cards_by_id
    assert cards[feared].bowed is bowed
    assert cards["hero"].bowed is not straightened


def _trinket_used(gold_cost: int) -> EngineSession:
    """The "Is That All?" battle once P1 has used the ability of a trinket costing ``gold_cost``
    attached to the hero, so its Response Step is open."""
    session = _is_that_all_battle()
    trinket = attachment("trinket", printed_id=TRINKET_PROBE, gold_cost=gold_cost)
    attached(session.game, trinket, "hero")
    session.act(P1, ActivateAbility("trinket"))
    return session


TRINKET_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    cost=no_cost,
    targets=itself,
    effects=lambda game, source, target: [],
    hits_every_target=True,
)


def test_is_that_all_destroys_the_zero_cost_attachment_whose_action_it_answers():
    with probe_ability(TRINKET_PROBE, TRINKET_ABILITY):
        session = _trinket_used(gold_cost=0)

        session.act(P1, PlayStrategy("is-that-all", "destroy"))

    assert "trinket" not in {card.id for card in session.game.table.battlefield.cards}


def test_is_that_all_does_not_answer_an_attachment_costing_gold():
    with probe_ability(TRINKET_PROBE, TRINKET_ABILITY):
        session = _trinket_used(gold_cost=1)

        assert PlayStrategy("is-that-all", "destroy") not in session.legal_actions(P1)


# --- Kakita Harudei, Drunkard ---


def _harudei_in_battle(*, guard_chi: int = 2, compassion: bool = False) -> EngineSession:
    """P1 attacks with Harudei (Chi 3). P2 defends with a guard of ``guard_chi`` and a sage of
    Chi 4. With ``compassion``, P2 holds a second Province, so P1 has fewer."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    if compassion:
        province_card(state, "def-prov1", seat=PlayerId.P2, index=1)
    put_in_play(state, personality("harudei", printed_id="kakita_harudei_drunkard", chi=3))
    put_in_play(state, personality("guard", owner=PlayerId.P2, chi=guard_chi))
    put_in_play(state, personality("sage", owner=PlayerId.P2, chi=4))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("harudei@0",)))
    session.submit(PlayerId.P2, DecisionResponse(("guard@0", "sage@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(PlayerId.P2, Pass())
    return session


def test_harudei_bows_an_opposed_personality_with_lower_chi():
    session = _harudei_in_battle()

    session.act(P1, ActivateAbility("harudei"))
    assert session.game.pending.candidates == ("guard",)
    session.submit(P1, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed is True
    assert session.game.table.cards_by_id["harudei"].bowed is False


def test_harudei_is_withheld_when_no_opposed_personality_has_lower_chi():
    session = _harudei_in_battle(guard_chi=3)  # equal Chi is not lower

    assert ActivateAbility("harudei") not in session.legal_actions(P1)


@pytest.mark.parametrize(("compassion", "again"), [(True, True), (False, False)])
def test_harudei_may_act_a_second_time_in_a_turn_only_with_compassion(compassion, again):
    session = _harudei_in_battle(compassion=compassion)
    session.act(P1, ActivateAbility("harudei"))
    session.submit(P1, DecisionResponse(("guard",)))

    session.act(PlayerId.P2, Pass())

    assert (ActivateAbility("harudei") in session.legal_actions(P1)) is again


def test_harudei_acts_no_third_time_with_compassion():
    session = _harudei_in_battle(compassion=True)
    for _ in range(2):
        session.act(P1, ActivateAbility("harudei"))
        session.submit(P1, DecisionResponse(("guard",)))
        session.act(PlayerId.P2, Pass())

    assert ActivateAbility("harudei") not in session.legal_actions(P1)


# --- Unity of Spirit ---

MELEE_PROBE = "probe_battle_melee_5"
MELEE_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: Melee 5 Attack",
    cost=no_cost,
    targets=attack_targets,
    effects=lambda game, source, target: [MeleeAttack(5, target.id, source.owner)],
)


def _unity_battle(*, yojimbo: bool = True, courtier: bool = True) -> EngineSession:
    """The Combat Segment of P1's attack, the Defender holding the opportunity. P1's raider has a
    Melee probe. P2 defends with kakita, a Yojimbo unless told otherwise, keeps a Courtier home
    unless told otherwise, and holds Unity of Spirit."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    put_in_play(state, personality("raider", printed_id=MELEE_PROBE, force=3))
    kakita_keywords = (keywords.YOJIMBO,) if yojimbo else ()
    put_in_play(state, personality("kakita", owner=PlayerId.P2, force=2, keywords=kakita_keywords))
    if courtier:
        put_in_play(
            state, personality("courtier", owner=PlayerId.P2, keywords=(keywords.COURTIER,))
        )
    state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="unity",
                name="Unity of Spirit",
                printed_id="unity_of_spirit",
                side=Side.FATE,
                owner=PlayerId.P2,
                gold_cost=0,
            ),
        )
    )
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(PlayerId.P2, DecisionResponse(("kakita@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    return session


def test_unity_of_spirit_straightens_an_opposed_yojimbo_and_grants_the_chosen_bonus():
    with probe_ability(MELEE_PROBE, MELEE_ABILITY):
        session = _unity_battle()
        session.game.table.cards_by_id["kakita"].bow()

        session.act(PlayerId.P2, PlayStrategy("unity"))
        assert session.game.pending.candidates == ("kakita",)
        session.submit(PlayerId.P2, DecisionResponse(("kakita",)))
        assert session.game.pending.candidates == (UNITY_FORCE, UNITY_CHI)
        session.submit(PlayerId.P2, DecisionResponse((UNITY_CHI,)))

        kakita = session.game.table.cards_by_id["kakita"]
        assert kakita.bowed is False
        assert effective_chi(session.game, kakita) == 5


def test_unity_of_spirit_offers_no_bonus_to_a_personality_who_is_not_a_yojimbo():
    with probe_ability(MELEE_PROBE, MELEE_ABILITY):
        session = _unity_battle(yojimbo=False)
        session.game.table.cards_by_id["kakita"].bow()

        session.act(PlayerId.P2, PlayStrategy("unity"))
        session.submit(PlayerId.P2, DecisionResponse(("kakita",)))

        assert session.game.table.cards_by_id["kakita"].bowed is False
        assert session.game.pending is None
        discard = session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.FATE_DISCARD)]
        assert [card.id for card in discard.cards] == ["unity"]


def test_unity_of_spirit_negates_a_melee_attack_on_the_yojimbo():
    with probe_ability(MELEE_PROBE, MELEE_ABILITY):
        session = _unity_battle()
        session.act(PlayerId.P2, Pass())
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("kakita",)))
        assert session.game.round.kind is RoundKind.INTERRUPT
        assert PlayInterrupt("unity") in session.legal_actions(PlayerId.P2)

        session.act(PlayerId.P2, PlayInterrupt("unity"))

        assert "kakita" in [card.id for card in session.game.table.battlefield.cards]


def test_unity_of_spirit_is_not_offered_without_a_courtier_or_shugenja():
    with probe_ability(MELEE_PROBE, MELEE_ABILITY):
        session = _unity_battle(courtier=False)
        session.act(PlayerId.P2, Pass())
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("kakita",)))

        assert session.game.round.kind is not RoundKind.INTERRUPT
        assert "kakita" not in [card.id for card in session.game.table.battlefield.cards]


def test_unity_of_spirit_is_not_offered_against_a_personality_who_is_not_a_yojimbo():
    with probe_ability(MELEE_PROBE, MELEE_ABILITY):
        session = _unity_battle(yojimbo=False)
        session.act(PlayerId.P2, Pass())
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("kakita",)))

        assert session.game.round.kind is not RoundKind.INTERRUPT
        assert "kakita" not in [card.id for card in session.game.table.battlefield.cards]


# --- Kitsune Rumiko ---


def test_rumiko_commits_seppuku_when_dishonored():
    game = two_seat_game()
    rumiko = put_in_play(game, personality("rumiko", printed_id="kitsune_rumiko", personal_honor=3))

    resolve_effects(game, [Dishonor(rumiko.id, PlayerId.P2)])
    run_stack(game)

    # Rehonored before the destruction, so her printed Personal Honor is not lost (CR, Seppuku).
    assert rumiko in game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert not rumiko.dishonorable
    assert game.table.seats[P1].honor == 0


def _rumiko_session(*, beiko: bool = False, compassion: bool = False) -> EngineSession:
    """With ``compassion``, P2 holds a Province and P1 none, so P1 has fewer."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("rumiko", printed_id="kitsune_rumiko"))
    if beiko:
        put_in_play(state, sensei(P1, printed_id="beiko_sensei"))
    if compassion:
        province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    return EngineSession.start(state, P1)


def test_rumiko_bows_to_gain_an_honor_on_her_controllers_turn():
    session = _rumiko_session()

    session.act(P1, ActivateAbility("rumiko"))

    assert session.game.table.seats[P1].honor == 1
    assert session.game.table.cards_by_id["rumiko"].bowed


def test_rumiko_stays_unbowed_with_compassion():
    session = _rumiko_session(compassion=True)

    session.act(P1, ActivateAbility("rumiko"))

    assert session.game.table.seats[P1].honor == 1
    assert not session.game.table.cards_by_id["rumiko"].bowed


def test_rumiko_gains_two_with_beiko_sensei():
    session = _rumiko_session(beiko=True)

    session.act(P1, ActivateAbility("rumiko"))

    assert session.game.table.seats[P1].honor == 2


def test_rumiko_is_withheld_on_the_other_seats_turn():
    session = _rumiko_session()
    end_turn(session)
    session.act(PlayerId.P2, Pass())

    assert session.game.round.priority is P1
    assert ActivateAbility("rumiko") not in session.legal_actions(P1)


# --- Tao Defenders ---


def _tao_defenders(*, owner=P1):
    return attachment(
        "defenders",
        owner=owner,
        printed_id="tao_defenders",
        attachment_type=AttachmentType.FOLLOWER,
        force=2,
        gold_cost=4,
        keywords=("Monk",),
    )


def _ring(card_id, *, ring_keywords=()):
    return L5RCard.of(
        RingPrint,
        id=card_id,
        printed_id=card_id,
        name=card_id,
        side=Side.FATE,
        owner=P1,
        keywords=ring_keywords,
    )


def test_tao_defenders_return_a_non_shadowlands_ring_to_hand_and_are_destroyed():
    # Way of the Dragon counts as a Ring for actions wherever it is.
    state = TableState.empty_two_seat()
    put_in_play(state, personality("hero"))
    attached(state, _tao_defenders(), "hero")
    discard = state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    discard.add(register(state, _ring("ring_of_water")))
    discard.add(register(state, _ring("dark_ring", ring_keywords=(keywords.SHADOWLANDS,))))
    discard.add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="way",
                printed_id="way_of_the_dragon_experienced",
                name="Way of the Dragon",
                side=Side.FATE,
                owner=P1,
            ),
        )
    )
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("defenders"))
    assert session.game.pending.candidates == ("ring_of_water", "way")
    session.submit(P1, DecisionResponse(("ring_of_water",)))

    zones = session.game.table.zones
    assert [card.id for card in zones[ZoneKey(P1, ZoneRole.HAND)].cards] == ["ring_of_water"]
    assert "defenders" in {card.id for card in zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards}


@pytest.mark.parametrize(
    ("p1_provinces", "offered"), [(3, True), (4, False)], ids=["compassion", "no_compassion"]
)
def test_tao_defenders_may_be_equipped_from_the_discard_pile_with_compassion(p1_provinces, offered):
    state = TableState.empty_two_seat()
    put_in_play(state, personality("hero"))
    put_in_play(state, holding("mine", gold_production=4))
    for seat, count in ((P1, p1_provinces), (PlayerId.P2, 4)):
        for index in range(count):
            state.zones[ZoneKey(seat, ZoneRole.PROVINCE, index)] = ProvinceZone(owner=seat)
    state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(register(state, _tao_defenders()))
    session = EngineSession.start(state, P1)

    assert (Equip("defenders") in session.legal_actions(P1)) is offered


# --- The Unicorn Expedition ---


def _horse_ability(game, source, target):
    return []


HORSE_ACTION = ActivateAbility("horse", "probe")


@pytest.fixture
def expedition():
    """The Combat Segment, with P1's bowed rider at home carrying a bowed horse, P1's vanguard
    carrying a scout at the battlefield against P2's guard, gold for any Invest, and The Unicorn
    Expedition in P1's hand. The horse and the scout each have a Battle ability."""
    strategy = L5RCard.of(
        FatePrint,
        id="expedition",
        name="The Unicorn Expedition",
        printed_id="the_unicorn_expedition",
        side=Side.FATE,
        owner=P1,
    )
    probe = Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=itself,
        effects=_horse_ability,
        hits_every_target=True,
        key="probe",
    )
    with probe_ability("horse_probe", probe), probe_ability("scout_probe", probe):
        session = combat_segment(
            [
                holding("mine", gold_production=5),
                personality("rider"),
                personality("vanguard"),
                personality("guard", owner=PlayerId.P2),
            ],
            {"vanguard": 0},
            {"guard": 0},
            in_hand=[strategy],
        )
        table = session.game.table
        follower = AttachmentType.FOLLOWER
        attached(
            table, attachment("horse", printed_id="horse_probe", attachment_type=follower), "rider"
        )
        attached(
            table,
            attachment("scout", printed_id="scout_probe", attachment_type=follower),
            "vanguard",
        )
        for card_id in ("rider", "horse"):
            table.cards_by_id[card_id].bow()
        yield session


def _send_the_rider(session, *invests):
    """Play the Expedition on the rider, paying ``invests`` on top, or plainly with none."""
    if not invests:
        session.act(P1, PlayStrategy("expedition", "battle"))
    else:
        session.act(P1, PlayStrategy("expedition", "invest"))
        session.submit(P1, DecisionResponse(invests))
        pay(session, P1)
    session.submit(P1, DecisionResponse(("rider",)))


def test_the_expedition_is_offered_plain_or_with_invest(expedition):
    offered = {
        action.ability_key
        for action in expedition.legal_actions(P1)
        if isinstance(action, PlayStrategy) and action.card_id == "expedition"
    }

    assert offered == {"battle", "invest"}


def test_investing_offers_both_lines_and_either_or_both(expedition):
    expedition.act(P1, PlayStrategy("expedition", "invest"))

    asked = expedition.game.pending
    assert asked.candidates == (UNICORN_EXPEDITION_FOLLOW_UP, UNICORN_EXPEDITION_STRAIGHTEN)
    assert (asked.minimum, asked.maximum) == (1, 2)


def test_the_expedition_is_withheld_with_no_enemy_to_oppose(expedition):
    resolve_effects(expedition.game, [Move("guard", Location.home(PlayerId.P2))])

    assert not any(
        isinstance(action, PlayStrategy) and action.card_id == "expedition"
        for action in expedition.legal_actions(P1)
    )


def test_the_expedition_moves_a_personality_from_home_to_the_battle(expedition):
    _send_the_rider(expedition)

    rider = expedition.game.table.cards_by_id["rider"]
    assert location_of(expedition.game.table, rider).battlefield == 0
    assert rider.bowed


def test_invest_3_straightens_the_unit_as_it_moves(expedition):
    _send_the_rider(expedition, UNICORN_EXPEDITION_STRAIGHTEN)

    cards = expedition.game.table.cards_by_id
    assert not cards["rider"].bowed and not cards["horse"].bowed


def test_invest_2_follows_up_only_with_a_card_in_the_moved_unit(expedition):
    expedition.game.table.cards_by_id["horse"].unbow()

    _send_the_rider(expedition, UNICORN_EXPEDITION_FOLLOW_UP)

    assert expedition.legal_actions(P1) == [Pass(), HORSE_ACTION]


def test_invest_2_opens_its_follow_up_even_with_nothing_in_the_unit_to_take(expedition):
    _send_the_rider(expedition, UNICORN_EXPEDITION_FOLLOW_UP)

    assert expedition.legal_actions(P1) == [Pass()]
    assert (expedition.game.round.priority, expedition.game.round.granted_by) == (
        P1,
        "expedition",
    )


RESPONSE_PROBE = Ability(
    timings=(ActionTiming.RESPONSE,),
    cost=no_cost,
    targets=itself,
    effects=lambda game, source, target: [],
    hits_every_target=True,
)


def test_a_response_taken_over_the_expedition_leaves_its_follow_up_for_the_battle(expedition):
    with probe_ability("responder_probe", RESPONSE_PROBE):
        put_in_play(
            expedition.game, holding("responder", owner=PlayerId.P2, printed_id="responder_probe")
        )
        expedition.game.table.cards_by_id["horse"].unbow()
        _send_the_rider(expedition, UNICORN_EXPEDITION_FOLLOW_UP)

        expedition.act(PlayerId.P2, ActivateAbility("responder"))

        assert expedition.game.round.kind is RoundKind.BATTLE_SEGMENT
        assert expedition.game.round.granted_by == "expedition"
        assert expedition.legal_actions(P1) == [Pass(), HORSE_ACTION]


def test_a_negated_move_buys_neither_invest(expedition):
    expedition.game.ongoing.append(
        Negation("probe", Duration.UNTIL_END_OF_TURN, effect_kind=Move, subject_id="rider")
    )

    _send_the_rider(expedition, UNICORN_EXPEDITION_FOLLOW_UP, UNICORN_EXPEDITION_STRAIGHTEN)

    cards = expedition.game.table.cards_by_id
    assert location_of(expedition.game.table, cards["rider"]).is_home
    assert cards["rider"].bowed and cards["horse"].bowed
    assert expedition.game.round.follow_ups is None


# --- Desperate Melee ---


def _desperate_melee_game(*, berserker: bool = False, gold_cost: int = 5) -> EngineSession:
    """A Combat Segment with P1's Personality facing two enemy Personalities, each carrying a
    Follower, and Desperate Melee in P1's hand."""
    mine = personality("mine", gold_cost=gold_cost, keywords=("Berserker",) if berserker else ())
    theirs = personality("theirs", owner=P2)
    other = personality("other", owner=P2)
    melee = L5RCard.of(
        ActionPrint,
        id="melee",
        printed_id="desperate_melee",
        name="Desperate Melee",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    session = combat_segment(
        [mine, theirs, other], {"mine": 0}, {"theirs": 0, "other": 0}, in_hand=[melee]
    )
    table = session.game.table
    for follower_id, bearer, cost in (
        ("cheap", "theirs", 2),
        ("dear", "other", 3),
        ("third", "other", 1),
    ):
        attached(
            table,
            attachment(
                follower_id,
                owner=P2,
                attachment_type=AttachmentType.FOLLOWER,
                gold_cost=cost,
            ),
            bearer,
        )
    return session


def _enemy_fate_discard(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)].cards}


def test_desperate_melee_destroys_two_enemy_followers_under_your_personalitys_gold_cost():
    session = _desperate_melee_game(gold_cost=6)

    session.act(P1, PlayStrategy("melee"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("cheap", "dear")))

    assert {"cheap", "dear"} <= _enemy_fate_discard(session)


def test_desperate_melee_will_not_take_a_pair_whose_total_gold_cost_reaches_yours():
    session = _desperate_melee_game(gold_cost=5)

    session.act(P1, PlayStrategy("melee"))
    session.submit(P1, DecisionResponse(("mine",)))

    pending = session.game.pending
    assert pending.accepts(DecisionResponse(("cheap", "dear"))) is False
    assert pending.accepts(DecisionResponse(("dear",))) is True


def test_desperate_melee_offers_a_berserker_more_followers():
    plain = _desperate_melee_game()
    plain.act(P1, PlayStrategy("melee"))
    plain.submit(P1, DecisionResponse(("mine",)))

    berserker = _desperate_melee_game(berserker=True)
    berserker.act(P1, PlayStrategy("melee"))
    berserker.submit(P1, DecisionResponse(("mine",)))

    # Three enemy Followers are on offer, so the Berserker's five clamps to what is there.
    assert plain.game.pending.maximum == 2
    assert berserker.game.pending.maximum == 3


def test_desperate_melee_destroys_your_own_personalitys_followers_too():
    session = _desperate_melee_game(gold_cost=6)
    attached(
        session.game.table,
        attachment("mine_own", attachment_type=AttachmentType.FOLLOWER, gold_cost=1),
        "mine",
    )

    session.act(P1, PlayStrategy("melee"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("cheap",)))

    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "mine_own" in {card.id for card in discard.cards}


def test_desperate_melee_records_both_phrases_as_the_actions_targets():
    session = _desperate_melee_game(gold_cost=6)

    session.act(P1, PlayStrategy("melee"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("cheap",)))

    assert set(session.game.action_targets) == {"mine", "cheap"}


def test_desperate_melee_destroys_your_own_followers_when_the_melee_reaches_none():
    mine = personality("mine", gold_cost=6)
    melee = L5RCard.of(
        ActionPrint,
        id="melee",
        printed_id="desperate_melee",
        name="Desperate Melee",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    session = combat_segment(
        [mine, personality("theirs", owner=P2)], {"mine": 0}, {"theirs": 0}, in_hand=[melee]
    )
    attached(
        session.game.table,
        attachment("mine_own", attachment_type=AttachmentType.FOLLOWER, gold_cost=1),
        "mine",
    )

    session.act(P1, PlayStrategy("melee"))
    session.submit(P1, DecisionResponse(("mine",)))

    # The second phrase has nothing to point at, so it targets nothing and the sentence that
    # destroys your Personality's own Followers still resolves.
    assert session.game.pending is None
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert "mine_own" in {card.id for card in discard.cards}


# --- "Is That All?" ---


def _is_that_all(owner: PlayerId) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id="is_that_all",
        name='"Is That All?"',
        printed_id="is_that_all",
        side=Side.FATE,
        owner=owner,
        keywords=(keywords.COURAGE,),
    )


@pytest.mark.parametrize(
    ("feared", "bowed", "straightened"),
    [("guard", True, True), ("ashigaru", True, False), ("giant", False, False)],
    ids=["personality", "follower", "out_of_reach"],
)
def test_is_that_all_fears_at_the_bowed_personalitys_force(feared, bowed, straightened):
    cards = [
        personality("brave", force=3),
        personality("guard", owner=P2, force=3),
        personality("giant", owner=P2, force=4),
        personality("escort", owner=P2, force=5),
    ]
    defenders = {"guard": 0, "giant": 0, "escort": 0}
    session = combat_segment(cards, {"brave": 0}, defenders, in_hand=[_is_that_all(P1)])
    game = session.game
    follower = attachment("ashigaru", owner=P2, attachment_type=AttachmentType.FOLLOWER, force=2)
    attached(game, follower, "escort")
    resolve_effects(game, [Bow("brave")])

    session.act(P1, PlayStrategy("is_that_all", "fear"))
    session.submit(P1, DecisionResponse(("brave",)))
    session.submit(P1, DecisionResponse((feared,)))
    while game.round.kind is RoundKind.INTERRUPT:
        session.act(game.round.priority, Pass())

    assert game.pending is None
    assert game.table.cards_by_id[feared].bowed is bowed
    assert game.table.cards_by_id["brave"].bowed is not straightened


def test_is_that_alls_fear_is_answerable_at_the_interrupt_step():
    okura = L5RCard.of(
        ActionPrint,
        id="okura",
        name="Okura is Released",
        printed_id="okura_is_released",
        side=Side.FATE,
        owner=P1,
    )
    cards = [personality("brave", force=3), personality("guard", owner=P2, force=3)]
    held = [_is_that_all(P1), okura]
    session = combat_segment(cards, {"brave": 0}, {"guard": 0}, in_hand=held)
    resolve_effects(session.game, [Bow("brave")])

    session.act(P1, PlayStrategy("is_that_all", "fear"))
    session.submit(P1, DecisionResponse(("brave",)))
    session.submit(P1, DecisionResponse(("guard",)))

    assert PlayInterrupt("okura") in session.legal_actions(P1)


def test_okura_destroys_what_is_that_alls_fear_bowed_after_its_personality_straightens():
    okura = L5RCard.of(
        ActionPrint,
        id="okura",
        name="Okura is Released",
        printed_id="okura_is_released",
        side=Side.FATE,
        owner=P1,
    )
    cards = [personality("brave", force=3), personality("guard", owner=P2, force=3)]
    session = combat_segment(cards, {"brave": 0}, {"guard": 0}, in_hand=[_is_that_all(P1), okura])
    game = session.game
    resolve_effects(game, [Bow("brave")])

    session.act(P1, PlayStrategy("is_that_all", "fear"))
    session.submit(P1, DecisionResponse(("brave",)))
    session.submit(P1, DecisionResponse(("guard",)))
    session.act(P1, PlayInterrupt("okura"))
    while game.round.kind is RoundKind.INTERRUPT:
        session.act(game.round.priority, Pass())

    order = [
        type(event).__name__
        for event in game.turn_events
        if isinstance(event, Straightened | Destroyed)
    ]
    assert order == ["Straightened", "Destroyed"]
    assert not game.table.cards_by_id["brave"].bowed


def test_is_that_all_is_not_played_with_nothing_to_fear():
    cards = [personality("brave", force=3), personality("guard", owner=P2, force=3)]
    session = combat_segment(cards, {"brave": 0}, {"guard": 1}, in_hand=[_is_that_all(P1)])
    resolve_effects(session.game, [Bow("brave")])

    assert PlayStrategy("is_that_all", "fear") not in session.legal_actions(P1)


def test_is_that_all_destroys_the_zero_cost_attachment_an_action_was_from():
    trinket_ability = Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        hits_every_target=True,
    )
    cards = [personality("raider", force=3), personality("guard", owner=P2, force=3)]
    with probe_ability("trinket_probe", trinket_ability):
        session = combat_segment(cards, {"raider": 0}, {"guard": 0}, in_hand=[_is_that_all(P2)])
        game = session.game
        trinket = attachment("trinket", printed_id="trinket_probe", gold_cost=0)
        attached(game, trinket, "raider")

        session.act(P1, ActivateAbility("trinket"))
        assert game.round.kind is RoundKind.RESPONSE
        session.act(P2, PlayStrategy("is_that_all", "destroy"))

    assert "trinket" not in {card.id for card in game.table.battlefield.cards}
