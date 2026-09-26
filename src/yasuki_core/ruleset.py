from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol

from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.duel.focusing import TWENTY_FESTIVALS_FOCUSING, FocusProcedure
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, Segment


def normalize_clan(name: str) -> str:
    """The comparison key for a clan name: lowercased, with a trailing ``" Clan"`` dropped and
    surrounding whitespace stripped, so ``"Crab Clan"``, ``"Crab"``, and ``"crab"`` all compare
    equal."""
    return name.strip().lower().removesuffix(" clan")


class RingEntry(Enum):
    """How a Ring whose text reads "Play after X" enters play.

    IMMEDIATE
        Offered the moment X resolves, and again each time X happens again, as the Twenty
        Festivals CR reads the Ring rule: the entry may not be delayed and the condition may be
        fulfilled more than once.
    AS_ACTION
        A placeholder for an arc that reads the trait as an action the player takes. Nothing is
        implemented behind it, and a registration read under it raises.
    """

    IMMEDIATE = "immediate"
    AS_ACTION = "as_action"


@dataclass(frozen=True, slots=True)
class FavorAbility:
    """A rulebook ability the Imperial Favor pays for, as one arc's rulebook grants it.

    Which abilities exist and what they are designated is arc configuration, not a constant: the
    pre-Gold rulebook granted four and the Onyx/ShE datasheet grants two, and the one they share
    reads under a different designator in each.

    Attributes
    ----------
    key : str
        Names the ability's effects in ``FAVOR_ABILITY_EFFECTS``. Distinct per arc, because two arcs
        granting "draw a card" for the Favor charge differently for it.
    timing : ActionTiming
        The designator it is taken under.
    label : str
        What the ability does, as the player reads it on a menu.
    active_seat_only : bool, optional
        Whether the rulebook restricts it to the player whose turn it is, which an Open designator
        does not do on its own. Default False.
    keywords : frozenset of str, optional
        The ability keywords the rulebook prints ahead of its designator, such as Political.
        Default empty.
    """

    key: str
    timing: ActionTiming
    label: str
    active_seat_only: bool = False
    keywords: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Ruleset:
    """The arc-specific rules constants the engine reads. Bundling them behind one object lets a
    later arc's ruleset be swapped in wholesale rather than editing scattered literals.

    Attributes
    ----------
    name : str
        The name an ability carries in its ``ruleset`` field to be read under this ruleset alone.
    arcs : tuple of str
        The arcs this ruleset governs, as ``set_info.yaml`` names them. An ability registered under
        this ruleset alone is implemented in the card's first printing among these arcs' sets.
        Default empty.
    clan_alignments : frozenset of str
        The legal Clan Alignments, as canonical :func:`~.normalize_clan` slugs. A card's clan counts
        toward alignment only if it resolves into this set. Every other clan name is unaligned.
    clan_aliases : dict mapping str to str
        Alternate clan slugs that resolve to a canonical member of ``clan_alignments`` (e.g. Naga
        is the same alignment as Akasha in this arc). Applied before the membership test. Default
        empty.
    off_clan_surcharge : int
        Extra Gold a Recruit costs when the card has a Clan Alignment the recruiting seat does not
        share. Default 2.
    honor_victory_at : int
        The Family Honor a seat must start its turn on to win an Honor Victory. Default 40.
    dishonor_loss_at : int
        The Family Honor at or below which a seat loses at the end of its turn. Default -20.
    attack_segments : tuple of Segment
        The Attack Phase's segments in the order this arc walks them. The enum's own order is not
        the authority, because an arc may walk a subset or interleave a segment another arc has no
        equivalent of.
    segment_names : dict mapping Segment to str
        What this arc's rulebook calls each of ``attack_segments``, shown to the player.
    battle_segments : tuple of BattleSegment
        One battle's segments in the order this arc's Battle Sequence walks them, nested inside the
        Fight Battles segment.
    battle_segment_names : dict mapping BattleSegment to str
        What this arc's rulebook calls each of ``battle_segments``, shown to the player.
    favor_abilities : tuple of FavorAbility
        The rulebook abilities this arc lets the Favor pay for. Empty for an arc whose rulebook
        grants none, which is what Gold Edition changed to when it made every use come from a card.
    abilities_once_per_turn : bool
        Whether an ability on a card in play, and a player ability, may be used only once per turn
        unless it prints Repeatable (CR, Using Abilities 0.3). Earlier arcs let every ability
        repeat. Default True, the CR's.
    ring_entry : RingEntry
        How a Ring's "Play after X" trait puts it into play. Default immediate, the CR's.
    lobby_timing : ActionTiming
        The designator the rulebook Lobby ability is taken under. The Twenty Festivals CR makes it
        Limited and the Onyx/ShE datasheet makes it Open, which are different Action Rounds with
        different players entitled to act. Default Limited, the CR's.
    focus_procedure : FocusProcedure
        How this arc's duels are focused: what may be focused, how many times, and what focusing one
        card does. Default the Twenty Festivals CR's.
    duel_stat_default : Stat
        The stat a duel compares where nothing overrides it. Default Chi, the CR's.
    rulebook_proxies : tuple of str
        The ids of the proxy cards dealt to each seat's rulebook zone as a game begins, one per
        rulebook ability family the arc grants, whose abilities are activated from there. Empty for
        an arc that grants none through a proxy. Default empty.
    """

    name: str
    clan_alignments: frozenset[str]
    arcs: tuple[str, ...] = ()
    clan_aliases: dict[str, str] = field(default_factory=dict)
    off_clan_surcharge: int = 2
    honor_victory_at: int = 40
    dishonor_loss_at: int = -20
    attack_segments: tuple[Segment, ...] = ()
    segment_names: dict[Segment, str] = field(default_factory=dict)
    battle_segments: tuple[BattleSegment, ...] = ()
    battle_segment_names: dict[BattleSegment, str] = field(default_factory=dict)
    abilities_once_per_turn: bool = True
    ring_entry: RingEntry = RingEntry.IMMEDIATE
    lobby_timing: ActionTiming = ActionTiming.LIMITED
    lobby_keywords: frozenset[str] = frozenset()
    favor_abilities: tuple[FavorAbility, ...] = ()
    focus_procedure: FocusProcedure = TWENTY_FESTIVALS_FOCUSING
    duel_stat_default: Stat = Stat.CHI
    rulebook_proxies: tuple[str, ...] = ()

    def segment_name(self, segment: Segment) -> str:
        """What this arc calls ``segment``.

        Raises
        ------
        KeyError
            If this arc does not walk ``segment``, which is a segment the engine reached under a
            ruleset that has no name for it: a wiring error rather than something to paper over.
        """
        return self.segment_names[segment]

    def battle_segment_name(self, segment: BattleSegment) -> str:
        """What this arc calls ``segment`` of a battle.

        Raises
        ------
        KeyError
            If this arc does not walk ``segment``, which is a segment the engine reached under a
            ruleset that has no name for it: a wiring error rather than something to paper over.
        """
        return self.battle_segment_names[segment]

    def alignment(self, clan_name: str) -> str | None:
        """The canonical Clan Alignment slug ``clan_name`` denotes, or None when it is not a legal
        alignment in this ruleset. Resolves aliases (Naga -> Akasha) before the membership test, so
        equal alignments always share one slug."""
        slug = normalize_clan(clan_name)
        slug = self.clan_aliases.get(slug, slug)
        return slug if slug in self.clan_alignments else None


