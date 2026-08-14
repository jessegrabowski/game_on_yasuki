import re
from difflib import SequenceMatcher

# Reminder text restates a rulebook keyword the card does not own, printed because a player cannot
# look a keyword up mid-game. Keyed by keyword rather than by printed bracket: a card prints one
# sentence per keyword it carries, so a Loyal Naval Shugenja prints three in one bracket and keying
# by the bracket would need an entry per combination. A keyword is printed more than one way often
# enough that each entry lists every wording the corpus uses.
#
# A wording earns its place by naming its own keyword; a shared keyword among the cards printing it
# is coincidence, which a cycle of similar cards produces just as readily. Nothing here may be
# relaxed into a shape test either, since a card's own clarification is shaped identically —
# "(Nothing happens to the loser.)" reads exactly like a reminder and is not one. Both rules guard
# the same asymmetry: a missing wording leaves text visible in the traits, a wrong one deletes rules
# silently. Reminder text belonging to no keyword goes in UNKEYED_REMINDER_TEXT.
REMINDER_TEXT = {
    "Absent": (
        "Absent actions may be taken without presence.",
        "You may take Absent actions without presence.",
    ),
    "Armor": ("A Personality can only have one Armor.",),
    "Brash": ("The Defender may draw a card after a Brash card is assigned to attack.",),
    "Cavalry": (
        "Once per turn, as an Absent Engage, move your unbowed Personality in a Cavalry unit to this battlefield.",
        "Once per turn, as an Absent Engage, move your unbowed Personality in a Cavalry unit to this battle.",
        "Once per turn, as an Absent Engage, move your unbowed Personality in a Cavalry unit to the battle.",
    ),
    "Compassion": ("Compassion takes effect while you have fewer Provinces than anyone else.",),
    "Conqueror": ("A Conqueror's unit doesn't bow after battle.",),
    "Courage": (
        "Repeatable Interrupt: Discard a Courage card to give a Fear effect +2 or -2 strength.",
    ),
    "Courtesy": (
        "Courtesy traits do not take effect if you went first.",
        "Courtesy does not take effect if you went first.",
    ),
    "Destined": (
        "Draw a card after you Recruit a Destined card.",
        "Draw a card after your Destined card enters play.",
    ),
    "Discipline": (
        "You may pay 2 Gold to play this Discipline from your discard pile, then banish it after its action resolves.",
        "You may pay :g2: to play this Discipline from your discard pile, then banish it after its action resolves.",
        "Pay 2 Gold to play, then remove from the game, this Discipline in your discard.",
    ),
    "Duelist": ("Duelists win tied duels versus non-Duelists.",),
    "Duty": (
        "You may discard a card from your hand as an Open action to refill your face-up Province with your discarded, not dead, Duty card.",
    ),
    "Dynasty": ("You may only take Dynasty actions during your Dynasty Phase.",),
    "Elite": ("Elite cards contribute Force even if bowed.",),
    "Expendable": (
        "Draw a card after your Expendable card dies.",
        "Draw a card after your Expendable card is destroyed.",
    ),
    "Fortification": (
        "Fortifications attach to the Province from which they entered play.",
        "Fortifications attach, bowed, to the Province from which they entered play.",
    ),
    "Home": ("Home actions may be taken from home.",),
    "Honesty": (
        "Honesty traits are active when the card is face up.",
        "You may turn an Honesty card face-up as a Battle action.",
        "You have Honesty if any Honesty cards are face-up in your hand.",
    ),
    "Honor": (
        "Repeatable Interrupt: Once per action, discard an Honor card to increase or reduce an Honor gain or loss by 1.",
        "Repeatable Interrupt: Discard an Honor card to give an Honor gain or loss +1 or -1.",
    ),
    "Invest": (
        "After this card enters play, you may also pay the Invest cost to get the effect, once.",
        "Entering play, permanently increase the Gold Cost by the Invest cost to get the effect.",
    ),
    "Kensai": (
        "Kensai may attach two Weapons, as long as neither is Two-Handed.",
        "Kensai may attach two One-Handed Weapons.",
    ),
    "Kharmic": (
        "Repeatable Limited, :g2:: Discard a Kharmic card from your Province and refill it face-up.",
        "Repeatable Limited, :g2:: Discard a Kharmic card to draw a card.",
        "Limited, :g2:: Discard a Kharmic card from your hand to draw a card.",
    ),
    "Legacy": (
        "Once per turn as a Dynasty, remove a card in your hand from the game to search your deck and Provinces for a Legacy Holding and Recruit it.",
    ),
    "Loyal": ("Loyal Personalities will not join other Clans.",),
    "Naval": (
        "Once a turn, the Attacker gets the first Battle action, if it's from a Naval Personality's unit.",
    ),
    "Overconfident": (
        "Each other player may draw a card after an Overconfident card enters or leaves play.",
    ),
    "Renew": ("When a card with Renew enters play from a Province, refill its Province face-up.",),
    "Reserve": (
        "If it would be opposed, you may Equip or Recruit a Reserve card as a Battle action.",
        "You may Recruit a Reserve Personality, if they would be opposed, as an Absent Battle action.",
        "You may Equip a Reserve attachment, if it would be opposed, as a Battle action.",
    ),
    "Resilient": ("Once per game per card, a Resilient card does not die in battle resolution.",),
    "Shugenja": (
        "Shugenja may attach and cast Spells.",
        # Printed on a Follower Shugenja, which cannot do what a Personality Shugenja can.
        "Followers cannot attach or cast Spells.",
    ),
    "Stalwart": ("Stalwart cards negate their first bowing each turn by other players' cards.",),
    "Tactician": (
        "Battle: Discard a card to give this Tactician a Force bonus equal to the card's Focus Value.",
    ),
    "Tireless": (
        "Tireless actions may be taken even while bowed.",
        "Tireless actions can be taken even while bowed.",
    ),
    "Unstoppable": ("Other players cannot Interrupt Unstoppable actions.",),
    "Weapon": ("A Personality can only have one Weapon.",),
}

