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


def serif(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return (SERIF_FAMILY, size, weight)
