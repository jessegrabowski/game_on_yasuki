#!/bin/bash
set -e

DB_URL="${YASUKI_DATABASE_URL:-${DATABASE_URL:-postgresql://yasuki:yasuki@db:5432/yasuki}}"

echo "Waiting for database and checking initialization..."

pixi run -e prod python -u -c "
import time, sys, os

os.environ.setdefault('YASUKI_DATABASE_URL', '$DB_URL')
import psycopg2

# Wait for database to become reachable
for attempt in range(1, 16):
    try:
        conn = psycopg2.connect('$DB_URL')
        conn.close()
        print(f'Database reachable (attempt {attempt})')
        break
    except psycopg2.OperationalError:
        print(f'Waiting for database... ({attempt}/15)')
        time.sleep(2)
else:
    print('ERROR: Database not reachable', file=sys.stderr)
    sys.exit(1)

# Check if database needs initialization
try:
    conn = psycopg2.connect('$DB_URL')
    cur = conn.cursor()
    cur.execute(\"SELECT 1 FROM information_schema.tables WHERE table_name = 'cards'\")
    if cur.fetchone():
        cur.execute('SELECT COUNT(*) FROM cards')
        if cur.fetchone()[0] > 0:
            print('Database already initialized')
            conn.close()
            sys.exit(0)
    conn.close()
except Exception:
    pass

# Database needs seeding
print('Initializing application database...')
from yasuki_core.install.install_db import main as install_main
try:
    install_main(['--dsn', '$DB_URL'])
except SystemExit as e:
    if e.code != 0:
        print('Database init failed, may already be initialized by another service')
except Exception as e:
    print(f'Database init error: {e}')
" || true

exec "$@"
