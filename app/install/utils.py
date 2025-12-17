import re
import unicodedata
from unidecode import unidecode_expect_ascii

from app.paths import ASSETS_DIR, SETS_DIR

SUFFIX_MAP = {
    "experienced": "exp",
    "inexperienced": "inexp",
    "experiencedcom": "exp_com",
    "experienced 2cw": "exp_2_cw",
    "experienced2kyd": "exp2kyd",
    "experienced 2": "exp2",
    "experienced 3": "exp3",
    "experienced 4": "exp4",
}

DECK_MAP = {
    "Fate": "FATE",
    "Dynasty": "DYNASTY",
    "Pre-Game": "PRE_GAME",
    "Other": "OTHER",
}


def clean_string(s):
    # Remove commas from numbers > 999
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)

    # Handle special characters where I have a strong opinion on the replacement
    s = (
        unidecode_expect_ascii(s)
        .lower()
        .strip()
        .replace(",", " ")
        .replace("'", "")
        .replace("&", "and")
    )

    # Remaining special characters are simply removed
    s = re.sub(r"[^a-z0-9_]", " ", s).strip()
    s = re.sub(" +", " ", s)
    s = s.replace(" ", "_")
    return s


def normalize_name(name: str) -> str:
    """
    Create lowercase ASCII version of name for searching and sorting.

    Removes diacritics and converts to lowercase.

    Parameters
    ----------
    name : str
        Name to normalize

    Returns
    -------
    normalized : str
        Lowercase ASCII version
    """
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.lower()


def normalize_for_filesystem(name: str) -> str:
    """
    Normalize name for file system paths.

    Converts to lowercase, replaces special characters with underscores,
    handles numeric formatting, and ensures filesystem safety.

    Parameters
    ----------
    name : str
        Name to normalize

    Returns
    -------
    normalized : str
        Filesystem-safe string with only lowercase alphanumeric and underscores
    """
    name = re.sub(r"(?<=\d),(?=\d{3}\b)", "", name)

    normalized = name.lower()
    normalized = normalized.replace(",", " ").replace("'", "").replace("&", "and")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = normalized.strip("_")
    return normalized


def strip_title(title: str) -> str:
    """
    Convert Extended Title to filename-safe format.

    Handles experience markers by splitting on bullet point and mapping
    experience keywords to short codes.

    Examples
    --------
    "Bayushi Kachiko" → "bayushi_kachiko"
    "Bayushi Kachiko • Experienced" → "bayushi_kachiko_exp"
    "Bayushi Kachiko • Inexperienced" → "bayushi_kachiko_inexp"
    "Bayushi Kachiko • Experienced 2" → "bayushi_kachiko_exp2"

    Parameters
    ----------
    title : str
        Extended title with optional experience markers

    Returns
    -------
    filename : str
        Normalized filename without extension
    """
    if "•" not in title:
        return normalize_for_filesystem(title)

    title, tags = title.split("•", 1)
    title = normalize_for_filesystem(title)
    tags = [
        SUFFIX_MAP.get(
            normalize_for_filesystem(stripped_tag), normalize_for_filesystem(stripped_tag)
        )
        for tag in tags.split(" ")
        if len(stripped_tag := tag.strip().lower()) > 0
    ]
    return "_".join([title, *tags])


def find_card_image(extended_title: str, set_name: str) -> str | None:
    """
    Find image file for a card using Extended Title.

    Images are stored in: app/assets/images/sets/<set_name>/<card_id>.png

    Parameters
    ----------
    extended_title : str
        Extended Title field (e.g., "Bayushi Kachiko • Experienced")
    set_name : str
        Set name

    Returns
    -------
    image_path : str or None
        Relative path from ASSETS_DIR, or None if not found
    """
    if not SETS_DIR.exists():
        return None

    set_dir_name = normalize_for_filesystem(set_name)
    set_dir = SETS_DIR / set_dir_name

    if not set_dir.exists():
        return None

    card_file_name = strip_title(extended_title) + ".png"
    card_path = set_dir / card_file_name

    if card_path.exists():
        return str(card_path.relative_to(ASSETS_DIR))

    return None


def process_string(s: str) -> str:
    """
    Clean up whitespace and special characters from scraped HTML text.

    Normalizes non-breaking spaces, newlines, and multiple spaces.

    Parameters
    ----------
    s : str
        Raw string from HTML

    Returns
    -------
    cleaned : str
        String with normalized whitespace
    """
    s = s.strip()
    s = re.sub(r"[\xa0\n]", " ", s)
    s = re.sub(" +", " ", s)
    return s


def normalize_empty(value: str | None) -> str | None:
    """
    Convert empty strings and dash placeholders to None for SQL NULL.

    Parameters
    ----------
    value : str or None
        Value to normalize

    Returns
    -------
    normalized : str or None
        None if value is empty/dash, otherwise original value
    """
    if value is None:
        return None
    if isinstance(value, str) and (value.strip() == "" or value == "-"):
        return None
    return value
