#!/bin/bash
set -e

DB_URL="${L5R_DATABASE_URL:-${DATABASE_URL:-postgresql://l5r:l5r@db:5432/l5r}}"

wait_for_db() {
    local attempt=1
    local max=15
    while [ $attempt -le $max ]; do
        if pixi run -e prod python -c "import psycopg2; psycopg2.connect('$DB_URL')" 2>/dev/null; then
            return 0
        fi
        echo "Waiting for database... ($attempt/$max)"
        sleep 2
        attempt=$((attempt + 1))
    done
    echo "ERROR: Database not reachable" >&2
    exit 1
}

initialize_database() {
    echo "Checking if database needs initialization..."
    if ! pixi run -e prod python -c "
import psycopg2
conn = psycopg2.connect('$DB_URL')
cur = conn.cursor()
cur.execute(\"SELECT 1 FROM information_schema.tables WHERE table_name = 'cards'\")
if not cur.fetchone():
    exit(1)
cur.execute('SELECT COUNT(*) FROM cards')
if cur.fetchone()[0] == 0:
    exit(1)
" 2>/dev/null; then
        echo "Initializing application database..."
        pixi run -e prod install-db --dsn "$DB_URL" || echo "Database init skipped (may already be initialized by another service)"
    else
        echo "Database already initialized"
    fi
}

wait_for_db
initialize_database

exec "$@"
