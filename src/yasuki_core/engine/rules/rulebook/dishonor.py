from yasuki_core.engine.rules.effects import Effect, GainHonor
from yasuki_core.engine.rules.triggers import TriggerContext, rulebook_trigger
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed
from yasuki_core.game_pieces.prints import PersonalityPrint


@rulebook_trigger(Destroyed)
def lose_honor_for_a_dishonorable_death(ctx: TriggerContext) -> list[Effect]:
    """After a dishonorable Personality is destroyed, his controller loses Honor equal to his
    printed Personal Honor (CR, Honorable and Dishonorable). The printed value, not the effective
    one, which the cap holds at zero for as long as he is dishonorable."""
    card = ctx.card
    if not isinstance(card.printed, PersonalityPrint) or not card.dishonorable:
        return []
    return [GainHonor(card.owner, -card.personal_honor)]
