import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.cards.road_to_ruin import FORGOTTEN_DEAD
from yasuki_core.engine.rules.effects import AttachCard, Destroy
from yasuki_core.engine.rules.flow import submit
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import (
    effective_force,
    effective_gold_cost,
)
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import MINUS_1F
from yasuki_core.game_pieces.prints import HoldingPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


def _ruins_game(*, in_deck=("mine",), in_discard=(), in_play=(), unique=()):
    """A session with P1's Repairing the Ruins face-up in a Province, and Holdings salted through
    the zones it searches. Ids double as printed ids, so a card in play blocks the copy of itself."""
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
    """ "…of which you do not control any copies." Control is judged per printed id, so an unrelated
    Holding in play leaves the deck's copy findable."""
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
    """ "…and permanently give it +1 Gold Cost if it was not from your discard pile." """
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
    """The Holding lands face-up in the Province, not in play, so the rider is what the seat pays."""
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
            state, L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1)
        )
    ]
    if with_producer:
        put_in_play(
            state,
            L5RCard.of(
                HoldingPrint, id="sh", name="SH", side=Side.DYNASTY, owner=P1, gold_production=8
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
    not been asked yet — the question comes in the window, as it bows."""
    session = _outlying_game()
    session.act(P1, Recruit("target"))

    pending = session.game.pending
    assert dict(pending.produced)["of"] == 2
    assert pending.grantable == (("of", 2),)


def test_bowing_outlying_farms_opens_its_window_before_the_yield_is_read():
    session = _outlying_game(with_producer=False)
    session.act(P1, Recruit("target"))

    session.submit(P1, DecisionResponse(("of",)))

    pending = session.game.pending
    assert pending.question == (
        "Give Outlying Farms +2 Gold Production? It is destroyed after it bows."
    )
    assert pending.candidates == ("of",)
    assert not session.game.table.cards_by_id["of"].bowed  # the yield is still unread


def test_a_grant_the_payment_cannot_do_without_refuses_no_as_an_answer():
    """Affordability counted the grant to offer the recruit, so announcing it commits the seat. The
    question stops saying no is an option, leaving cancelling as the way out."""
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))

    pending = session.game.pending
    assert not pending.accepts(DecisionResponse(()))
    assert pending.accepts(DecisionResponse(("of",)))
    assert pending.cancellable


def test_a_grant_the_payment_does_not_need_can_still_be_declined():
    """Nothing is committed when another producer covers the cost, so the Farm's window is the plain
    optional question the card prints."""
    session = _outlying_game(target_cost=10)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))

    assert session.game.pending.accepts(DecisionResponse(()))


def test_backing_out_at_the_window_leaves_the_board_as_it_was():
    """The seat announced a Recruit and only then learned the price was the Farm. Cancelling has to
    put back everything the announcement moved, not just the question."""
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, Recruit("target"))
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
    assert Recruit("target") in session.legal_actions(P1)

    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(("of",)))  # yes

    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")  # destroyed after bowing granted
    assert session.game.gold[P1] == 0


def test_the_grant_is_banked_and_outlying_farms_destroyed_even_when_unneeded():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(("of",)))  # yes, though 2 already covers

    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")
    assert session.game.gold[P1] == 2  # 4 produced, 2 spent, 2 excess banked


def test_declining_bows_outlying_farms_for_its_plain_yield():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, Recruit("target"))
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
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))
    session.submit(P1, DecisionResponse(()))  # no
    session.submit(P1, DecisionResponse(("sh",)))

    assert _recruited(session, "target")
    assert not _in_dynasty_discard(session, "of")


def test_the_outlying_farms_grant_replays_to_the_same_state():
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, Recruit("target"))
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
