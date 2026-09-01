from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    _ABILITIES,
    bow_parent_cost,
    can_pay,
)
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.attachments import attached_to
from yasuki_core.engine.rules.economy import effective_force
from yasuki_core.engine.rules.effects import AdjustCounter, Unpayable
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1

# A synthetic attachment whose ability is paid by the Personality carrying it and whose effect reads
# that Personality's Force. Between them they exercise both directions of the parent reference — the
# cost reaching a card the ability never chose, and the effect reading a stat off it. No real card is
# encoded yet; that is PR 2's job.
_ABILITIES["test_bows_its_personality"] = Ability(
    timings=(ActionTiming.OPEN,),
    label="test",
    cost=bow_parent_cost,
    targets=lambda game, card: [card.id],
    effects=lambda game, source, target: [
        AdjustCounter(source.id, WEALTH, effective_force(game, attached_to(game, source)))
    ],
    # It acts on itself, so there is nothing to choose and activation settles in one step.
    all_targets=True,
)


def _equipped(force: int = 3):
    """A board holding a Personality with the probe attachment on him.

    Only the board is returned, never the cards: starting a session rebuilds the table, so a card
    grabbed here is a detached copy by the time the test asserts on it.
    """
    game = two_seat_game()
    put_in_play(game, personality("hero", force=force, chi=3))
    attached(game, attachment("item", printed_id="test_bows_its_personality"), "hero")
    return game


def test_the_cost_bows_the_personality_not_the_attachment():
    """An attachment acts through the Personality carrying it, so what the cost spends is his
    bow — the attachment itself stays ready."""
    game = _equipped()
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("item"))

    assert session.game.table.cards_by_id["hero"].bowed is True
    assert session.game.table.cards_by_id["item"].bowed is False


def test_the_effect_reads_the_personality_it_hangs_on():
    game = _equipped(force=4)
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("item"))

    assert session.game.table.cards_by_id["item"].counters[WEALTH.key] == 4


def test_the_ability_is_offered_while_the_personality_can_pay():
    """The control for the negative cases below. Without it they would all pass just as well if the
    ability were never offered at all — a broken location or timing would read as a clean suite."""
    game = _equipped()
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("item") in session.legal_actions(P1)


def test_the_ability_is_not_offered_when_the_personality_is_already_bowed():
    """The cost is the parent's bow, so his state gates the ability — not the attachment's."""
    game = _equipped()
    session = EngineSession.start(game.table, P1)
    # Bowed through the live game: starting a session runs the first turn's straighten, which would
    # undo a bow applied to the board beforehand.
    session.game.table.cards_by_id["hero"].bow()

    assert ActivateAbility("item") not in session.legal_actions(P1)


def test_an_unattached_attachment_cannot_pay_a_parent_cost():
    """A cost naming a card the board does not hold has to answer "no". Returning no effects would
    read as a free cost and offer the ability to a card with no Personality at all."""
    game = two_seat_game()
    loose = put_in_play(game, attachment("item", printed_id="test_bows_its_personality"))

    # Typed rather than compared whole: the reason is trace text, not contract, and pinning its
    # wording here would break the test on a reword that changes nothing.
    assert [type(effect) for effect in bow_parent_cost(game, loose)] == [Unpayable]
    assert can_pay(game, loose, bow_parent_cost) is False


def test_the_ability_follows_the_attachment_to_a_new_personality():
    """The parent is read from the graph at activation rather than captured when the card is
    registered, so moving the attachment moves what its cost spends."""
    game = _equipped()
    put_in_play(game, personality("second", force=2, chi=3))
    attached(game, game.table.cards_by_id["item"], "second")
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("item"))

    assert session.game.table.cards_by_id["second"].bowed is True
    assert session.game.table.cards_by_id["hero"].bowed is False
