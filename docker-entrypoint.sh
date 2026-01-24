#!/bin/bash
set -e

wait_for_postgres() {
    echo "Waiting for PostgreSQL to be ready..."
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if pixi run python -c "import psycopg2; psycopg2.connect('$L5R_DATABASE_URL')" 2>/dev/null; then
            echo "PostgreSQL is ready"
            return 0
        fi
        echo "Waiting for PostgreSQL... ($attempt/$max_attempts)"
        sleep 1
        attempt=$((attempt + 1))
    done

    echo "ERROR: PostgreSQL did not become ready in time"
    exit 1
}

initialize_database() {
    echo "Checking if database needs initialization..."
    if ! pixi run python -c "
import psycopg2
import os
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

wait_for_postgres
initialize_database

exec "$@"
