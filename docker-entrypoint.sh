#!/bin/bash
set -e

initialize_database() {
    echo "Checking if database needs initialization..."
    if ! pixi run python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['L5R_DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT 1 FROM information_schema.tables WHERE table_name = 'cards'\")
if not cur.fetchone():
    exit(1)
cur.execute('SELECT COUNT(*) FROM cards')
if cur.fetchone()[0] == 0:
    exit(1)
" 2>/dev/null; then
        echo "Initializing application database..."
        pixi run install-db --dsn "$L5R_DATABASE_URL"
    else
        echo "Database already initialized"
    fi
}

initialize_database

exec "$@"
