import re
from dataclasses import dataclass
from typing import Literal


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
    Represents a parsed search query with terms and logic.

    Attributes
    ----------
    terms : list of SearchTerm
        Individual search terms
    logic : str
        Boolean logic ('AND' or 'OR')
    """

    terms: list[SearchTerm]
    logic: Literal["AND", "OR"] = "AND"


FIELD_ALIASES = {
    "o": "text",
    "oracle": "text",
    "t": "type",
    "c": "clan",
    "s": "set",
    "f": "force",
    "format": "format",
    "r": "rarity",
    "side": "deck",
    "gold": "gold_cost",
    "ph": "personal_honor",
    "province": "province_strength",
    "startinghonor": "starting_honor",
    "has": "is",
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
}


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

    # Check for quoted exact match
    if token.startswith('!"') and token.endswith('"'):
        return SearchTerm(field=None, operator="=", value=token[2:-1], negated=negated)
    elif token.startswith('"') and token.endswith('"'):
        return SearchTerm(field=None, operator="=", value=token[1:-1], negated=negated)

    # Try to match field:value or field>value patterns
    match = re.match(r"^([a-zA-Z_]+)([:=><]+)(.+)$", token)

    if match:
        field, operator, value = match.groups()

        # Normalize >= and <= to ensure consistency
        if operator == "=>":
            operator = ">="
        elif operator == "=<":
            operator = "<="

        field_normalized = normalize_field_name(field)

        # Handle special "is:" and "has:" fields (has is an alias for is)
        if field_normalized == "is":
            return SearchTerm(field="is", operator=":", value=value.lower(), negated=negated)

        return SearchTerm(field=field_normalized, operator=operator, value=value, negated=negated)

    # Plain text search (no field specified)
    return SearchTerm(field=None, operator=":", value=token, negated=negated)


def parse_search_query(query: str) -> ParsedQuery:
    """
    Parse a search query string into structured search terms.

    Supports Scryfall-style syntax:
    - Field-specific: name:Doji, type:personality, force>3
    - Exact match: "Doji Hoturi", !"exact phrase"
    - Boolean: term1 AND term2, term1 OR term2
    - Negation: -type:event, NOT type:event
    - Numeric comparison: force>=3, chi<2, gold:5
    - Special: is:unique

    Parameters
    ----------
    query : str
        Search query string

    Returns
    -------
    parsed : ParsedQuery
        Parsed query with terms and logic

    Examples
    --------
    >>> parse_search_query('name:Doji type:personality')
    ParsedQuery(terms=[...], logic='AND')

    >>> parse_search_query('clan:Crane OR clan:Lion')
    ParsedQuery(terms=[...], logic='OR')
    """
    if not query.strip():
        return ParsedQuery(terms=[], logic="AND")

    # Determine logic (default AND)
    logic = "AND"
    if " OR " in query.upper():
        logic = "OR"
        # Normalize OR separators
        query = re.sub(r"\s+OR\s+", " OR ", query, flags=re.IGNORECASE)

    # Tokenize first (this handles quotes properly)
    tokens = tokenize_query(query)

    # Split on OR if present
    if logic == "OR":
        # Split tokens on OR keyword
        token_groups = []
        current_group = []
        for token in tokens:
            if token.upper() == "OR":
                if current_group:
                    token_groups.append(current_group)
                    current_group = []
            else:
                current_group.append(token)
        if current_group:
            token_groups.append(current_group)

        # Flatten all tokens
        all_tokens = []
        for group in token_groups:
            all_tokens.extend(group)
    else:
        # Filter out AND/OR/NOT keywords (they're handled implicitly)
        all_tokens = [t for t in tokens if t.upper() not in ("AND", "OR", "NOT")]

    # Remove duplicates while preserving order
    seen = set()
    unique_tokens = []
    for token in all_tokens:
        if token not in seen:
            seen.add(token)
            unique_tokens.append(token)

    terms = [parse_token(token) for token in unique_tokens]

    return ParsedQuery(terms=terms, logic=logic)


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

    # Group terms by field for aggregation
    field_groups = {}
    for term in parsed.terms:
        field = term.field or "text"
        if field not in field_groups:
            field_groups[field] = []
        field_groups[field].append(term)

    for field, terms_list in field_groups.items():
        if field == "text":
            # General text search
            for term in terms_list:
                if not term.negated:
                    text_query_parts.append(term.value)
        elif field == "name":
            # Name search - add to text query
            for term in terms_list:
                if not term.negated:
                    text_query_parts.append(term.value)
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
                elif keyword_value == "unique":
                    # Special case for is_unique boolean field
                    filter_options["is_unique"] = not term.negated
                else:
                    # Single keyword (implicit AND when multiple is: terms)
                    if not term.negated:
                        if "keywords" not in filter_options:
                            filter_options["keywords"] = []
                        filter_options["keywords"].append(keyword_value)
        elif field in ("deck", "type", "clan", "set", "rarity", "format"):
            # Categorical filters
            values = [term.value for term in terms_list if not term.negated]
            if values:
                if field == "deck":
                    filter_options["decks"] = [v.upper() for v in values]
                elif field == "type":
                    filter_options["types"] = [v.lower() for v in values]
                elif field == "clan":
                    filter_options["clans"] = [v for v in values]
                elif field == "set":
                    filter_options["sets"] = [v for v in values]
                elif field == "rarity":
                    filter_options["rarities"] = [v for v in values]
                elif field == "format":
                    # Format with legality check
                    format_value = values[0] if values else None
                    filter_options["legality"] = (format_value, ["legal"])
        elif field in NUMERIC_FIELDS:
            # Numeric comparison filters
            # Track min/max separately, then combine into tuple
            field_min = None
            field_max = None

            for term in terms_list:
                if term.negated:
                    continue

                try:
                    value = int(term.value)

                    # Map operators to min/max values
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
                    # Invalid numeric value, skip
                    pass

            # Store as tuple (min, max) format expected by database
            if field_min is not None or field_max is not None:
                filter_options[field] = (field_min, field_max)

    text_query = " ".join(text_query_parts)
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
    {'force_min': 4}
    """
    parsed = parse_search_query(query_string)
    return build_filter_options(parsed)