# The clans the engine names, as canonical :func:`~.normalize_clan` slugs. A clan is card text
# like a keyword is, so it is spelled once here rather than at each call site. It is here rather
# than beside the keywords because which of these count as Clan Alignments is arc config, and a
# ruleset below builds its set from these names so the two cannot drift.
AKASHA = "akasha"
CRAB = "crab"
CRANE = "crane"
DRAGON = "dragon"
LION = "lion"
MANTIS = "mantis"
# Naga is a clan a card can carry but not an alignment of its own: it resolves to Akasha below.
NAGA = "naga"
PHOENIX = "phoenix"
SCORPION = "scorpion"
SPIDER = "spider"
UNICORN = "unicorn"

# The Attack Phase Sequence the Twenty Festivals CR lists, with its own headings. Fight Battles is
# the CR's name for the third and the CR does not call that one a Segment, so neither does this.
#
# Earlier arcs walk a different sequence. The Cavalry Maneuvers segment between Maneuvers and the
# battles is the one that will bring this to a head. Adding it is three edits: a member on
# :class:`~yasuki_core.engine.rules.vocabulary.segments.Segment`, a place in that arc's
# ``attack_segments``, and a name in its ``segment_names``. Nothing reads the enum's declaration
# order, so no arc inherits another's sequence.
_ONYX_SEGMENTS = (Segment.DECLARATION, Segment.MANEUVERS, Segment.FIGHT)

