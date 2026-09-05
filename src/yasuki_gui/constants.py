# Card footprint for the local client — smaller than the web board's (board.js is 81×115) so more
# of the board fits on screen.
CARD_W = 73
CARD_H = 104

# How much larger than its on-board size a card renders when previewed, wherever it is
# previewed from.
PREVIEW_SCALE = 3.6
# Copies of one holding stack in a single home column, each offset down by this much so every copy
# stays visible and clickable.
HOME_STACK_OFFSET = 26
# Pixels an attached card is shifted up per slot, so its title bar clears the card it rides and each
# further attachment fans a little higher. Matches the web board's ATTACH_STACK_OFFSET.
ATTACH_STACK_OFFSET = 24
# Slightly reduced spacing for draw placement
DRAW_OFFSET = 16

# Canvas and UI colors
CANVAS_BG = "#2b2b2b"
INSPECT_BG = "#1e1e1e"
INSPECT_TEXT = "#eaeaea"
FALLBACK_CARD_BG = "#6b6b6b"
FALLBACK_CARD_TEXT = "#222"

# Marquee selection styling
MARQUEE_COLOR = "#66ccff"
MARQUEE_WIDTH = 2
MARQUEE_DASH = (4, 2)

# Deck label keywords (heuristics)
LABEL_KEYWORD_FATE = "Fate"
LABEL_KEYWORD_DYNASTY = "Dynasty"

# Hand layout
HAND_PADDING = 12
HAND_GAP = 8

# Image component tags
CARD_TAG = "card"
ART_TAG = "art"
BORDER_TAG = "border"
SELECT_TAG = "select"
LABEL_TAG = "label"
NOTE_TAG = "note"
COUNTER_TAG = "counter"
STAT_TAG = "stat"

# Radius of a counter badge (e.g. a wealth token). It hangs off the card's bottom-right; the
# top-right is where a card prints its Chi, and the live stat is stamped over that.
COUNTER_BADGE_R = 9

# Where a card prints its Force and Chi, as a fraction of the card — the median bounding-box center
# of the numerals over 40 Twenty Festivals Personalities. The live stat is stamped over the printed
# one rather than inset from a corner, so it lands where the eye already goes for that number.
FORCE_ANCHOR = (0.1107, 0.0714)
CHI_ANCHOR = (0.8887, 0.0705)
# The stamp's box. Fixed rather than measured off the glyphs, so every card carries the same shape
# and a bowed card rotates that shape rather than whatever its own digits happened to make.
STAT_FONT_PX = 12
STAT_BOX_H = 13
STAT_BOX_W = 13  # one digit; each further digit adds STAT_DIGIT_W
STAT_DIGIT_W = 9  # the widest digit's advance, so the margin holds however long the number runs

# Honor counter limits
MIN_HONOR = -20
MAX_HONOR = 100
