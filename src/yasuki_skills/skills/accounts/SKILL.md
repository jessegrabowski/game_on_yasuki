---
name: accounts
description: >
  Use this whenever you work on user accounts, login, or authentication — Google OAuth, sessions, saved
  decks, the banlist, roles/admin approval, or the separate accounts database and its migrations — and
  read it first, since there are load-bearing security invariants (the email HMAC pepper, hashed tokens,
  the isolated DB) that are easy to break. Covers src/yasuki_core/accounts and the web auth surface
  (yasuki_web/auth.py, saved_decks.py). This is isolated from the card database and the game engine; the
  card DB is the card-data skill.
---

# Accounts (users, auth, saved decks)

## Where it lives

- `src/yasuki_core/accounts/` — `db.py`, `users.py`, `sessions.py`, `decks.py`, `deck_repo.py`,
  `crypto.py`, `roles.py`, `banlist.py`, `oauth_state.py`, `migrate.py`, and `migrations/*.sql`
- `src/yasuki_web/auth.py`, `saved_decks.py` — the HTTP surface (Google OAuth, session cookies, deck CRUD)

## What it does

Users, sessions, saved decks, roles/approval, and the banlist, backed by a **separate accounts
PostgreSQL** — deliberately isolated so a card reseed can never reach user data. The accounts schema is
**ordered SQL migrations** under `accounts/migrations/` (not `schema.sql`); `migrate.py` applies them on
startup (idempotent, never drops).

Security-critical details: emails and OAuth subs are never stored in the clear — only as an HMAC blind
index keyed by `YASUKI_EMAIL_HMAC_PEPPER`, which is **load-bearing and effectively un-rotatable**
(changing it re-hashes every identity and orphans duplicate-account detection and banlist tombstones).
Session tokens are stored hashed (`crypto.py`). Login is Google OAuth (`auth.py`); a local dev shortcut
(`YASUKI_DEV_LOGIN`) is refused whenever `ENVIRONMENT=production`. The whole surface **degrades
gracefully**: without the accounts DB or the `GOOGLE_*` credentials, `/auth/*` returns 503 and these
features are simply off, while public card search and the deck builder keep working.

## How it fits the big picture

Accounts bolt onto the web server (see the `web` skill) via `auth.py`/`saved_decks.py` and are
independent of the game engine. The database is entirely separate from the card DB (see the `card-data`
skill). Configuration (accounts DSN, pepper, OAuth, SMTP) is documented in `.env.example`.
