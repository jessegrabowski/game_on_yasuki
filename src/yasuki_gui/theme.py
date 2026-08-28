# The desktop client's visual language, mirroring the web play board (the `.room` scope in the
# web's play.css): a warm parchment table, brown ink, a muted gold accent, and a serif for names
# and titles. Tkinter takes only opaque colors, so the web's translucent lines and washes are baked
# to solid approximations here. Every widget and canvas visual draws from these tokens so the look
# stays consistent and can be retuned in one place.

# Surfaces
BG = "#e8e0d0"  # window background behind panels
SURFACE = "#f4edde"  # the battlefield / table felt
PANEL = "#fbf7ef"  # sidebar and panel chrome
CARD_FACE = "#efe7d6"  # a card with no art

# Ink
INK = "#2c2620"
INK_DIM = "#7c7160"
ON_DARK = "#fdf6e6"  # text over a dark wash or brown back

# Lines (opaque bakes of the web's translucent hairlines)
LINE = "#cdc3ad"
LINE_SOFT = "#e2dac8"

# Accents
GOLD = "#9a7b3f"
GOLD_HOVER = "#876b34"
POWDER_BLUE = "#b0e0e6"  # the Sincerity counter badge, set apart from the gold wealth token
REVEAL = "#2563eb"  # a card shown to the opponent
WARN = "#9c4a35"
SELECT = "#2bb8c9"  # selection ring / marquee

# The centre panel of the scroll each printed stat sits on, sampled off card scans and within three
# points across Celestial, Emperor, Ivory and Twenty Festivals. A card's live Force and Chi are
# stamped over the printed numerals in these, so the stamp reads as the card's own furniture.
FORCE_BANNER = "#988967"
CHI_BANNER = "#6d6d79"
STAT_PRINTED = "#ffffff"  # a stat no modifier reaches, set like the numeral it covers
STAT_UP = "#8fe3a4"  # above printed
STAT_DOWN = "#ff9c85"  # below printed

# Cards
CARD_BORDER = "#6e5a37"
CARD_BACK = "#6b4d27"
CARD_BACK_BORDER = "#46330f"
MIDLINE = "#d8c79a"  # faint gold line splitting the two players' halves
NOTE_BG = "#1c1408"
NOTE_FG = ON_DARK
COUNT_BG = "#2c2620"
COUNT_FG = "#ffffff"

AVATAR_BG = GOLD
AVATAR_FG = "#ffffff"

# EB Garamond on the web; Georgia is the dependable desktop serif with the same editorial feel.
SERIF_FAMILY = "Georgia"

# Georgia's digits are old-style — 0 1 2 sit at x-height, 3 4 5 7 9 descend, 6 8 ascend — so a
# column of them bobs, and a box sized to hold any of them has to span an ascender and a descender
# to fit five pixels of digit. Stat readouts are data rather than prose and want lining figures of
# one height. Tk falls back to its default sans where this family is absent.
NUMERAL_FAMILY = "Verdana"


def serif(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return (SERIF_FAMILY, size, weight)


def numerals(size_px: int, weight: str = "bold") -> tuple[str, int, str]:
    """A numeral font ``size_px`` pixels tall.

    Pixels rather than points — Tk reads a negative size as pixels — because a stat stamp is drawn
    into a box of a fixed pixel size, and points would scale the digits out of it on any display
    whose DPI is not the one this was measured on.
    """
    return (NUMERAL_FAMILY, -size_px, weight)
