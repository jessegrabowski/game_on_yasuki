from dataclasses import dataclass, field
from typing import NamedTuple

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, Segment


class BattleOutcome(NamedTuple):
    """What resolving a battle did, recorded as it happened.

    Attributes
    ----------
    winner : PlayerId or None
        The seat whose Force was higher, or None if the battle was tied.
    destroyed : tuple of str
        The ids of the cards destroyed, in the order they went.
    province_destroyed : bool
        Whether the Province the battle was fought at was destroyed.
    honor : dict mapping PlayerId to int
        How far each seat's Family Honor moved. A seat that neither gained nor lost is absent.
    """

    winner: PlayerId | None
    destroyed: tuple[str, ...]
    province_destroyed: bool
    honor: dict[PlayerId, int]


class BattlefieldInfo(NamedTuple):
    """A battlefield an attack created, and the Defender Province it is associated with.

    Attributes
    ----------
    province : ZoneKey
        The Province this battlefield sits at.
    outcome : BattleOutcome or None
        What the battle fought here did, or None until one has been.
    """

    province: ZoneKey
    outcome: BattleOutcome | None = None


@dataclass(slots=True)
class AttackPhase:
    """The attack the active player declared this turn, and the battlefields it created.

    A card standing at a battlefield names it by the index it has in :attr:`battlefields`, which is
    what its :class:`~yasuki_core.engine.table.Location` carries.

    Attributes
    ----------
    attacker : PlayerId
        The seat that declared, which is always the active player.
    defender : PlayerId
        The seat being attacked, at whose Provinces the battlefields stand.
    battlefields : tuple of BattlefieldInfo
        One per Defender Province, in Province order. A card at a battlefield indexes into this
        tuple, so the order is load-bearing and fixed for the life of the attack.
    segment : Segment
        Which segment of the phase is open. Default ``Segment.DECLARATION``.
    fought : frozenset of int
        The battlefields a battle has already been fought at. Exactly one battle happens at each,
        so this is what the fight loop counts down. Default empty.
    current : int or None
        The battlefield a battle is being fought at, or None between battles. Default None.
    battle_segment : BattleSegment or None
        Which segment of the battle at ``current`` is open, or None when no battle is being fought.
        Default None.
    assigned_in : dict mapping str to str
        Each assigned Personality to the maneuvers window it assigned in. The current rules run one
        window, so every entry names the same one. Earlier editions ran Infantry Maneuvers and
        Cavalry Maneuvers as two, and cards ask which of them a unit came in on. Recording where a
        unit ended up would not answer that. Default empty.
    """

    attacker: PlayerId
    defender: PlayerId
    battlefields: tuple[BattlefieldInfo, ...]
    segment: Segment = Segment.DECLARATION
    fought: frozenset[int] = frozenset()
    current: int | None = None
    battle_segment: BattleSegment | None = None
    assigned_in: dict[str, str] = field(default_factory=dict)

    @property
    def current_province(self) -> ZoneKey:
        """The Province the battle now being fought sits at: what a card means by "the current
        Province". Raise ``TypeError`` between battles, when there is no current battlefield."""
        return self.battlefields[self.current].province
