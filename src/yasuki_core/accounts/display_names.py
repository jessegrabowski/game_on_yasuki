import secrets

# A new account's default handle is generated, never taken from the Google profile, so a player
# whose Google name is their real name doesn't leak it. Adjective + clan/role + number, CamelCase.
_ADJECTIVES = (
    "Stoic",
    "Bold",
    "Cunning",
    "Honorable",
    "Swift",
    "Steadfast",
    "Fierce",
    "Wily",
    "Noble",
    "Grim",
    "Radiant",
    "Resolute",
    "Vigilant",
    "Humble",
    "Daring",
    "Serene",
    "Iron",
    "Jade",
    "Crimson",
    "Shadow",
    "Quiet",
    "Relentless",
    "Gallant",
    "Patient",
)
_NOUNS = (
    "Crane",
    "Scorpion",
    "Dragon",
    "Phoenix",
    "Lion",
    "Crab",
    "Unicorn",
    "Mantis",
    "Ronin",
    "Samurai",
    "Shugenja",
    "Tactician",
    "Daimyo",
    "Sensei",
    "Duelist",
    "Magistrate",
    "Courtier",
    "Berserker",
    "Sentinel",
    "Wanderer",
    "Yojimbo",
    "Tatsu",
    "Kitsune",
    "Hatamoto",
)


def random_display_name() -> str:
    """Return a random CamelCase handle: an adjective, a clan/role noun, and a 3-digit number.

    The privacy-preserving default for a fresh account, so signing in with Google never seeds the
    display name from the player's real name.
    """
    return f"{secrets.choice(_ADJECTIVES)}{secrets.choice(_NOUNS)}{secrets.randbelow(900) + 100}"
