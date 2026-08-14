import re
from dataclasses import dataclass

from yasuki_core.install.reminders import is_reminder

# The designators are a closed set; the CR names them and says they are not keywords. Everything
# else in an ability's bold prefix is an ability keyword, which the CR inherits up to the card:
# "a Strategy with a Political ability is a Political Strategy".
DESIGNATORS = frozenset(
    {"Open", "Battle", "Limited", "Engage", "Dynasty", "Interrupt", "Reaction", "Response"}
)
# Modifiers say how an ability behaves or how far it reaches. They are a closed set, and unlike a
# keyword nothing in the game refers to one as a thing: no card destroys "a Tireless" the way cards
# destroy "a Terrain". They therefore never rise to the card.
MODIFIERS = frozenset({"Absent", "Home", "Remote", "Repeatable", "Tireless", "Unstoppable"})
# Two words that name one keyword. "Virtue" never opens a prefix on its own — it is always a Dark
# Virtue or a Bushido Virtue — so splitting on spaces would invent three keywords out of one.
COMPOUND_KEYWORDS = ("Bushido Virtue", "Dark Virtue")
# The traits the rules name, each written "Name: effect" and each its own unit of behavior.
NAMED_TRAITS = ("Compassion", "Courtesy", "Discipline", "Honesty", "Invest", "Sincerity", "Yu")
# A duel's focus step names its trait the same way, but punctuates it with a comma instead of a
# colon. It can also follow another classifier — "Honesty: As a Focus Effect, …" — so like the
# named traits it only opens a trait where it opens a segment.
FOCUS_EFFECT = "As a Focus Effect,"

_ICON_BODY = r"[A-Za-z0-9_*]+:"
_ICON = f":{_ICON_BODY}"
_DESIG = "|".join(sorted(DESIGNATORS))
_TAGS = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>")

# [keywords] [designator(/designator)] [, cost [or cost]] :
_ANCHOR = re.compile(
    rf"(?P<kw>(?:[A-Z][a-z]+\s+){{0,3}})"
    rf"(?P<desig>(?:{_DESIG})(?:\s*/\s*(?:{_DESIG}))?)"
    rf"(?P<cost>(?:\s*,?\s*(?:{_ICON})(?:\s+or\s+{_ICON})?)*)"
    rf"\s*:"
)
# A cost with no designator is still an ability — the ":bow:: Produce 2 Gold" production template.
_COST_ONLY = re.compile(rf"(?:(?<=^)|(?<=\.))\s*(?P<cost>{_ICON}(?:\s+or\s+{_ICON})?)\s*:")
_NAMED = re.compile(
    rf"(?=\b(?:{'|'.join(NAMED_TRAITS)})\b\s*(?:{_ICON})?\s*:|{re.escape(FOCUS_EFFECT)})"
)
# A prefix only opens an ability where it opens a segment. Mid-sentence the same words are prose —
# "if your Wind is The Kanpeki Dynasty:" names a card, and the colon is the sentence's own. A trait
# classifier is the exception: it qualifies what follows rather than being prose, so "Honesty:
# Interrupt, :X:: …" is a classified ability, not a trait that happens to contain one.
_SEGMENT_OPEN = re.compile(
    rf"(?:[.”]|\.\))\s*$|^\s*(?:(?:{'|'.join(NAMED_TRAITS)})\s*(?:{_ICON})?\s*:|{re.escape(FOCUS_EFFECT)})\s*$"
)
# A sentence ends at "." or at a paren closing one (".)"), never at a paren closing a clause.
_SENTENCE = re.compile(r"(?:(?<=[.\u201d])|(?<=\.\)))\s+(?=[A-Z:\u201c(])")
# A sentence that cannot stand alone continues the one before it. What makes it dependent is a
# subject or object with no antecedent of its own: a bare pronoun, an imperative acting on one
# ("Discard it at the end of the turn"), or a connective.
_PRONOUN = r"it|them|they|him|her|he|she"
_CONTINUES = re.compile(
    r"^(?:\(.*\)\.?$"
    r"|(?:Then|Otherwise)\b"
    rf"|(?:{_PRONOUN})\b"
    rf"|[A-Za-z]+\s+(?:{_PRONOUN})\b"
    rf"|You may\b(?=[^.]*\b(?:{_PRONOUN})\b))",
    re.I,
)
# Any parenthetical, markup and all. Reminder text is recognised by its wording, so the candidate
# has to be found before the tags come off.
_PAREN = re.compile(r"\s*\([^()]*\)")


