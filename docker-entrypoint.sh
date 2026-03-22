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
import psycopg2

db_url = os.environ['YASUKI_DATABASE_URL']

for attempt in range(1, 16):
    try:
        conn = psycopg2.connect(db_url)
        conn.close()
        print(f'[db-init] Database reachable (attempt {attempt})')
        break
    except psycopg2.OperationalError as e:
        print(f'[db-init] Waiting for database... ({attempt}/15)')
        if attempt == 15:
            print(f'[db-init] Last error: {e}', file=sys.stderr)
        time.sleep(2)
else:
    print('[db-init] ERROR: Database not reachable after 15 attempts', file=sys.stderr)
    sys.exit(1)

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(\"SELECT 1 FROM information_schema.tables WHERE table_name = 'cards'\")
    if cur.fetchone():
        cur.execute('SELECT COUNT(*) FROM cards')
        count = cur.fetchone()[0]
        if count > 0:
            print(f'[db-init] Database already initialized ({count} cards)')
            conn.close()
            sys.exit(0)
    conn.close()
except Exception:
    pass

print('[db-init] Initializing application database...')
from yasuki_core.install.install_db import main as install_main
try:
    install_main(['--dsn', db_url])
    print('[db-init] Database initialization complete')
except SystemExit as e:
    if e.code == 0:
        print('[db-init] Database initialization complete')
    else:
        print('[db-init] Database init failed, may already be initialized by another service')
except Exception as e:
    print(f'[db-init] Database init error: {e}')
" &
DB_INIT_PID=$!
echo "Database init running in background (PID $DB_INIT_PID)"

echo "Starting server..."
exec "$@"
