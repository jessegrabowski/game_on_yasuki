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


class ArmyForces(NamedTuple):
    """Both armies' Force at a battlefield as its resolution began (CR, Army Force).

    Attributes
    ----------
    attacking : int
        The attacking army's Force.
    defending : int
        The defending army's Force.
    """

    attacking: int
    defending: int


class BattlefieldInfo(NamedTuple):
    """A battlefield an attack created, and the Defender Province it is associated with, if any.

    Attributes
    ----------
    province : ZoneKey or None
        The Province this battlefield sits at, or None for a battlefield not associated with any
        Province (CR, Battlefields), which no battle's resolution can destroy.
    outcome : BattleOutcome or None
        What the battle fought here did, or None until one has been.
    ever_present : frozenset of (PlayerId, str)
        Each seat and the Personality it ever had at this battlefield, by assignment or by a move,
        whether or not the Personality was still there when the battle was fought. An entry stays
        once written, because "any enemy units were ever at its battlefield" asks about the whole
        attack. Default empty.
    bow_exempt : frozenset of PlayerId
        The seats whose units the battle's resolution does not bow (CR, After Resolution 0.1), as
        Rallying Cry grants. Default empty.
    terrains_played : frozenset of (PlayerId, str)
        Each seat and the Terrain it played here from its hand. Default empty.
    terrains_destroyed : frozenset of (PlayerId, str)
        Each seat and the Terrain here it destroyed. Default empty.
    printed_actions : frozenset of PlayerId
        The seats that took a printed action from one of their cards while the battle here was
        being fought. Default empty.
    sealed : bool
        Whether units may no longer be placed here, as "Other Personalities cannot move there"
        reads. The units recorded ever present assigned as the battlefield was made and may still
        come and go. Default False.
    """

    province: ZoneKey | None
    outcome: BattleOutcome | None = None
    ever_present: frozenset[tuple[PlayerId, str]] = frozenset()
    bow_exempt: frozenset[PlayerId] = frozenset()
    terrains_played: frozenset[tuple[PlayerId, str]] = frozenset()
    terrains_destroyed: frozenset[tuple[PlayerId, str]] = frozenset()
    printed_actions: frozenset[PlayerId] = frozenset()
    sealed: bool = False


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
        The battlefields this attack created: one per Defender Province, in Province order, when
        declared. A card at a battlefield indexes into this tuple, so the order is load-bearing
        and entries are never removed or reordered for the life of the attack.
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

    def amend(self, battlefield: int, **changes: object) -> None:
        """Record ``changes`` on the battlefield at index ``battlefield``."""
        # A NamedTuple, so this is a replacement rather than an assignment.
        self.battlefields = tuple(
            info._replace(**changes) if index == battlefield else info
            for index, info in enumerate(self.battlefields)
        )

    def enemy_of(self, seat: PlayerId) -> PlayerId:
        """The other side of the attack from ``seat``. Raise ``KeyError`` for a seat on neither."""
        if seat is self.attacker:
            return self.defender
        if seat is self.defender:
            return self.attacker
        raise KeyError(f"{seat} is not in this attack")

    @property
    def current_province(self) -> ZoneKey | None:
        """The Province the battle now being fought sits at: what a card means by "the current
        Province". None at a battlefield not associated with any Province, where nothing is the
        current Province. Raise ``ValueError`` between battles, when there is no current
        battlefield, so that None keeps exactly one meaning."""
        if self.current is None:
            raise ValueError("no battle is being fought")
        return self.battlefields[self.current].province