@dataclass(frozen=True, slots=True)
class Ability:
    """One ability of a card: when it may be used, what it is classified as, and what it costs.

    ``keywords`` classify the ability and rise to the card that holds it — the CR reads a Strategy
    with a Political ability as a Political Strategy. ``modifiers`` change how the ability behaves
    and stay where they are printed.
    """

    designators: tuple[str, ...]
    keywords: tuple[str, ...]
    modifiers: tuple[str, ...]
    cost: str | None
    text: str


@dataclass(frozen=True, slots=True)
class TextBox:
    """A card's text box decomposed into the traits it states and the abilities it grants.

    Reminder text is kept apart rather than discarded: it is not behavior the card owns, so it is
    not a trait, but it is printed on the card and a reader may still want it.
    """

    traits: tuple[str, ...] = ()
    abilities: tuple[Ability, ...] = ()
    reminders: tuple[str, ...] = ()


def strip_markup(text: str) -> str:
    """The text box as plain prose.

    Tags become a space so words never fuse, then the space a tag leaves in front of punctuation is
    taken back out — ``<b>Tireless</b>.`` must read "Tireless." and ``<b>Battle</b>:`` must read
    "Battle:". A colon that opens an icon keeps the space in front of it, so ``:pearl:`` stays
    apart from the word before it. An opening quote hugs what it quotes.

    Parameters
    ----------
    text : str
        A card's rules text, with or without its markup.

    Returns
    -------
    plain : str
        The same text with the tags removed and the spacing they left repaired.
    """
    plain = re.sub(r"\s{2,}", " ", _TAGS.sub(" ", text))
    plain = re.sub(r"\s+([.,;!?\u201d])", r"\1", plain)
    plain = re.sub(rf"\s+:(?!{_ICON_BODY})", ":", plain)

    def hug(match: re.Match) -> str:
        return '"' if plain[: match.start()].count('"') % 2 == 0 else match.group(0)

    return re.sub(r'"\s+(?=\S)', hug, plain).strip()


def _outside_parens(text: str, pos: int) -> bool:
    """Whether ``pos`` falls outside parentheses — a bracket holding two sentences is one aside, so
    cutting between them would leave both halves unclosed."""
    before = text[:pos]
    return before.count("(") == before.count(")")


def _segments(text: str) -> list[str]:
    """The card's printed lines. A break inside a parenthetical does not start a line: the aside
    simply runs across two of them, and cutting there leaves both halves unclosed."""
    out, start = [], 0
    for match in _BREAK.finditer(text):
        if _outside_parens(text, match.start()):
            out.append(text[start : match.start()])
            start = match.end()
    out.append(text[start:])
    return out


def _outside_quotes(text: str, pos: int) -> bool:
    """Whether ``pos`` falls outside quotation marks — inside them the text is granted, not the
    card's own, so no split may happen there."""
    return text[:pos].count('"') % 2 == 0


def _opens_segment(plain: str, pos: int) -> bool:
    """Whether ``pos`` begins a segment — nothing before it, or a finished sentence."""
    before = plain[:pos]
    return not before.strip() or bool(_SEGMENT_OPEN.search(before))


def _anchors(plain: str) -> list[re.Match]:
    """Every ability opening in ``plain``, in order, with overlaps dropped."""
    hits = sorted(
        (
            m
            for m in [*_ANCHOR.finditer(plain), *_COST_ONLY.finditer(plain)]
            if _outside_quotes(plain, m.start()) and _opens_segment(plain, m.start())
        ),
        key=lambda m: m.start(),
    )
    return [m for i, m in enumerate(hits) if i == 0 or m.start() >= hits[i - 1].end()]


def _abilities(text: str) -> list[Ability]:
    """Abilities segment on ``<br>`` exactly as traits do, so a break the card prints is a boundary
    the prefix match can see."""
    out: list[Ability] = []
    for segment in _segments(text):
        out.extend(_segment_abilities(strip_markup(segment)))
    return out


def _segment_abilities(plain: str) -> list[Ability]:
    """The abilities of one segment, each running until the next one opens."""
    hits = _anchors(plain)
    out: list[Ability] = []
    for i, match in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(plain)
        groups = match.groupdict()
        keywords, modifiers = _classify_prefix(_classifying_words(groups.get("kw")))
        out.append(
            Ability(
                designators=tuple(_words(groups.get("desig"))),
                keywords=keywords,
                modifiers=modifiers,
                cost=(groups.get("cost") or "").strip(" ,") or None,
                text=plain[match.end() : end].strip(),
            )
        )
    return out


