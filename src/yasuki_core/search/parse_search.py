import re
from dataclasses import dataclass


@dataclass
class SearchTerm:
    """
    Represents a single search term with field, operator, and value.

    Attributes
    ----------
    field : str or None
        Field name (e.g., 'name', 'type', 'force'). None for text search.
    operator : str
        Comparison operator (':', '=', '>', '>=', '<', '<=')
    value : str
        Search value
    negated : bool
        Whether this term is negated (NOT)
    """

    field: str | None
    operator: str
    value: str
    negated: bool = False


@dataclass
class ParsedQuery:
    """
    A parsed search query as a flat list of terms.

    Attributes
    ----------
    terms : list of SearchTerm
        Individual search terms
    """

    terms: list[SearchTerm]


FIELD_ALIASES = {
    "o": "text",
    "oracle": "text",
    "title": "name",
    "t": "type",
    "c": "clan",
    "s": "set",
    "f": "force",
    "format": "format",
    "arc": "format",
    "r": "rarity",
    "a": "artist",
    "ft": "flavor",
    "side": "deck",
    # Stat abbreviations. The single-letter namespace is taken (t/c/s/f/r/a), so every stat gets a
    # two-letter code; force keeps its established "f".
    "gold": "gold_cost",
    "gc": "gold_cost",
    "gp": "gold_production",
    "fc": "focus",
    "ch": "chi",
    "ph": "personal_honor",
    "hr": "honor_requirement",
    "province": "province_strength",
    "ps": "province_strength",
    "startinghonor": "starting_honor",
    "sh": "starting_honor",
    "fh": "starting_honor",
    "exp": "experience",
    "xp": "experience",
    "has": "is",
}

# `is:` values that toggle a boolean card column rather than match a keyword/trait.
IS_BOOLEAN_FIELDS = {"unique": "is_unique", "banned": "is_banned"}

# `is:` values that test whether a nullable column is populated — `is:flip` (has a back face),
# `is:errata` (has errata text). Maps the value to the filter key the database resolves.
IS_PRESENCE_FIELDS = {"flip": "is_flip", "errata": "has_errata"}


# Non-deck cards (proxies, tokens, bio cards, …) are hidden by default. `include:tokens` brings the
# token/non-deck cards back; `include:all` shows everything.
INCLUDE_CATEGORIES = {"tokens", "all"}


# Categorical set-membership fields: parser field name -> (filter key, per-value normalizer). Each
# emits `<key>` for the required values and `<key>_excludes` for negated ones.
CATEGORICAL_FIELDS = {
    "deck": ("decks", str.upper),
    "type": ("types", str.lower),
    "clan": ("clans", None),
    "rarity": ("rarities", None),
}


NUMERIC_FIELDS = {
    "gold_cost",
    "focus",
    "force",
    "chi",
    "honor_requirement",
    "personal_honor",
    "gold_production",
    "province_strength",
    "starting_honor",
    "experience",
}

# Shorthand for a closed numeric range, e.g. `force:2-4`. Non-negative bounds only, so it never
# collides with a negative value like `exp:-1`; open-ended ranges use the >=/<= operators instead.
_RANGE_SHORTHAND = re.compile(r"^(\d+)-(\d+)$")


def normalize_field_name(field: str) -> str:
    """
    Normalize field name using aliases.

    Parameters
    ----------
    field : str
        Raw field name from query

    Returns
    -------
    normalized : str
        Normalized field name
    """
    field_lower = field.lower()
    return FIELD_ALIASES.get(field_lower, field_lower)


def tokenize_query(query: str) -> list[str]:
    """
    Tokenize search query into components.

    Handles quoted strings, field:value pairs, and boolean operators.

    Parameters
    ----------
    query : str
        Raw search query

    Returns
    -------
    tokens : list of str
        Query tokens

    Examples
    --------
    >>> tokenize_query('name:Doji type:personality')
    ['name:Doji', 'type:personality']

    >>> tokenize_query('"Doji Hoturi" force>3')
    ['"Doji Hoturi"', 'force>3']
    """
    tokens = []
    current_token = []
    in_quotes = False
    i = 0

    while i < len(query):
        char = query[i]

        if char == '"':
            in_quotes = not in_quotes
            current_token.append(char)
        elif char in (" ", "\t", "\n") and not in_quotes:
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
        else:
            current_token.append(char)

        i += 1

    if current_token:
        tokens.append("".join(current_token))

    return tokens