# The Battle Sequence this arc walks inside Fight Battles, named apart from the enum's order for
# the same reason the Attack Phase's sequence is.
_ONYX_BATTLE_SEGMENTS = (
    BattleSegment.ENGAGE,
    BattleSegment.COMBAT,
    BattleSegment.RESOLUTION,
    BattleSegment.AFTER_RESOLUTION,
)

# Onyx Edition / Shattered Empire: the ten legal Clan Alignments the rulebook enumerates. Naga is
# the same alignment as Akasha and resolves to it. Every other clan name a card carries -- minor
# clans, Ninja, Shadowlands, Toturi's Army, "Unaligned", "Imperial" -- is not an alignment here.
ONYX = Ruleset(
    name="onyx",
    arcs=("Onyx Edition",),
    clan_alignments=frozenset(
        {AKASHA, CRAB, CRANE, DRAGON, LION, MANTIS, PHOENIX, SCORPION, SPIDER, UNICORN}
    ),
    clan_aliases={NAGA: AKASHA},
    attack_segments=_ONYX_SEGMENTS,
    segment_names={
        Segment.DECLARATION: "Declaration Segment",
        Segment.MANEUVERS: "Maneuvers Segment",
        Segment.FIGHT: "Fight Battles",
    },
    lobby_timing=ActionTiming.OPEN,
    lobby_keywords=frozenset({keywords.POLITICAL}),
    favor_abilities=(
        FavorAbility(
            "discard_to_draw",
            ActionTiming.OPEN,
            "discard a Fate card to draw a card",
            active_seat_only=True,
            keywords=frozenset({keywords.POLITICAL}),
        ),
        FavorAbility(
            "send_attacker_home",
            ActionTiming.BATTLE,
            "move a target attacking enemy Personality home",
            keywords=frozenset({keywords.POLITICAL}),
        ),
    ),
    battle_segments=_ONYX_BATTLE_SEGMENTS,
    battle_segment_names={
        BattleSegment.ENGAGE: "Engage Segment",
        BattleSegment.COMBAT: "Combat Segment",
        BattleSegment.RESOLUTION: "Resolution Segment",
        BattleSegment.AFTER_RESOLUTION: "After Resolution",
    },
)

# Shattered Empire follows Onyx Edition. The engine models none of the rules differences between
# them yet, so it starts as a copy of Onyx. The two differ only in printings: a card whose text
# Shattered Empire rewrote registers its Onyx text under ``ONYX``'s name.
SHATTERED_EMPIRE = replace(ONYX, name="shattered_empire", arcs=("Shattered Empire",))

# The ruleset the engine plays under. Named once so no module decides for itself which arc is live.
ACTIVE = SHATTERED_EMPIRE


def ring_entry() -> RingEntry:
    """How the active ruleset puts a "Play after X" Ring into play."""
    return ACTIVE.ring_entry


class Scoped(Protocol):
    """A registration that may name the one ruleset it is in force under."""

    @property
    def ruleset(self) -> str | None: ...


def in_force(registered: Scoped, *, ruleset_name: str | None = None) -> bool:
    """Whether ``registered`` is read under one ruleset: every arc reads one naming none.

    Parameters
    ----------
    registered : :class:`~yasuki_core.ruleset.Scoped`
        An ability, Interrupt or trigger registration carrying a ``ruleset`` name or None.
    ruleset_name : str, optional
        The name of the ruleset asked about. Default the active ruleset's.
    """
    name = ACTIVE.name if ruleset_name is None else ruleset_name
    return registered.ruleset is None or registered.ruleset == name


# The pre-Gold rulebook, which granted four uses of the Favor rather than two and asked nothing
# alongside it for the draw. Gold Edition then removed them all, leaving every use to come from a
# card; the Onyx/ShE datasheet grants two again.
IMPERIAL = Ruleset(
    name="imperial",
    arcs=("Clan Wars", 'Hidden Emperor - "Jade"'),
    clan_alignments=SHATTERED_EMPIRE.clan_alignments,
    abilities_once_per_turn=False,
    lobby_keywords=frozenset({keywords.POLITICAL}),
    favor_abilities=(
        FavorAbility("draw", ActionTiming.LIMITED, "draw a Fate card"),
        FavorAbility(
            "restore_honor", ActionTiming.OPEN, "restore a Dishonored Personality to Honorable"
        ),
        FavorAbility(
            "send_unit_home", ActionTiming.BATTLE, "send a unit home from a battle, bowed"
        ),
        FavorAbility("prevent_honor_loss", ActionTiming.RESPONSE, "prevent a Family Honor loss"),
    ),
)
