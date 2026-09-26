from enum import Enum

# Proxies the rulebook itself puts on every table, as opposed to the tokens a card creates. The
# Imperial Favor belongs to no creator card, so ``card_creates`` has no honest row for it.
IMPERIAL_FAVOR_ID = "imperial_favor"
# The proxies a held thing is represented by, which the sandbox may spawn and any seat may clear:
# the Favor alone. A proxy the rules engine deals into a seat's rulebook zone is not among them.
RULEBOOK_PROXY_IDS = (IMPERIAL_FAVOR_ID,)
# The Cycle rulebook ability is activated from a proxy each seat holds in its rulebook zone.
CYCLE_PROXY_ID = "cycle"
# The Legacy rulebook ability is activated from a proxy each seat holds in its rulebook zone.
LEGACY_PROXY_ID = "legacy"
# The rulebook Favor abilities are activated from a proxy each seat holds in its rulebook zone, one
# per arc family. Neither is the Favor card a holder's hand shows, which is ``IMPERIAL_FAVOR_ID``.
ONYX_FAVOR_PROXY_ID = "onyx_favor"
PRE_GOLD_FAVOR_PROXY_ID = "pre_gold_favor"


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
