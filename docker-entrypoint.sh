#!/bin/bash
set -e

if [ -n "$YASUKI_DATABASE_URL" ]; then
    DB_URL="$YASUKI_DATABASE_URL"
elif [ -n "$DATABASE_URL" ]; then
    DB_URL="$DATABASE_URL"
else
    DB_URL=""
fi

export YASUKI_DATABASE_URL="$DB_URL"

if [ -z "$DB_URL" ]; then
    echo "WARNING: No database URL configured."
    echo "  Set DATABASE_URL or YASUKI_DATABASE_URL."
    echo "  On Railway: add a PostgreSQL service, then set"
    echo "    DATABASE_URL = \${{Postgres.DATABASE_URL}}"
    echo "  on your web service's Variables tab."
    echo ""
    echo "  DEBUG: YASUKI_DATABASE_URL='${YASUKI_DATABASE_URL:-(unset)}'"
    echo "  DEBUG: DATABASE_URL='${DATABASE_URL:-(unset)}'"
    echo ""
    echo "Skipping database initialization. Starting server anyway..."
    exec "$@"
fi

MASKED_URL=$(echo "$DB_URL" | sed -E 's|(://[^:]+:)[^@]+(@)|\1****\2|')
echo "Database URL: $MASKED_URL"

echo "Starting database initialization in background..."
pixi run -e prod python -u -c "
import time, sys, os
import psycopg
from yasuki_core.database import get_connection_string

db_url = get_connection_string()

for attempt in range(1, 16):
    try:
        conn = psycopg.connect(db_url)
        conn.close()
        print(f'[db-init] Database reachable (attempt {attempt})')
        break
    except psycopg.OperationalError as e:
        print(f'[db-init] Waiting for database... ({attempt}/15)')
        if attempt == 15:
            print(f'[db-init] Last error: {e}', file=sys.stderr)
        time.sleep(2)
else:
    print('[db-init] ERROR: Database not reachable after 15 attempts', file=sys.stderr)
    sys.exit(1)

print('[db-init] Running database initialization...')
from yasuki_core.install.install_db import main as install_main
rc = 1
try:
    rc = install_main(['--dsn', db_url])
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else 1
except Exception as e:
    print(f'[db-init] Database init error: {e}')

if rc == 0:
    print('[db-init] Database initialization complete')
else:
    print(f'[db-init] Database init failed (exit code {rc})')
" &
DB_INIT_PID=$!
echo "Database init running in background (PID $DB_INIT_PID)"

echo "Starting server..."
exec "$@"
