from yasuki_core import ruleset
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import BattleSegment, Phase

# The CR's own names for the turn's phases, in its Turn Sequence. The engine's middle phase is
# named BATTLE; the CR calls it the Attack Phase, and the player is shown the CR's name.
PHASE_LABELS: dict[Phase, str] = {
    Phase.ACTION: "Action Phase",
    Phase.BATTLE: "Attack Phase",
    Phase.DYNASTY: "Dynasty Phase",
}


# The Battle Sequence as a lane's foot can print it: four cells across a column the width of a
# card, so the "Segment" three of the four names carry is cut. Here rather than in the ruleset,
# which spells what the arc calls a segment, not how a widget abbreviates it.
BATTLE_SEGMENT_CHIPS: dict[BattleSegment, str] = {
    BattleSegment.ENGAGE: "Engage",
    BattleSegment.COMBAT: "Combat",
    BattleSegment.RESOLUTION: "Resolution",
    BattleSegment.AFTER_RESOLUTION: "After-Resolution",
}


def turn_context(view: GameView) -> str:
    """Whose turn it is and where in it the seat stands, in the live ruleset's own words.

    The most specific heading that applies: the segment of the battle being fought once one is
    under way, the segment of the Attack Phase once an attack has been declared, and the phase
    otherwise. A turn belongs to its active player even where both seats may act inside it, so the
    possessive follows the turn rather than the opportunity to act.
    """
    whose = "Your" if view.active is view.viewer else "Opponent's"
    attack = view.attack
    if attack is None:
        return f"{whose} {PHASE_LABELS[view.phase]}"
    if attack.battle_segment is None or attack.current is None:
        return f"{whose} {ruleset.ACTIVE.segment_name(attack.segment)}"
    segment = ruleset.ACTIVE.battle_segment_name(attack.battle_segment)
    return f"{whose} {segment} at Battlefield {attack.current + 1}"
