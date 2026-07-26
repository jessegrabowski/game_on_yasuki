from dataclasses import dataclass, field


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
    """

    clan_alignments: frozenset[str]
    clan_aliases: dict[str, str] = field(default_factory=dict)
    off_clan_surcharge: int = 2

    def alignment(self, clan_name: str) -> str | None:
        """The canonical Clan Alignment slug ``clan_name`` denotes, or None when it is not a legal
        alignment in this ruleset. Resolves aliases (Naga -> Akasha) before the membership test, so
        equal alignments always share one slug."""
        slug = normalize_clan(clan_name)
        slug = self.clan_aliases.get(slug, slug)
        return slug if slug in self.clan_alignments else None


# Onyx Edition / Shattered Empire: the ten legal Clan Alignments the rulebook enumerates. Naga is the
# same alignment as Akasha and resolves to it. Every other clan name a card carries -- minor clans,
# Ninja, Shadowlands, Toturi's Army, "Unaligned", "Imperial" -- is not an alignment here.
SHATTERED_EMPIRE = Ruleset(
    clan_alignments=frozenset(
        {
            "akasha",
            "crab",
            "crane",
            "dragon",
            "lion",
            "mantis",
            "phoenix",
            "scorpion",
            "spider",
            "unicorn",
        }
    ),
    clan_aliases={"naga": "akasha"},
)