def parse_token(token: str) -> SearchTerm:
    """
    Parse a single token into a SearchTerm.

    Parameters
    ----------
    token : str
        Single query token

    Returns
    -------
    term : SearchTerm
        Parsed search term

    Examples
    --------
    >>> parse_token('name:Doji')
    SearchTerm(field='name', operator=':', value='Doji', negated=False)

    >>> parse_token('force>3')
    SearchTerm(field='force', operator='>', value='3', negated=False)

    >>> parse_token('-type:event')
    SearchTerm(field='type', operator=':', value='event', negated=True)
    """
    negated = False

    # Check for negation
    if token.startswith("-"):
        negated = True
        token = token[1:]

    # `!"phrase"` is an exact whole-name match (operator "="); a bare `"phrase"` is a substring
    # phrase (operator ":"), the same broad search a plain word gets.
    if token.startswith('!"') and token.endswith('"'):
        return SearchTerm(field=None, operator="=", value=token[2:-1], negated=negated)
    elif token.startswith('"') and token.endswith('"'):
        return SearchTerm(field=None, operator=":", value=token[1:-1], negated=negated)

    # Try to match field:value or field>value patterns
    match = re.match(r"^([a-zA-Z_]+)([:=><]+)(.+)$", token)

    if match:
        field, operator, value = match.groups()

        # Normalize >= and <= to ensure consistency
        if operator == "=>":
            operator = ">="
        elif operator == "=<":
            operator = "<="

        # A quoted field value (o:"take control", name:"Doji Hoturi") keeps its quotes through the
        # regex; strip a surrounding pair so the phrase searches as text, like a bare "quoted" term.
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]

        field_normalized = normalize_field_name(field)

        # Handle special "is:" and "has:" fields (has is an alias for is)
        if field_normalized == "is":
            return SearchTerm(field="is", operator=":", value=value.lower(), negated=negated)

        return SearchTerm(field=field_normalized, operator=operator, value=value, negated=negated)

    # Plain text search (no field specified)
    return SearchTerm(field=None, operator=":", value=token, negated=negated)


def parse_search_query(query: str) -> ParsedQuery:
    """
    Parse a search query string into a flat, deduplicated list of terms.

    Bare boolean keywords (AND/OR/NOT) are stripped; combining logic lives downstream, where
    ``build_filter_options`` ORs same-field values and ANDs everything else. (The deck-builder search
    box parses through ``boolean_query`` instead, which honors real cross-field OR and grouping.)

    Parameters
    ----------
    query : str
        Search query string.

    Returns
    -------
    parsed : ParsedQuery
        The parsed terms, deduplicated in order.
    """
    terms = []
    seen = set()
    for token in tokenize_query(query):
        if token.upper() in ("AND", "OR", "NOT") or token in seen:
            continue
        seen.add(token)
        terms.append(parse_token(token))
    return ParsedQuery(terms=terms)


def _scope_text_field(terms_list: list, prefix: str, filter_options: dict) -> None:
    """Record a field's terms as ``<prefix>_contains`` / ``<prefix>_excludes`` ILIKE filters."""
    included = [term.value for term in terms_list if not term.negated]
    excluded = [term.value for term in terms_list if term.negated]
    if included:
        filter_options[f"{prefix}_contains"] = included
    if excluded:
        filter_options[f"{prefix}_excludes"] = excluded


