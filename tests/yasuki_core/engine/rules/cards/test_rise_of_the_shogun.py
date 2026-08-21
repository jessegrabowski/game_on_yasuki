from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.cards.onyx_edition import CAVALRY_FOLLOWER
from yasuki_core.engine.rules.decisions import Confirm, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.economy import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)

from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    token_template,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)


def test_shadowlands_ambassador_dishonors_the_personality_he_serves():
    """He prints Force 2 and Chi -1 and reads "This Personality has -1PH". The Force is his own and
    stays with the unit; the Chi and the Honor are both the Personality's."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=3, chi=2, personal_honor=2))
    attached(
        game,
        attachment(
            "ambassador",
            printed_id="shadowlands_ambassador",
            attachment_type=AttachmentType.FOLLOWER,
            force=2,
            chi_modifier=-1,
        ),
        "hero",
    )

    assert effective_force(game, hero) == 3
    assert effective_chi(game, hero) == 1
    assert effective_personal_honor(game, hero) == 1


# --- Shadowlands Ambassador's bow waiver ---

P1 = PlayerId.P1


def _gorou_game(*, ambassador=True):
    """Utaku Gorou, whose Open ability costs a bow, with the Ambassador on him to waive it."""
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
    if ambassador:
        attached(
            game,
            attachment(
                "ambassador",
                printed_id="shadowlands_ambassador",
                attachment_type=AttachmentType.FOLLOWER,
                force=2,
                chi_modifier=-1,
            ),
            "gorou",
        )
    return EngineSession.start(game.table, P1)


def test_paying_a_bow_cost_offers_the_waiver_first():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))

    pending = session.game.pending
    assert isinstance(pending, Confirm)
    assert pending.question == "Ignore the cost of bowing gorou?"


def test_taking_the_waiver_leaves_him_standing_and_still_resolves():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("ambassador",)))  # yes: ignore the cost
    session.submit(P1, DecisionResponse(("bushi",)))

    game = session.game
    assert game.table.cards_by_id["gorou"].bowed is False
    assert attachments_of(game, game.table.cards_by_id["bushi"])[0].name == "Cavalry"


def test_declining_the_waiver_pays_the_cost_as_printed():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(()))  # no: bow him
    session.submit(P1, DecisionResponse(("bushi",)))

    assert session.game.table.cards_by_id["gorou"].bowed is True


def test_the_waiver_is_offered_once_a_turn():
    """Spent on the first ability, the second is charged as printed with nothing to ask about."""
    session = _gorou_game()
    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("ambassador",)))
    session.submit(P1, DecisionResponse(("bushi",)))

    session.game.table.cards_by_id["gorou"].unbow()
    session.act(PlayerId.P2, Pass())
    session.act(P1, ActivateAbility("gorou"))

    assert not isinstance(session.game.pending, Confirm)  # nothing left to waive
    assert session.game.table.cards_by_id["gorou"].bowed is True


def test_merely_listing_the_action_does_not_spend_the_waiver():
    """A cost is built to decide legality as well as to pay, so looking must not spend the use."""
    session = _gorou_game()

    session.legal_actions(P1)
    session.legal_actions(P1)
    session.act(P1, ActivateAbility("gorou"))

    assert isinstance(session.game.pending, Confirm)


def test_a_personality_without_the_ambassador_is_asked_nothing():
    session = _gorou_game(ambassador=False)

    session.act(P1, ActivateAbility("gorou"))

    assert not isinstance(session.game.pending, Confirm)
    assert session.game.table.cards_by_id["gorou"].bowed is True
