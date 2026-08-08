from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Cycle, Pass, Recruit
from yasuki_core.engine.rules.policies import EconomicCyclePolicy, cards_to_cycle
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyPersonality

from tests.yasuki_core.engine.builders import (
    dealt_table,
    holding,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _opening(*productions: int) -> EngineSession:
    """A session on P1's opening turn in the Action phase, one face-up Province card per
    production. Cycle is on offer here and nowhere else."""
    session = EngineSession.start(dealt_table(), P1, seed=1)
    for index, production in enumerate(productions):
        province_card(session.game, f"pv{index}", seat=P1, gold_production=production, index=index)
    return session


def _deck_cards(*productions: int):
    return [
        holding(f"deck{index}", owner=P1, gold_production=production)
        for index, production in enumerate(productions)
    ]


def _view(session: EngineSession, *deck_productions: int):
    """P1's view with a stand-in dynasty deck, so a test states the deck it is judged against."""
    return replace(session.project(P1), dynasty_deck=tuple(_deck_cards(*deck_productions)))


def _seed_dynasty(session: EngineSession, *productions: int) -> None:
    """Put real cards in P1's dynasty deck, so a Province it empties has something to refill from.
    ``dealt_table`` seeds only the fate decks."""
    cards = _deck_cards(*productions)
    for card in cards:
        register(session.game.table, card)
    session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards = cards


def _province_ids(session: EngineSession) -> set[str]:
    return {
        card.id
        for key, zone in session.game.table.zones.items()
        if key.owner is P1 and key.role is ZoneRole.PROVINCE
        for card in zone.cards
    }


def test_it_replaces_only_the_cards_the_deck_beats():
    # The deck averages 3, so the 1 is worth redrawing and the 5 is not.
    session = _opening(1, 5)

    assert cards_to_cycle(_view(session, 2, 4)) == ("pv0",)


def test_every_card_the_deck_beats_goes_back_in_a_settled_order():
    # More than one card can be worth replacing, and the harness reruns a seed expecting the same
    # game. The ids run against Province order on purpose: sorting is only observable when the two
    # disagree, so pv0/pv1 naming would pass whether or not the answer is sorted at all.
    session = EngineSession.start(dealt_table(), P1, seed=1)
    province_card(session.game, "z-weak", seat=P1, gold_production=0, index=0)
    province_card(session.game, "a-weak", seat=P1, gold_production=1, index=1)

    assert cards_to_cycle(_view(session, 4)) == ("a-weak", "z-weak")


def test_a_personality_counts_as_producing_nothing():
    # Gold Production is declared on Holdings, so a Personality has no such attribute at all — and
    # a face-up Personality is an ordinary opening, not an edge case. Reading the stat off the card
    # rather than through the module's accessor raises instead of ranking it last.
    session = _opening(4)
    hero = DynastyPersonality(id="hero", name="Bushi", side=Side.DYNASTY, owner=P1, force=3)
    register(session.game.table, hero)
    hero.turn_face_up()
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 1)] = ProvinceZone(owner=P1)
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 1)].add(hero)

    assert cards_to_cycle(_view(session, 2, 4)) == ("hero",)


def test_a_deck_of_personalities_averages_to_nothing():
    # The same accessor covers the other loop: a real deck holds Personalities, so summing the
    # stat directly would raise before any Province card was judged.
    session = _opening(0)
    deck = [DynastyPersonality(id="p", name="Bushi", side=Side.DYNASTY, owner=P1)]

    assert cards_to_cycle(replace(session.project(P1), dynasty_deck=tuple(deck))) == ()


def test_a_card_matching_the_deck_average_is_left_alone():
    # Strictly worse, not merely not-better: swapping an average card for an average card churns
    # the deck for nothing.
    session = _opening(3)

    assert cards_to_cycle(_view(session, 3, 3)) == ()


def test_an_empty_deck_is_never_worth_cycling_into():
    # There is nothing to draw but the cards just put back, so the row would come back unchanged.
    session = _opening(0)

    assert cards_to_cycle(_view(session)) == ()


def test_a_face_down_card_the_seat_has_peeked_is_not_offered_up():
    # A Legacy search leaves the seat peeking its own face-down Province cards, which makes them
    # identifiable in the view without making them face-up. Cycle only accepts face-up cards, so
    # naming one would answer the choice with a card the engine rejects.
    session = _opening(9)
    hidden = province_card(
        session.game, "hidden", seat=P1, gold_production=0, face_up=False, index=1
    )
    hidden.add_peeker(P1)

    assert cards_to_cycle(_view(session, 4)) == ()


def test_it_takes_cycle_when_something_is_worth_replacing():
    session = _opening(0, 1)

    assert EconomicCyclePolicy().choose(_view(session, 4), session.legal_actions(P1)) == Cycle()


def test_it_declines_cycle_when_the_opening_already_beats_the_deck():
    # Recruits are offered only in the Dynasty phase, so passing is the whole of what declining
    # looks like here — the buying delegation is exercised by the test below instead.
    session = _opening(5, 6)

    assert EconomicCyclePolicy().choose(_view(session, 1), session.legal_actions(P1)) == Pass()


def test_it_buys_like_the_economic_policy_when_cycle_is_not_on_offer():
    # The other half of the policy: everything that is not the cycle decision has to reach the
    # buying policy, which a fallback hardcoded to Pass would satisfy in the Action phase alone.
    session = EngineSession.start(dealt_table(), P1, seed=1)
    put_in_play(session.game, holding("purse", owner=P1, gold_production=6))
    province_card(session.game, "buyme", seat=P1, gold_cost=3, gold_production=4, index=0)
    session.act(P1, Pass())  # Action -> Attack
    session.act(P1, Pass())  # Attack -> Dynasty

    chosen = EconomicCyclePolicy().choose(session.project(P1), session.legal_actions(P1))

    assert chosen == Recruit("buyme")


def test_it_answers_its_own_choice_with_the_cards_it_chose_over():
    # The policy picks the action and the agent answers the decision it raises. Split across two
    # objects that judge separately, a seat could take Cycle and then put back a different set.
    # The weak card is second on purpose: a generic agent answers with the shortest accepted
    # prefix, so it would put back the first card and pass a test where the two happened to agree.
    session = _opening(5, 1)
    _seed_dynasty(session, 2, 4)  # the real deck, so the emptied Province has a card to draw
    view = session.project(P1)
    policy = EconomicCyclePolicy()

    session.act(P1, policy.choose(view, session.legal_actions(P1)))
    session.submit(P1, policy.decide(session.game.pending, view))

    # pv1 went under and its Province refilled; pv0 was worth keeping and stayed put.
    remaining = _province_ids(session)
    assert "pv1" not in remaining
    assert "pv0" in remaining