# Reminder text belonging to no keyword: it spells out a consequence the rules already produce, so
# the engine derives it rather than reading it. Kept apart from REMINDER_TEXT because that map is
# also the keyword glossary, and there is no keyword to look these up under.
UNKEYED_REMINDER_TEXT = (
    # On Poisoned Weapon, after the -3C it applies: the duel ending is what the rules do when a
    # duelist dies, not something the card decides.
    "If this destroys the Personality, the duel ends immediately without resolution.",
    # Restated from data the card already carries: its alignment, its uniqueness, its identity.
    "This Personality is Unaligned.",
    "This is not an Affection token for Iweko Miaka.",
    "Multiple copies of this card's traits are not cumulative.",
    # A rule of attachment, true of every attached card.
    "This card is controlled by the controller of the Personality it is attached to.",
    # The Siege sets are their own format, played on Territory and Clock cards that no other set
    # uses. These note that format's rules rather than anything the card decides.
    "Cannot be conquered.",
    "Cannot be destroyed.",
    "This is always the last card of the deck and cannot be discarded.",
    "The Rokugani players lose the game.",
    "The Imperial District may now be destroyed.",
    "If you destroy your Warrior, draw a card.",
    # The draft stronghold printed on the back of an advertisement card names the other face's
    # stats. The two faces are linked in the database, so the note carries nothing the data lacks.
    "This has +1PS and +2GP if you didn't go first.",
    "This has -1PS and -2GP if you went first.",
    # Fight on Your Back fuses the Courage and Honor reminders into one sentence, so it belongs to
    # neither keyword on its own.
    "Repeatable Interrupt: Discard a Courage card to give a Fear effect +2 or -2 strength or discard an Honor card to give an Honor gain or loss +1 or -1.",
)

# Reminders that name a card or a number cannot be listed as fixed wordings. Each pattern has to
# describe a whole sentence, so a card's own prose cannot satisfy one by containing it.
REMINDER_PATTERNS = {
    "Discipline": (
        r"Pay \d+ Gold to play, then remove from the game, this Discipline in your discard\.?",
    ),
    # Uniqueness is a property of the card in the database, so saying a card lacks it adds nothing.
    "Unique": (r"[A-Z][\w'’ ]* is not Unique\.?",),
}
# Could be reminder text: it opens like a sentence rather than a qualifier, since "(if able)" and
# "(this turn)" are lowercase fragments. Only ever used to rule a parenthetical out — what rules one
# in is its wording, because a card's own clarification opens the same way.
_MAYBE_REMINDER = re.compile(r"\(\s*[A-Z][^()]*\)")


def _reminder_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip(" ()")).strip().casefold()


_REMINDERS = frozenset(
    _reminder_key(t)
    for t in (*(w for wordings in REMINDER_TEXT.values() for w in wordings), *UNKEYED_REMINDER_TEXT)
)
_REMINDER_MATCHERS = tuple(
    re.compile(pattern) for patterns in REMINDER_PATTERNS.values() for pattern in patterns
)
# The same rule is printed more than one way — an Expendable card "dies" on one card and "is
# destroyed" on another, and a period sometimes falls outside the bracket — so a sentence is matched
# by resemblance rather than equality. Across the corpus a card's own clarification scores at most
# 0.39 against the nearest reminder while the known variants score 0.90 and up.
_RESEMBLANCE = 0.80
_SENTENCE_END = re.compile(r"(?<=\.)\s+")


def is_reminder(body: str) -> bool:
    """Whether a parenthetical is entirely rulebook reminder text.

    Every sentence has to be a known keyword's reminder, because a card prints one per keyword it
    carries and may print its own clarification beside them.
    """
    if not _MAYBE_REMINDER.fullmatch(body.strip()):
        return False
    sentences = [s for s in _SENTENCE_END.split(body.strip(" ()")) if s.strip()]
    return bool(sentences) and all(_matches_a_reminder(s) for s in sentences)


def _matches_a_reminder(sentence: str) -> bool:
    key = _reminder_key(sentence)
    if key in _REMINDERS:
        return True
    if any(pattern.fullmatch(sentence.strip()) for pattern in _REMINDER_MATCHERS):
        return True
    return any(SequenceMatcher(None, key, known).ratio() >= _RESEMBLANCE for known in _REMINDERS)
