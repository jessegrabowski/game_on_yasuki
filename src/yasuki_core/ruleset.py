from dataclasses import dataclass, field

from yasuki_core.engine.rules.state import BattleSegment, Segment


def normalize_clan(name: str) -> str:
    """The comparison key for a clan name: lowercased, with a trailing ``" Clan"`` dropped and
    surrounding whitespace stripped, so ``"Crab Clan"``, ``"Crab"``, and ``"crab"`` all compare
    equal."""
    return name.strip().lower().removesuffix(" clan")


@dataclass(frozen=True, slots=True)
class Ruleset:
    """The arc-specific rules constants the engine reads. Bundling them behind one object lets a
    later arc's ruleset be swapped in wholesale rather than editing scattered literals.

    Attributes
    ----------
    clan_alignments : frozenset of str
        The legal Clan Alignments, as canonical :func:`normalize_clan` slugs. A card's clan counts
        toward alignment only if it resolves into this set; every other clan name is unaligned.
    clan_aliases : dict mapping str to str
        Alternate clan slugs that resolve to a canonical member of ``clan_alignments`` (e.g. Naga is
        the same alignment as Akasha in this arc). Applied before the membership test. Default empty.
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
    """

    clan_alignments: frozenset[str]
    clan_aliases: dict[str, str] = field(default_factory=dict)
    off_clan_surcharge: int = 2
    honor_victory_at: int = 40
    dishonor_loss_at: int = -20
    attack_segments: tuple[Segment, ...] = ()
    segment_names: dict[Segment, str] = field(default_factory=dict)
    battle_segments: tuple[BattleSegment, ...] = ()
    battle_segment_names: dict[BattleSegment, str] = field(default_factory=dict)

    def segment_name(self, segment: Segment) -> str:
        """What this arc calls ``segment``.

        Raises
        ------
        KeyError
            If this arc does not walk ``segment``, which is a segment the engine reached under a
            ruleset that has no name for it — a wiring error rather than something to paper over.
        """
        return self.segment_names[segment]

    def battle_segment_name(self, segment: BattleSegment) -> str:
        """What this arc calls ``segment`` of a battle.

        Raises
        ------
        KeyError
            If this arc does not walk ``segment``, which is a segment the engine reached under a
            ruleset that has no name for it — a wiring error rather than something to paper over.
        """
        return self.battle_segment_names[segment]

    def alignment(self, clan_name: str) -> str | None:
        """The canonical Clan Alignment slug ``clan_name`` denotes, or None when it is not a legal
        alignment in this ruleset. Resolves aliases (Naga -> Akasha) before the membership test, so
        equal alignments always share one slug."""
        slug = normalize_clan(clan_name)
        slug = self.clan_aliases.get(slug, slug)
        return slug if slug in self.clan_alignments else None


# The clans the engine names, as canonical :func:`normalize_clan` slugs. A clan is card text like a
# keyword is, so it is spelled once here rather than at each call site — and here rather than beside
# the keywords because which of these count as Clan Alignments is arc config, and a ruleset below
# builds its set from these names so the two cannot drift.
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
# Earlier arcs walk a different sequence — the Cavalry Maneuvers segment between Maneuvers and the
# battles is the one that will bring this to a head. Adding it is three edits: a member on
# :class:`~yasuki_core.engine.rules.state.Segment`, a place in that arc's ``attack_segments``, and a
# name in its ``segment_names``. Nothing reads the enum's declaration order, so no arc inherits
# another's sequence.
_SHATTERED_EMPIRE_SEGMENTS = (Segment.DECLARATION, Segment.MANEUVERS, Segment.FIGHT)

# The Battle Sequence this arc walks inside Fight Battles, named apart from the enum's order for
# the same reason the Attack Phase's sequence is.
_SHATTERED_EMPIRE_BATTLE_SEGMENTS = (
    BattleSegment.ENGAGE,
    BattleSegment.COMBAT,
    BattleSegment.RESOLUTION,
    BattleSegment.AFTER_RESOLUTION,
)

# Onyx Edition / Shattered Empire: the ten legal Clan Alignments the rulebook enumerates. Naga is the
# same alignment as Akasha and resolves to it. Every other clan name a card carries -- minor clans,
# Ninja, Shadowlands, Toturi's Army, "Unaligned", "Imperial" -- is not an alignment here.
SHATTERED_EMPIRE = Ruleset(
    clan_alignments=frozenset(
        {AKASHA, CRAB, CRANE, DRAGON, LION, MANTIS, PHOENIX, SCORPION, SPIDER, UNICORN}
    ),
    clan_aliases={NAGA: AKASHA},
    attack_segments=_SHATTERED_EMPIRE_SEGMENTS,
    segment_names={
        Segment.DECLARATION: "Declaration Segment",
        Segment.MANEUVERS: "Maneuvers Segment",
        Segment.FIGHT: "Fight Battles",
    },
    battle_segments=_SHATTERED_EMPIRE_BATTLE_SEGMENTS,
    battle_segment_names={
        BattleSegment.ENGAGE: "Engage Segment",
        BattleSegment.COMBAT: "Combat Segment",
        BattleSegment.RESOLUTION: "Resolution Segment",
        BattleSegment.AFTER_RESOLUTION: "After Resolution",
    },
)

# The ruleset the engine plays under. Named once so no module decides for itself which arc is live.
ACTIVE = SHATTERED_EMPIRE
