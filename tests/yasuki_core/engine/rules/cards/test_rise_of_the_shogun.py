from yasuki_core.engine.rules.economy import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)

from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
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
