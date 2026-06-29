import psycopg


def list_roles(conn: psycopg.Connection) -> list[dict]:
    """Return every defined role as ``{name, description}``, alphabetically."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, description FROM roles ORDER BY name")
        return cur.fetchall()


def create_role(conn: psycopg.Connection, name: str, description: str = "") -> bool:
    """Define a new role, returning whether it was created (False if it already existed)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO roles (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
            (name, description),
        )
        return cur.rowcount > 0


def role_exists(conn: psycopg.Connection, name: str) -> bool:
    """Whether ``name`` is a defined role."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM roles WHERE name = %s", (name,))
        return cur.fetchone() is not None
