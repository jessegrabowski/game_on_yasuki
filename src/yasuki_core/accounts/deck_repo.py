import secrets

import psycopg

from yasuki_core.accounts.decks import DeckCard, DeckSummary, from_rows, to_rows

# The deck fields the web layer needs to render a tile or a shared-deck page; excludes the soft-delete
# tombstone and the heavy card list (fetched separately by get_deck).
_DECK_COLUMNS = (
    "id, slug, owner_id, name, format, description, visibility, "
    "stronghold_card_id, clan, dynasty_count, fate_count, created_at, updated_at"
)
# token_urlsafe(6) is 8 base64url chars; ample space against collision, retried below regardless.
_SLUG_BYTES = 6
_SLUG_ATTEMPTS = 5


def count_active_decks(conn: psycopg.Connection, owner_id: int) -> int:
    """The number of a user's decks that are not soft-deleted — the per-user cap is checked here."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM decks WHERE owner_id = %s AND deleted_at IS NULL",
            (owner_id,),
        )
        return cur.fetchone()["n"]


def save_deck(
    conn: psycopg.Connection,
    owner_id: int,
    *,
    name: str,
    cards: list[DeckCard],
    summary: DeckSummary,
    format: str | None = None,
    description: str | None = None,
    visibility: str = "private",
) -> dict:
    """Insert a deck and its cards in one transaction, returning the new deck row.

    A fresh random slug is allocated; on the vanishingly rare collision the insert retries with a new
    one. The cards are expected pre-validated and pre-summarized (see ``decks.resolve_deck_cards`` and
    ``decks.summarize``).

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    owner_id : int
        The owning user's id.
    name : str
        The deck's display name.
    cards : list of DeckCard
        The resolved, validated deck entries.
    summary : DeckSummary
        The denormalized stronghold / clan / count summary.
    format : str, optional
        The targeted format slug. Default None.
    description : str, optional
        Free-text description. Default None.
    visibility : str, optional
        One of 'private', 'unlisted', 'public'. Default 'private'.

    Returns
    -------
    deck : dict
        The inserted deck row, with the keys in ``_DECK_COLUMNS``.
    """
    for _ in range(_SLUG_ATTEMPTS):
        slug = secrets.token_urlsafe(_SLUG_BYTES)
        try:
            with conn.transaction():
                deck = _insert_deck(
                    conn, owner_id, slug, name, summary, format, description, visibility
                )
                _insert_cards(conn, deck["id"], cards)
            return deck
        except psycopg.errors.UniqueViolation:
            # resolve_deck_cards collapses duplicate variants, so the only unique column that can
            # collide here is the slug; regenerate and retry.
            continue
    raise RuntimeError("could not allocate a unique deck slug")


def _insert_deck(conn, owner_id, slug, name, summary, format, description, visibility) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO decks (slug, owner_id, name, format, description, visibility,
                               stronghold_card_id, clan, dynasty_count, fate_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_DECK_COLUMNS}
            """,
            (
                slug,
                owner_id,
                name,
                format,
                description,
                visibility,
                summary.stronghold_card_id,
                summary.clan,
                summary.dynasty_count,
                summary.fate_count,
            ),
        )
        return cur.fetchone()


def _insert_cards(conn, deck_id: int, cards: list[DeckCard]) -> None:
    if not cards:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, set_name, side, quantity, "
            "art_donor_card_id, art_donor_set) VALUES (%(deck_id)s, %(card_id)s, %(card_name)s, "
            "%(set_name)s, %(side)s, %(quantity)s, %(art_donor_card_id)s, %(art_donor_set)s)",
            to_rows(cards, deck_id),
        )


def list_decks(conn: psycopg.Connection, owner_id: int) -> list[dict]:
    """A user's non-deleted decks, newest-edited first, as summary rows (no card lists)."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_DECK_COLUMNS} FROM decks "
            "WHERE owner_id = %s AND deleted_at IS NULL ORDER BY updated_at DESC",
            (owner_id,),
        )
        return cur.fetchall()


def get_deck(conn: psycopg.Connection, slug: str) -> dict | None:
    """A single non-deleted deck by slug with its cards attached, or None if absent.

    Returns the deck row (including ``owner_id`` and ``visibility`` for the caller's access check)
    with an added ``cards`` key holding the deck's ``DeckCard`` list.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_DECK_COLUMNS} FROM decks WHERE slug = %s AND deleted_at IS NULL",
            (slug,),
        )
        deck = cur.fetchone()
        if deck is None:
            return None
        cur.execute(
            "SELECT card_id, card_name, set_name, side, quantity, art_donor_card_id, art_donor_set "
            "FROM deck_cards WHERE deck_id = %s ORDER BY id",
            (deck["id"],),
        )
        deck["cards"] = from_rows(cur.fetchall())
        return deck


def soft_delete_deck(conn: psycopg.Connection, slug: str, owner_id: int) -> bool:
    """Soft-delete a user's deck by slug, returning whether a row was theirs to delete.

    Sets ``deleted_at`` so shared links 404 and the deck leaves listings while staying recoverable.
    A slug that is missing, already deleted, or owned by someone else returns False, unchanged.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE decks SET deleted_at = now() "
            "WHERE slug = %s AND owner_id = %s AND deleted_at IS NULL RETURNING id",
            (slug, owner_id),
        )
        return cur.fetchone() is not None
