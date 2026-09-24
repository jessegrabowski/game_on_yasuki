from enum import Enum

# Proxies the rulebook itself puts on every table, as opposed to the tokens a card creates. The
# Imperial Favor belongs to no creator card, so ``card_creates`` has no honest row for it.
IMPERIAL_FAVOR_ID = "imperial_favor"
# The proxies a held thing is represented by, which the sandbox may spawn and any seat may clear:
# the Favor alone. A rulebook ability's proxy (``KHARMIC_PROXY_ID``) is dealt by the rules engine
# into a seat's rulebook zone and is not among them.
RULEBOOK_PROXY_IDS = (IMPERIAL_FAVOR_ID,)
# The Kharmic rulebook abilities are activated from a proxy card each seat holds in its rulebook
# zone, so cards that name them key on this id.
KHARMIC_PROXY_ID = "kharmic"


class Side(str, Enum):
    FATE = "FATE"
    DYNASTY = "DYNASTY"
    STRONGHOLD = "STRONGHOLD"


class Element(str, Enum):
    AIR = "Air"
    EARTH = "Earth"
    FIRE = "Fire"
    WATER = "Water"
    VOID = "Void"


class Timing(str, Enum):
    OPEN = "Open"
    LIMITED = "Limited"
    BATTLE = "Battle"
    ENGAGE = "Engage"
    REACTION = "Reaction"
    INTERRUPT = "Interrupt"
    DYNASTY = "Dynasty"


class AttachmentType(str, Enum):
    ITEM = "Item"
    FOLLOWER = "Follower"
    SPELL = "Spell"


class DynastyType(str, Enum):
    PERSONALITY = "Personality"
    HOLDING = "Holding"
    EVENT = "Event"
    REGION = "Region"
    CELESTIAL = "Celestial"


class FateType(str, Enum):
    STRATEGY = "Strategy"
    RING = "Ring"
    ANCESTOR = "Ancestor"
    ITEM = "Item"
    FOLLOWER = "Follower"
    SPELL = "Spell"


class PreGameType(str, Enum):
    STRONGHOLD = "Stronghold"
    SENSEI = "Sensei"
    WIND = "Wind"


class SpecialType(str, Enum):
    CLOCK = "Clock"
    TERRITORY = "Territory"
