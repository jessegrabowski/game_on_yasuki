# Header a test connection uses to name its player; conftest's fake authenticator turns it into a
# stable account. Connections sharing a name share an id (and thus a seat).
WS_USER_HEADER = "x-test-user"

_account_ids: dict[str, int] = {}


def _id_for(name: str) -> int:
    return _account_ids.setdefault(name, len(_account_ids) + 1)


def account(name: str) -> dict:
    """A synthetic authenticated account for unit tests that seat players directly.

    The same name always maps to the same id, so naming one player twice models that player's
    second tab, while distinct names are distinct players.
    """
    return {"id": _id_for(name), "display_name": name}


def as_user(name: str) -> dict[str, str]:
    """WebSocket handshake header that signs a test connection in as ``name``."""
    return {WS_USER_HEADER: name}
