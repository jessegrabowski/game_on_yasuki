# Card footprint for the local client — smaller than the web board's (board.js is 81×115) so more
# of the board fits on screen.
CARD_W = 73
CARD_H = 104
# Copies of one holding stack in a single home column, each offset down by this much so every copy
# stays visible and clickable.
HOME_STACK_OFFSET = 26
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

# Radius of a counter badge (e.g. a wealth token) drawn in a card's top-right corner.
COUNTER_BADGE_R = 9

# Honor counter limits
MIN_HONOR = -20
MAX_HONOR = 100
