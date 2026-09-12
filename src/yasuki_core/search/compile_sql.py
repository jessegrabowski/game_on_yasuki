import logging

from yasuki_core.install.utils import normalize_name
from yasuki_core.search.boolean_query import (
    Node,
    Not,
    Term,
    active_format_from_ast,
    includes_from_ast,
    parse_query,
)
from yasuki_core.search.parse_search import ParsedQuery, SearchTerm, build_filter_options

logger = logging.getLogger(__name__)


def escape_like(value: str) -> str:
    """Escape ``%`` and ``_`` wildcards for use in ILIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


ALL_CLANS_MARKER = "All Clans"

# Clans L5R renamed over its history. A filter on any name in a group matches the whole group, and
# the first name is the one the deck-builder dropdown shows.
CLAN_ALIAS_GROUPS = (("Naga", "Akasha"),)
_CLAN_ALIASES = {
    name.lower(): [n.lower() for n in group] for group in CLAN_ALIAS_GROUPS for name in group
}
CLAN_CANONICAL = {name.lower(): group[0] for group in CLAN_ALIAS_GROUPS for name in group[1:]}


_ALLOWED_COLUMNS = {
    "is_unique",
    "is_proxy",
    "is_banned",
    "name",
    "force",
    "chi",
    "honor_requirement",
    "gold_cost",
    "personal_honor",
    "province_strength",
    "gold_production",
    "starting_honor",
    "focus",
    "experience",
}

_NUMERIC_STATS = (
    "force",
    "chi",
    "honor_requirement",
    "gold_cost",
    "personal_honor",
    "province_strength",
    "gold_production",
    "starting_honor",
    "focus",
    "experience",
)


# Comparison operators allowed in a `format>diamond` or `set>=ge`-style search, mapped to the SQL
# they emit. The map both whitelists the operator (keeping it injection-safe when interpolated) and
# excludes the exact operators, which take a different code path.
_RANGE_OPS = {">": ">", ">=": ">=", "<": "<", "<=": "<="}

# `is:` presence flags -> the nullable column whose being-populated they test. Keys are hardcoded,
# so interpolating the column into `c.<col> IS NOT NULL` is injection-safe.
_PRESENCE_COLUMNS = {"is_flip": "back_card_id", "has_errata": "errata_text"}

# The broad bare-word match: a card whose name, id, current text (either face), or any printing's
# own text contains the needle. Four %s placeholders take the same pattern. Used positively for a
# bare word and, negated as a whole (De Morgan), to exclude one.
_BARE_TEXT_UNION = (
    "c.name ILIKE %s ESCAPE '\\'"
    " OR c.card_id ILIKE %s ESCAPE '\\'"
    " OR (c.rules_text || ' ' || COALESCE(back.rules_text, '')) ILIKE %s ESCAPE '\\'"
    " OR EXISTS (SELECT 1 FROM prints p WHERE p.card_id = c.card_id"
    " AND p.rules_text ILIKE %s ESCAPE '\\')"
)


def _bare_text_predicate(needle: str, *, negated: bool = False) -> tuple[str, list]:
    """Broad bare-word predicate for one needle, with the pattern replicated per placeholder."""
    sql = f"NOT ({_BARE_TEXT_UNION})" if negated else f"({_BARE_TEXT_UNION})"
    return sql, [f"%{escape_like(needle)}%"] * 4


def active_format_from_options(filter_options: dict | None) -> str | None:
    """
    Resolve the single active format whose arc should bias default-print selection.

    An exact ``format:``/``arc:`` search token or the deck-builder format dropdown pins one format.
    Inequality ranges, multiple specs, or no format filter leave it unresolved.

    Parameters
    ----------
    filter_options : dict or None
        The filter dictionary passed to ``build_card_filter``.

    Returns
    -------
    active_format : str or None
        A format name or block alias, or None when no single format is in effect.
    """
    if not filter_options:
        return None
    resolved = filter_options.get("_active_format")
    if resolved:
        return resolved
    specs = filter_options.get("format_filters")
    if specs and len(specs) == 1 and specs[0][0] in (":", "="):
        return specs[0][1]
    legality = filter_options.get("legality")
    if legality and legality[0]:
        return legality[0]
    return None


def _emit_condition(property_name: str, value) -> tuple[list[str], list]:
    """
    Emit the SQL condition(s) and positional params for one filter entry.

    Map a single ``filter_options`` key/value to zero or more self-contained WHERE predicates.
    ``build_card_filter`` calls this per dict entry to AND them into the query. ``compile_term``
    calls it per search term to compile one AST leaf.

    Parameters
    ----------
    property_name : str
        The filter key (a column, a ``*_excludes`` variant, or a synthetic key like ``clans``).
    value : object
        The key's value. Its shape depends on the key (a list of needles, a (min, max) tuple, a
        list of (operator, value) specs, and so on).

    Returns
    -------
    conditions : list of str
        SQL predicate fragments to AND into the WHERE clause.
    params : list
        Positional parameters matching the ``%s`` placeholders in ``conditions``.
    """
    conditions: list[str] = []
    params: list = []
    if property_name in ("include", "all", "_active_format"):
        # include feeds the visibility filter; _active_format only biases default-print selection;
        # all adds nothing.
        return conditions, params
    if property_name == "_search_ast":
        # A pre-compiled boolean-query predicate (SQL, params), dropped in verbatim.
        sql, ast_params = value
        return [sql], list(ast_params)
    if property_name == "_unknown_fields":
        # An unrecognized search field makes the query unsatisfiable rather than silently
        # matching everything or text-searching the value.
        logger.warning("Unknown search field(s), returning no results: %s", value)
        conditions.append("FALSE")
    elif property_name in _PRESENCE_COLUMNS:
        # Presence flag (is:flip -> a front with a back face; is:errata -> has errata text): the
        # column is populated. The column name is a hardcoded table key, so interpolation is safe.
        column = _PRESENCE_COLUMNS[property_name]
        conditions.append(f"c.{column} IS NOT NULL" if value else f"c.{column} IS NULL")
    elif property_name in ("name_contains", "name_excludes"):
        # Match the accent-folded name so ASCII input finds accented titles (Shime -> Shimé). Fold
        # the needle with the same normalizer that built name_normalized. Name is face-independent.
        op = "NOT ILIKE" if property_name.endswith("excludes") else "ILIKE"
        for needle in value:
            conditions.append(f"c.name_normalized {op} %s ESCAPE '\\'")
            params.append(f"%{escape_like(normalize_name(needle))}%")
    elif property_name in ("name_exact", "name_exact_excludes"):
        # `!"phrase"` for exact match: the whole name equals the phrase (case-insensitive).
        # All of a card's experience versions share a name, so this isolates that card, not one
        # printing.
        op = "!=" if property_name.endswith("excludes") else "="
        for needle in value:
            conditions.append(f"lower(c.name) {op} lower(%s)")
            params.append(needle)
    elif property_name == "bare_excludes":
        # A negated bare word (-doji) hides any card the positive bare word would match.
        for needle in value:
            sql, pattern_params = _bare_text_predicate(needle, negated=True)
            conditions.append(sql)
            params.extend(pattern_params)
    elif property_name in ("rules_text_contains", "rules_text_excludes"):
        # Rules text matches either face (the back has its own text) and any printing's own
        # wording, so a reworded reprint's phrasing is findable even when the card's current
        # text dropped it. Excludes negates the whole disjunction (De Morgan).
        card_col = "(c.rules_text || ' ' || COALESCE(back.rules_text, ''))"
        print_exists = (
            "EXISTS (SELECT 1 FROM prints p WHERE p.card_id = c.card_id"
            " AND p.rules_text ILIKE %s ESCAPE '\\')"
        )
        excludes = property_name.endswith("excludes")
        for needle in value:
            pattern = f"%{escape_like(needle)}%"
            if excludes:
                conditions.append(f"({card_col} NOT ILIKE %s ESCAPE '\\' AND NOT {print_exists})")
            else:
                conditions.append(f"({card_col} ILIKE %s ESCAPE '\\' OR {print_exists})")
            params.extend([pattern, pattern])
    elif property_name == "legality":
        formats, _statuses = value
        if isinstance(formats, str):
            formats = [formats]
        if formats:
            conditions.append(
                "c.card_id IN (SELECT card_id FROM card_legalities WHERE format_name = ANY(%s))"
            )
            params.append(list(formats))
    elif property_name in ("format_filters", "format_filters_excludes"):
        # Each (operator, value) resolves the value against a format's name or short block alias.
        # Exact operators match that one format; inequalities compare every format's legal_from to
        # the reference format's, selecting one side of the arc timeline. The *_excludes twin is the
        # strict set complement (NOT IN). -format>=diamond means "legal in no format at or after
        # diamond", never a naive operator flip to format<diamond. An unresolvable reference fails
        # closed via the EXISTS guard so a typo'd -format:xyz matches nothing, mirroring the
        # positive filter whose empty IN-set matches nothing.
        excludes = property_name.endswith("excludes")
        for op, format_value in value:
            if op in (":", "="):
                match_sql = (
                    "SELECT cl.card_id FROM card_legalities cl"
                    " JOIN formats f ON f.name = cl.format_name"
                    " WHERE lower(f.name) = lower(%s) OR lower(f.block) = lower(%s)"
                )
                guard_sql = (
                    "EXISTS (SELECT 1 FROM formats"
                    " WHERE lower(name) = lower(%s) OR lower(block) = lower(%s))"
                )
            elif op in _RANGE_OPS:
                match_sql = (
                    "SELECT cl.card_id FROM card_legalities cl"
                    " JOIN formats f ON f.name = cl.format_name"
                    f" WHERE f.legal_from {_RANGE_OPS[op]} (SELECT legal_from FROM formats"
                    " WHERE (lower(name) = lower(%s) OR lower(block) = lower(%s))"
                    " AND legal_from IS NOT NULL LIMIT 1)"
                )
                guard_sql = (
                    "EXISTS (SELECT 1 FROM formats"
                    " WHERE (lower(name) = lower(%s) OR lower(block) = lower(%s))"
                    " AND legal_from IS NOT NULL)"
                )
            else:
                continue
            if excludes:
                conditions.append(f"({guard_sql} AND c.card_id NOT IN ({match_sql}))")
                params.extend([format_value] * 4)
            else:
                conditions.append(f"c.card_id IN ({match_sql})")
                params.extend([format_value, format_value])
    elif property_name in ("set_filters", "set_filters_excludes"):
        # Each (operator, value) resolves the value against a set's full name or short code. Exact
        # operators match that set; inequalities compare every set's release_date to the reference
        # set's, selecting cards printed on one side of that release. The *_excludes twin is the
        # strict set complement (NOT IN). -set>=GE means "printed in no set at or after GE", not
        # "printed in some earlier set", and an unresolvable reference fails closed via the EXISTS
        # guard, matching nothing like the positive filter does.
        excludes = property_name.endswith("excludes")
        for op, set_value in value:
            if op in (":", "="):
                match_sql = (
                    "SELECT p.card_id FROM prints p"
                    " JOIN l5r_sets s ON s.set_id = p.set_id"
                    " WHERE lower(s.set_name) = lower(%s) OR lower(s.code) = lower(%s)"
                )
                guard_sql = (
                    "EXISTS (SELECT 1 FROM l5r_sets"
                    " WHERE lower(set_name) = lower(%s) OR lower(code) = lower(%s))"
                )
            elif op in _RANGE_OPS:
                match_sql = (
                    "SELECT p.card_id FROM prints p"
                    " JOIN l5r_sets s ON s.set_id = p.set_id"
                    f" WHERE s.release_date {_RANGE_OPS[op]} (SELECT release_date"
                    " FROM l5r_sets WHERE (lower(set_name) = lower(%s) OR lower(code) ="
                    " lower(%s)) AND release_date IS NOT NULL ORDER BY release_date LIMIT 1)"
                )
                guard_sql = (
                    "EXISTS (SELECT 1 FROM l5r_sets"
                    " WHERE (lower(set_name) = lower(%s) OR lower(code) = lower(%s))"
                    " AND release_date IS NOT NULL)"
                )
            else:
                continue
            if excludes:
                conditions.append(f"({guard_sql} AND c.card_id NOT IN ({match_sql}))")
                params.extend([set_value] * 4)
            else:
                conditions.append(f"c.card_id IN ({match_sql})")
                params.extend([set_value, set_value])
    elif property_name == "sets":
        if value:
            conditions.append(
                "c.card_id IN (SELECT p.card_id FROM prints p"
                " JOIN l5r_sets s ON s.set_id = p.set_id WHERE s.set_name = ANY(%s))"
            )
            params.append(value)
    elif property_name == "year_filters":
        # Each (operator, year) matches a card with any printing from a set released that year (or
        # on one side of it). Exact operators become =; inequalities come from the whitelist.
        for op, year in value:
            sql_op = _RANGE_OPS.get(op, "=")
            conditions.append(
                "c.card_id IN (SELECT p.card_id FROM prints p JOIN l5r_sets s ON s.set_id = p.set_id"
                f" WHERE EXTRACT(YEAR FROM s.release_date) {sql_op} %s)"
            )
            params.append(year)
    elif property_name in ("decks", "decks_excludes"):
        if value:
            op = "NOT IN" if property_name.endswith("excludes") else "IN"
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM card_decks WHERE deck = ANY(%s::deck_type[]))"
            )
            params.append([d.title() for d in value])
    elif property_name in ("types", "types_excludes"):
        if value:
            op = "NOT IN" if property_name.endswith("excludes") else "IN"
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM card_card_types"
                " WHERE type = ANY(%s::card_type[]))"
            )
            params.append([t.title() for t in value])
    elif property_name in ("clans", "clans_excludes"):
        # An "All Clans" sensei is legal in any clan's deck, so every clan filter also matches it.
        # Symmetrically, -clan:X excludes it too (NOT of the positive).
        if value:
            wanted = set()
            for clan in value:
                clan = clan.lower()
                wanted.update(_CLAN_ALIASES.get(clan, (clan,)))
            wanted.add(ALL_CLANS_MARKER.lower())
            op = "NOT IN" if property_name.endswith("excludes") else "IN"
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM card_clans WHERE lower(clan) = ANY(%s))"
            )
            params.append(list(wanted))
    elif property_name in ("rarities", "rarities_excludes"):
        if value:
            rarity_conditions = []
            for rarity in value:
                rarity_conditions.append("rarity ILIKE %s ESCAPE '\\'")
                params.append(f"%{escape_like(rarity)}%")
            op = "NOT IN" if property_name.endswith("excludes") else "IN"
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM prints"
                f" WHERE {' OR '.join(rarity_conditions)})"
            )
    elif property_name in ("artist", "artist_excludes"):
        op = "NOT IN" if property_name.endswith("excludes") else "IN"
        for artist in value:
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM prints WHERE artist ILIKE %s ESCAPE '\\')"
            )
            params.append(f"%{escape_like(artist)}%")
    elif property_name in ("flavor", "flavor_excludes"):
        op = "NOT IN" if property_name.endswith("excludes") else "IN"
        for flavor in value:
            # A printing's special back (story scroll) keeps its prose in back_flavor.
            conditions.append(
                f"c.card_id {op} (SELECT card_id FROM prints"
                " WHERE (flavor_text || ' ' || COALESCE(back_flavor, '')) ILIKE %s ESCAPE '\\')"
            )
            params.append(f"%{escape_like(flavor)}%")
    elif property_name in ("story", "story_excludes"):
        excludes = property_name.endswith("excludes")
        for story in value:
            if excludes:
                # A NULL story credit doesn't contain the term, so keep those cards.
                conditions.append("(c.story IS NULL OR c.story NOT ILIKE %s ESCAPE '\\')")
            else:
                conditions.append("c.story ILIKE %s ESCAPE '\\'")
            params.append(f"%{escape_like(story)}%")
    elif property_name == "keywords":
        if value:
            for keyword in value:
                conditions.append(
                    "c.card_id IN (SELECT card_id FROM card_keywords WHERE lower(keyword) = lower(%s))"
                )
                params.append(keyword)
    elif property_name == "keywords_or":
        # `is:a|b` for cards carrying any one of the keywords.
        if value:
            conditions.append(
                "c.card_id IN (SELECT card_id FROM card_keywords WHERE lower(keyword) = ANY(%s))"
            )
            params.append([k.lower() for k in value])
    elif property_name in _NUMERIC_STATS:
        # A dash stat (one the card doesn't print) is stored as NULL. The whitelisted column name
        # is interpolation-safe (it is a key of _NUMERIC_STATS).
        if value == "isnull":
            conditions.append(f"c.{property_name} IS NULL")
        elif value == "notnull":
            conditions.append(f"c.{property_name} IS NOT NULL")
        elif isinstance(value, tuple) and len(value) == 2:
            # Range matches consider the back face too, so a stat that differs per face (e.g.
            # province_strength) matches when either side satisfies it.
            min_val, max_val = value
            range_predicates, range_params = [], []
            for alias in ("c", "back"):
                col = f"{alias}.{property_name}"
                if min_val is not None and max_val is not None:
                    range_predicates.append(f"{col} >= %s AND {col} <= %s")
                    range_params.extend([min_val, max_val])
                elif min_val is not None:
                    range_predicates.append(f"{col} >= %s")
                    range_params.append(min_val)
                elif max_val is not None:
                    range_predicates.append(f"{col} <= %s")
                    range_params.append(max_val)
            if range_predicates:
                joined = " OR ".join(f"({predicate})" for predicate in range_predicates)
                conditions.append(f"({joined})")
                params.extend(range_params)
    elif value is not None:
        if property_name not in _ALLOWED_COLUMNS:
            logger.warning(f"Ignoring unknown filter column: {property_name}")
            return conditions, params
        conditions.append(f"c.{property_name} = %s")
        params.append(value)
    return conditions, params


def build_card_filter(
    text_query: str = "",
    filter_options: dict | None = None,
) -> tuple[str, list]:
    """
    Build a WHERE clause and parameter list from filter criteria.

    All conditions reference only the ``cards`` table (aliased ``c``) and
    use subqueries for joins, so the clause works with or without the
    lateral print join.

    Parameters
    ----------
    text_query : str
        Free-text search for name, id, or rules text
    filter_options : dict, optional
        Property filters (see ``query_cards_filtered`` for format)

    Returns
    -------
    where_clause : str
        SQL fragment starting with ``WHERE`` or empty string
    params : list
        Positional parameters matching ``%s`` placeholders in the clause
    """
    conditions: list[str] = []
    params: list = []

    # A back face is never a standalone result; a search reaches it through its front via the
    # cross-face conditions below, which consult the joined `back` row.
    conditions.append("NOT c.is_back")

    if text_query:
        sql, pattern_params = _bare_text_predicate(text_query)
        conditions.append(sql)
        params.extend(pattern_params)

    if filter_options:
        for property_name, value in filter_options.items():
            new_conditions, new_params = _emit_condition(property_name, value)
            conditions.extend(new_conditions)
            params.extend(new_params)

    # Non-deck cards (proxies and everything filed under the "Other" deck: tokens, bio cards,
    # deckbackers, ...) are hidden by default. `include:tokens` brings the "Other" cards back
    # (proxies that are also tokens come with them); `include:all` shows everything.
    token = "EXISTS (SELECT 1 FROM card_decks d WHERE d.card_id = c.card_id AND d.deck = 'Other')"
    includes = filter_options.get("include", ()) if filter_options else ()
    if "all" not in includes:
        if "tokens" in includes:
            conditions.append(f"(NOT c.is_proxy OR {token})")
        else:
            conditions.append(f"(NOT c.is_proxy AND NOT {token})")

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where_clause, params


def compile_term(term: SearchTerm) -> tuple[str, list] | None:
    """
    Compile one search term (a boolean-AST leaf) into a single SQL predicate and its params.

    Reuse ``build_filter_options`` to map the term to filter keys, then ``_emit_condition`` for each
    key's SQL, ANDing a term's several conditions (e.g. ``is:a&b``) into one parenthesized
    predicate. A term that constrains nothing on its own (``all:``, or a bare directive like
    ``include:tokens``) compiles to None.

    Parameters
    ----------
    term : SearchTerm
        A single parsed search term.

    Returns
    -------
    compiled : tuple of (str, list) or None
        One SQL boolean expression (safe to combine under AND/OR/NOT) with its positional params, or
        None when the term adds no predicate.
    """
    text_query, filter_options = build_filter_options(ParsedQuery(terms=[term]))
    conditions: list[str] = []
    params: list = []
    if text_query:
        sql, pattern_params = _bare_text_predicate(text_query)
        conditions.append(sql)
        params.extend(pattern_params)
    for property_name, value in filter_options.items():
        new_conditions, new_params = _emit_condition(property_name, value)
        conditions.extend(new_conditions)
        params.extend(new_params)
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0], params
    return "(" + " AND ".join(conditions) + ")", params


def compile_query(node: Node | None) -> tuple[str, list] | None:
    """
    Compile a boolean-query AST into one SQL predicate and its params, or None for no constraint.

    Recurse the tree: a ``Term`` compiles via ``compile_term``, a ``Not`` prefixes ``NOT``, and a
    ``BoolGroup`` parenthesizes its children joined by AND/OR. Empty branches drop out, so a group
    with one surviving child collapses to that child.

    Parameters
    ----------
    node : Node or None
        The AST root from ``parse_query``.

    Returns
    -------
    compiled : tuple of (str, list) or None
        The SQL expression and its positional params, or None when the query constrains nothing.
    """
    if node is None:
        return None
    if isinstance(node, Term):
        return compile_term(node.term)
    if isinstance(node, Not):
        compiled = compile_query(node.child)
        if compiled is None:
            return None
        sql, params = compiled
        return f"NOT {sql}", params
    # BoolGroup: the only remaining node type.
    parts: list[str] = []
    params: list = []
    for child in node.children:
        compiled = compile_query(child)
        if compiled is None:
            continue
        sql, child_params = compiled
        parts.append(sql)
        params.extend(child_params)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0], params
    return "(" + f" {node.op} ".join(parts) + ")", params


def build_search_filters(query: str) -> dict:
    """
    Compile a search-box query string into ``filter_options`` entries.

    Produce a ``_search_ast`` entry holding the compiled boolean predicate and, when the query pins
    a single format, an ``_active_format`` entry to bias default-print selection. Deck-builder
    dialog filters are added to the same dict by the caller and AND with this predicate.

    Parameters
    ----------
    query : str
        Raw search-box query.

    Returns
    -------
    filter_options : dict
        Filter entries for ``query_cards_filtered``. Empty when the query constrains nothing.
    """
    node = parse_query(query)
    options: dict = {}
    predicate = compile_query(node)
    if predicate is not None:
        options["_search_ast"] = predicate
    active = active_format_from_ast(node)
    if active:
        options["_active_format"] = active
    includes = includes_from_ast(node)
    if includes:
        options["include"] = includes
    return options