def _words(part: str | None) -> list[str]:
    """The words of one part of a prefix, with its icons and separators dropped."""
    return [w for w in re.split(r"[,/]|\s+", re.sub(_ICON, " ", part or "")) if w.strip()]


def _classifying_words(part: str | None) -> list[str]:
    """The words of a prefix that classify the ability, so without the "or" that joins its
    alternative costs."""
    return [w for w in _words(part) if w.isalpha() and w.lower() != "or"]


def _classify_prefix(words: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Sort a prefix's words into the keywords it classifies the ability as and the modifiers it
    carries, joining the two-word keywords back together first."""
    joined, i = [], 0
    while i < len(words):
        pair = " ".join(words[i : i + 2])
        if pair in COMPOUND_KEYWORDS:
            joined.append(pair)
            i += 2
        else:
            joined.append(words[i])
            i += 1
    return (
        tuple(w for w in joined if w not in MODIFIERS),
        tuple(w for w in joined if w in MODIFIERS),
    )


def ability_keywords(text: str) -> tuple[str, ...]:
    """The keywords a card inherits from its own abilities, in the order they are printed.

    The CR inherits upward only: an ability's keyword classifies the card that holds it, while the
    card's printed keywords say nothing about its abilities.

    Parameters
    ----------
    text : str
        A card's rules text.

    Returns
    -------
    keywords : tuple of str
        Each inherited keyword once, in printed order. Empty when the card has no abilities.
    """
    return tuple(
        dict.fromkeys(
            keyword for ability in split_text_box(text).abilities for keyword in ability.keywords
        )
    )


def _traits(text: str) -> list[str]:
    traits: list[str] = []
    for segment in _segments(text):
        plain = strip_markup(segment)
        stop = min([m.start() for m in _anchors(plain)], default=len(plain))
        lead = plain[:stop].strip().rstrip(":").strip()
        if not lead:
            continue
        for chunk in _split_named(lead):
            traits.extend(_merge_continuations(_split_sentences(chunk)))
    return traits


def _split_named(chunk: str) -> list[str]:
    """Split where a named trait opens a new one — at the start of a block or after a sentence end.
    Mid-sentence the word names a trait rather than opening one, as in "…have Discipline :g2:."."""
    starts = [
        m.start()
        for m in _NAMED.finditer(chunk)
        if (m.start() == 0 or chunk[max(0, m.start() - 2) : m.start()].strip().endswith("."))
        and _outside_quotes(chunk, m.start())
    ]
    bounds = sorted({0, *starts, len(chunk)})
    return [chunk[a:b].strip() for a, b in zip(bounds, bounds[1:]) if chunk[a:b].strip()]


def _split_sentences(chunk: str) -> list[str]:
    cuts = [
        m.end()
        for m in _SENTENCE.finditer(chunk)
        if _outside_quotes(chunk, m.start()) and _outside_parens(chunk, m.start())
    ]
    bounds = sorted({0, *cuts, len(chunk)})
    return [t for t in (chunk[a:b].strip() for a, b in zip(bounds, bounds[1:])) if t]


def _merge_continuations(chunks: list[str]) -> list[str]:
    """Fold a chunk that cannot stand alone into the one before it."""
    out: list[str] = []
    for chunk in chunks:
        if out and _CONTINUES.match(chunk):
            out[-1] = f"{out[-1]} {chunk}"
        else:
            out.append(chunk)
    return out


def _pull_reminders(text: str) -> tuple[str, list[str]]:
    """The text without its rulebook reminders, and the reminders taken out of it."""
    found: list[str] = []

    def drop(match: re.Match) -> str:
        body = strip_markup(match.group(0))
        if not is_reminder(body):
            return match.group(0)
        found.append(body.strip())
        return ""

    return _PAREN.sub(drop, text), found


def split_text_box(text: str) -> TextBox:
    """Decompose a card's text box into its traits and abilities.

    ``<br>`` is honored as a hard boundary while it is in the data, but nothing depends on markup:
    abilities are found by their designator and traits fall back to sentence boundaries, so the
    same split holds once the tags are gone.

    Parameters
    ----------
    text : str
        A card's rules text, with or without its ``<b>``, ``<i>`` and ``<br>`` markup.

    Returns
    -------
    box : TextBox
        The card's traits, abilities and rulebook reminder text.
    """
    without, reminders = _pull_reminders(text)
    return TextBox(
        traits=tuple(_traits(without)),
        abilities=tuple(_abilities(without)),
        reminders=tuple(reminders),
    )
