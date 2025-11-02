from enum import Enum


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
    ATTACHMENT = "Attachment"
    SENSEI = "Sensei"
    RING = "Ring"
