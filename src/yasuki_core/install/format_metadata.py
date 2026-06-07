# The one curated source mapping each legality format to its story arc and a short search alias.
# `arc` joins to l5r_sets.arc so the format's chronological position derives from the arc's earliest
# set release (no dates are hardcoded here); arc=None marks formats outside the storyline timeline.
# `block` is the single-word alias a search can use (`format:diamond`). This replaces the previously
# duplicated order/alias constants; consumers read the resulting formats.legal_from / block.
FORMAT_METADATA: dict[str, dict[str, str | None]] = {
    "Clan Wars (Imperial)": {"arc": "Clan Wars", "block": "imperial"},
    "Hidden Emperor (Jade)": {"arc": 'Hidden Emperor - "Jade"', "block": "jade"},
    "Four Winds (Gold)": {"arc": 'Four Winds - "Gold"', "block": "gold"},
    "Rain of Blood (Diamond)": {"arc": 'Rain of Blood - "Diamond"', "block": "diamond"},
    "Age of Enlightenment (Lotus)": {"arc": 'Age of Enlightenment - "Lotus"', "block": "lotus"},
    "Race for the Throne (Samurai)": {"arc": 'Race for the Throne - "Samurai"', "block": "samurai"},
    "Destroyer War (Celestial)": {"arc": 'Destroyer War - "Celestial"', "block": "celestial"},
    "Age of Conquest (Emperor)": {"arc": 'Age of Conquest - "Emperor"', "block": "emperor"},
    "A Brother's Destiny (Ivory Edition)": {
        "arc": 'A Brother\'s Destiny - "Ivory"',
        "block": "ivory",
    },
    "A Brother's Destiny (Twenty Festivals)": {
        "arc": 'A Brother\'s Destiny - "Ivory"',
        "block": "20f",
    },
    "War of the Seals (Onyx Edition)": {"arc": "Onyx Edition", "block": "onyx"},
    "Shattered Empire": {"arc": "Shattered Empire", "block": "shattered"},
    "Modern": {"arc": None, "block": "modern"},
    "Legacy": {"arc": None, "block": "legacy"},
    "Not Legal (Proxy)": {"arc": None, "block": "proxy"},
    "Unreleased": {"arc": None, "block": "unreleased"},
}


def populate_format_metadata(cur) -> None:
    """Fill formats.arc / block / legal_from from FORMAT_METADATA and the loaded set release dates.

    ``legal_from`` is the earliest ``release_date`` among the arc's sets (NULL for non-arc formats),
    so the chronology stays sourced from set metadata rather than hardcoded here. Idempotent:
    re-running refreshes the three columns. Requires ``l5r_sets`` to be populated first.
    """
    for name, meta in FORMAT_METADATA.items():
        cur.execute(
            "UPDATE formats SET arc = %s, block = %s,"
            " legal_from = (SELECT MIN(release_date) FROM l5r_sets WHERE arc = %s)"
            " WHERE name = %s",
            (meta["arc"], meta["block"], meta["arc"], name),
        )
