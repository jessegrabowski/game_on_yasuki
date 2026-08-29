from yasuki_core import ruleset
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import Phase

# The CR's own names for the turn's phases, in its Turn Sequence. The engine's middle phase is
# named BATTLE; the CR calls it the Attack Phase, and the player is shown the CR's name.
PHASE_LABELS: dict[Phase, str] = {
    Phase.ACTION: "Action Phase",
    Phase.BATTLE: "Attack Phase",
    Phase.DYNASTY: "Dynasty Phase",
}


def turn_context(view: GameView) -> str:
    """Whose turn it is and where in it the seat stands, in the live ruleset's own words.

    The most specific heading that applies: the segment of the Attack Phase once an attack has been
    declared, and the phase otherwise. A turn belongs to its active player even where both seats may
    act inside it, so the possessive follows the turn rather than the opportunity to act.
    """
    whose = "Your" if view.active is view.viewer else "Opponent's"
    if view.attack is not None:
        return f"{whose} {ruleset.ACTIVE.segment_name(view.attack.segment)}"
    return f"{whose} {PHASE_LABELS[view.phase]}"