def build_filter_options(parsed: ParsedQuery) -> tuple[str, dict]:
    """
    Convert parsed query to database filter options.

    Parameters
    ----------
    parsed : ParsedQuery
        Parsed search query

    Returns
    -------
    text_query : str
        General text search query (for name/text fields)
    filter_options : dict
        Structured filter options for database query

    Notes
    -----
    This function converts the parsed search terms into the format
    expected by query_cards_filtered() in the database module.
    """
    text_query_parts = []
    filter_options = {}

    # Group terms by field for aggregation. Bare words (field None) get their own group so they keep
    # the broad name+id+rules-text behavior, while explicit name:/text: scope to a single column.
    field_groups = {}
    for term in parsed.terms:
        field = term.field if term.field is not None else "_bare"
        if field not in field_groups:
            field_groups[field] = []
        field_groups[field].append(term)

    for field, terms_list in field_groups.items():
        if field == "_bare":
            # Bare words: broad substring search across name, card id, and rules text. A negated
            # bare word (-doji) excludes that broad match; `!"phrase"` (operator "=") is instead an
            # exact whole-name match, positive or negated.
            for term in terms_list:
                if not term.value:
                    # A stray '-' or '""' carries no needle. Left unguarded, a negated one becomes a
                    # match-everything exclude ('%%') that blanks the whole result set.
                    continue
                if term.operator == "=":
                    key = "name_exact_excludes" if term.negated else "name_exact"
                    filter_options.setdefault(key, []).append(term.value)
                elif term.negated:
                    filter_options.setdefault("bare_excludes", []).append(term.value)
                else:
                    text_query_parts.append(term.value)
        elif field == "name":
            # name:/title: — match the card name only.
            _scope_text_field(terms_list, "name", filter_options)
        elif field == "text":
            # text:/o:/oracle: — match the rules text only.
            _scope_text_field(terms_list, "rules_text", filter_options)
        elif field == "all":
            # The canonical "match every card" predicate — adds no constraints.
            filter_options["all"] = True
        elif field == "is":
            # Special "is:" filters
            # Handle both is_unique and keywords with AND/OR logic
            # Syntax: is:keyword1 is:keyword2 (AND - default)
            #         is:keyword1|keyword2    (OR)
            #         is:keyword1&keyword2    (AND - explicit)
            for term in terms_list:
                keyword_value = term.value.lower()

                # Check for pipe (OR) or ampersand (AND) syntax
                if "|" in keyword_value:
                    # OR logic: split by pipe
                    keywords = [kw.strip() for kw in keyword_value.split("|")]
                    if not term.negated:
                        if "keywords_or" not in filter_options:
                            filter_options["keywords_or"] = []
                        filter_options["keywords_or"].extend(keywords)
                elif "&" in keyword_value:
                    # AND logic: split by ampersand (explicit)
                    keywords = [kw.strip() for kw in keyword_value.split("&")]
                    if not term.negated:
                        if "keywords" not in filter_options:
                            filter_options["keywords"] = []
                        filter_options["keywords"].extend(keywords)
                elif keyword_value in IS_BOOLEAN_FIELDS:
                    # Boolean card flags (is:unique, is:banned) rather than keyword traits.
                    filter_options[IS_BOOLEAN_FIELDS[keyword_value]] = not term.negated
                elif keyword_value in IS_PRESENCE_FIELDS:
                    # Presence flags (is:flip, is:errata) — a nullable column being populated.
                    filter_options[IS_PRESENCE_FIELDS[keyword_value]] = not term.negated
                else:
                    # Single keyword (implicit AND when multiple is: terms)
                    if not term.negated:
                        if "keywords" not in filter_options:
                            filter_options["keywords"] = []
                        filter_options["keywords"].append(keyword_value)
        elif field in CATEGORICAL_FIELDS:
            # Categorical filters. Negated terms (-type:event) become a parallel *_excludes list the
            # database applies as NOT IN, so a query can both require and forbid categories at once.
            key, normalize = CATEGORICAL_FIELDS[field]
            included = [term.value for term in terms_list if not term.negated]
            excluded = [term.value for term in terms_list if term.negated]
            if normalize:
                included = [normalize(v) for v in included]
                excluded = [normalize(v) for v in excluded]
            if included:
                filter_options[key] = included
            if excluded:
                filter_options[f"{key}_excludes"] = excluded
        elif field in ("artist", "flavor", "story"):
            # Free-text partial matches: artist/flavor on the print, story on the card credit. A
            # negated term (-artist:foo) forbids the match via a parallel *_excludes list.
            included, excluded = [], []
            for term in terms_list:
                cleaned = term.value.strip('"').strip()
                if not cleaned:
                    continue
                (excluded if term.negated else included).append(cleaned)
            if included:
                filter_options[field] = included
            if excluded:
                filter_options[f"{field}_excludes"] = excluded
        elif field == "set":
            # Set by full name or short code, resolved in the database. Like format, emit each
            # (operator, value); the operator may be exact or an inequality against set release dates.
            # A negated term forbids membership via the *_excludes twin (strict set complement, so
            # -set>=GE means "printed in no set at or after GE", not "printed in some set before GE").
            specs = [
                (term.operator, term.value.strip('"').strip())
                for term in terms_list
                if not term.negated and term.value.strip('"').strip()
            ]
            excluded = [
                (term.operator, term.value.strip('"').strip())
                for term in terms_list
                if term.negated and term.value.strip('"').strip()
            ]
            if specs:
                filter_options["set_filters"] = specs
            if excluded:
                filter_options["set_filters_excludes"] = excluded
        elif field == "format":
            # Legality by format, resolved in the database against formats.block / legal_from. Emit
            # each (operator, value) verbatim: the value may be a short alias (`diamond`) or a full
            # name, and the operator may be exact or an inequality against the format timeline. A
            # negated term forbids membership via the *_excludes twin (strict set complement, so
            # -format>=diamond means "legal in no format at or after diamond", not "legal in some
            # earlier format").
            specs = [
                (term.operator, term.value.strip('"').strip())
                for term in terms_list
                if not term.negated and term.value.strip('"').strip()
            ]
            excluded = [
                (term.operator, term.value.strip('"').strip())
                for term in terms_list
                if term.negated and term.value.strip('"').strip()
            ]
            if specs:
                filter_options["format_filters"] = specs
            if excluded:
                filter_options["format_filters_excludes"] = excluded
        elif field in NUMERIC_FIELDS:
            # Numeric comparison filters tracked as a (min, max) pair. A bare "-" matches the dash
            # stat — one the card simply doesn't print, stored as NULL — and negation flips it to
            # "has any value".
            field_min = None
            field_max = None
            dash = None  # True => stat is NULL, False => stat is NOT NULL

            for term in terms_list:
                if term.value.strip() == "-" and term.operator in (":", "="):
                    dash = not term.negated
                    continue
                if term.negated:
                    continue

                if term.operator in (":", "="):
                    range_match = _RANGE_SHORTHAND.match(term.value.strip())
                    if range_match:
                        low, high = int(range_match.group(1)), int(range_match.group(2))
                        field_min, field_max = min(low, high), max(low, high)
                        continue

                try:
                    value = int(term.value)

                    if term.operator in (":", "="):
                        field_min = value
                        field_max = value
                    elif term.operator == ">":
                        field_min = value + 1
                    elif term.operator == ">=":
                        field_min = value
                    elif term.operator == "<":
                        field_max = value - 1
                    elif term.operator == "<=":
                        field_max = value
                except ValueError:
                    pass

            if dash is not None:
                filter_options[field] = "isnull" if dash else "notnull"
            elif field_min is not None or field_max is not None:
                filter_options[field] = (field_min, field_max)
        elif field == "include":
            # Opt non-deck cards back into the results; unknown categories are ignored.
            valid = {
                term.value.lower()
                for term in terms_list
                if not term.negated and term.value.lower() in INCLUDE_CATEGORIES
            }
            if valid:
                filter_options["include"] = valid
        else:
            # Unrecognized field (typo or unsupported key): mark the query unsatisfiable rather than
            # text-searching the value (which matches nonsense) or dropping it (which matches all).
            filter_options.setdefault("_unknown_fields", []).append(field)

    text_query = " ".join(text_query_parts)
    if not parsed.terms:
        # A blank search resolves to the explicit all: predicate, so every query carries one.
        filter_options["all"] = True
    return text_query, filter_options


def parse_and_build_query(query_string: str) -> tuple[str, dict]:
    """
    Parse search query and build database query parameters.

    High-level function combining parsing and filter building.

    Parameters
    ----------
    query_string : str
        Raw search query string

    Returns
    -------
    text_query : str
        Text search query
    filter_options : dict
        Database filter options

    Examples
    --------
    >>> text, filters = parse_and_build_query('name:Doji force>3')
    >>> text
    'Doji'
    >>> filters
    {'force': (4, None)}
    """
    parsed = parse_search_query(query_string)
    return build_filter_options(parsed)
