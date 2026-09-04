from enum import Enum

# Proxies the rulebook itself puts on every table, as opposed to the tokens a card creates. The
# Imperial Favor belongs to no creator card, so ``card_creates`` has no honest row for it.
IMPERIAL_FAVOR_ID = "imperial_favor"
RULEBOOK_PROXY_IDS = (IMPERIAL_FAVOR_ID,)


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
