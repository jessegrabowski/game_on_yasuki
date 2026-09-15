# The keywords the rules engine reasons about, spelled once. A keyword is card text: it has to match
# the card database exactly, and a misspelling is a rule that silently never fires. So the
# vocabulary lives in one module with a test behind it rather than as a literal at each call site.
# A keyword earns a name here when engine code reads it; the thousand-odd keywords no rule asks
# after stay in the card data.
#
# Clan words are the trap, and the two columns read them the opposite way round. As a *keyword*,
# "Dragon" is the creature (70 cards: Air Dragon, Celestial Dragon, Nonhuman, and Unaligned at
# that) while "Dragon Clan" is the clan (409 cards); as a *clan* it is the other way, and the clans
# column spells the clan plainly as "Dragon". So a card that asks after Dragon Clan membership wants
# the keyword "Dragon Clan", never "Dragon". A card that asks whether its controller plays
# Dragon wants ``is_clan`` and the clan vocabulary in ``yasuki_core.ruleset``, not a keyword at all.
# ``test_keywords`` fails a bare clan word named here whose "<X> Clan" twin exists in the card data.

# --- Keywords the rulebook itself reads ---

# No card in a Conqueror Personality's unit bows before returning home after a battle's resolution
# (CR, Conqueror). It is the Personality's keyword rather than the unit's: a Follower carrying it
# exempts nobody, not even itself.
CONQUEROR = "Conqueror"

# The designator marking an ability a Favor action however its cost is settled, for a card whose
# alternate cost would otherwise decide it (ShE datasheet, The Favor Icon).
FAVOR = "Favor"

# A Holding carrying this attaches to the Province it entered play from, or to one its controller
# picks if it came from elsewhere, and is destroyed with it (CR, Fortification).
FORTIFICATION = "Fortification"

# A Kensai Personality may attach two Weapons rather than one (CR, Kensai).
KENSAI = "Kensai"

# A Strategy that puts itself into play and stays there. A player holds one at a time unless a
# card says otherwise (ShE datasheet, Edicts).
EDICT = "Edict"

# The boldface keyword marking a card the Courage rulebook Interrupt can discard to move a Fear
# effect by 2 (ShE datasheet, Courage Rulebook ability).
COURAGE = "Courage"

# The boldface keyword marking a card the Honor rulebook Interrupt can discard to move an Honor
# gain or loss by 1 (ShE datasheet, Honor Rulebook ability).
HONOR = "Honor"

# The boldface keyword marking a card the Kharmic rulebook abilities can spend.
KHARMIC = "Kharmic"

# The boldface keyword marking a card the Legacy rulebook ability can search out.
LEGACY = "Legacy"

# Refills a card's vacated Province face-up when it enters play (rather than the usual face-down),
# so the next card is recruitable the same turn.
RENEW = "Renew"

# A Spell will only attach to a Shugenja Personality, and casts only while attached to one (CR,
# Spell). A rule about the Spell card type rather than a keyword any card reads off a Shugenja.
SHUGENJA = "Shugenja"

# Cards carrying this accrue and receive seeded Sincerity tokens.
SINCERITY = "Sincerity"

# A Two-Handed Weapon is exclusive: its Personality may hold no other, even a Kensai (CR,
# Two-Handed).
TWO_HANDED = "Two-Handed"

# An Item answering to the Weapon rules: the per-Personality limit and Two-Handed exclusivity.
WEAPON = "Weapon"

# --- Keywords individual cards ask after ---

CAVALRY = "Cavalry"
COMMANDER = "Commander"
COURTIER = "Courtier"
FARM = "Farm"
JADE = "Jade"
MARKET = "Market"
MERCHANT_CARAVAN = "Merchant Caravan"
NAGA = "Naga"
# "Human" on a card is not a keyword: it names a Personality or Follower without this one
# (CR, Human), so a card asking after Humans reads Nonhuman and negates it.
NONHUMAN = "Nonhuman"
PORT = "Port"
SAMURAI = "Samurai"
SHADOWLANDS = "Shadowlands"
YOJIMBO = "Yojimbo"
# The clan, not the creature: the "<X> Clan" column, per the note at the top of this module.
TANUKI_CLAN = "Tanuki Clan"
# Ability keywords: printed ahead of a designator ("Political Battle:"), authored on the Ability
# that carries them, and checked against the card text by the registration audit.
BUSHIDO_VIRTUE = "Bushido Virtue"
DUELIST = "Duelist"
EARTH = "Earth"
ECONOMIC = "Economic"
IAIJUTSU = "Iaijutsu"
MAHO = "Maho"
POLITICAL = "Political"
