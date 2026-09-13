---
name: accounts
description: >
  Use this for user accounts and anything behind a login: Google OAuth, sessions and their cookies,
  saved decks, roles and admin approval, the banlist, and the separate accounts database with its
  migrations. Fires on "add a login", "sessions expire", "save a deck", "approve a user", "ban",
  "the auth endpoints 503", "add a migration", and on any change under src/yasuki_core/accounts/ or
  src/yasuki_web/auth.py. Read it first, because the security invariants here are load-bearing and
  quiet when broken. Emails are stored only as an HMAC blind index under a pepper that cannot be
  rotated, session tokens are stored hashed, and the whole surface is meant to degrade to 503 rather
  than fail open. This database is kept apart from the card database, which is the card-data skill.
---

# Accounts, login and saved decks

## Where it lives

- `src/yasuki_core/accounts/`: `db.py`, `users.py`, `sessions.py`, `decks.py`, `deck_repo.py`,
  `crypto.py`, `roles.py`, `banlist.py`, `oauth_state.py`, `migrate.py`
- `src/yasuki_core/accounts/migrations/`: ordered SQL, applied on startup
- `src/yasuki_web/auth.py`, `src/yasuki_web/saved_decks.py`: the HTTP surface

## What it does

Users, sessions, saved decks, roles and the banlist, backed by its own PostgreSQL database, kept
separate so that reseeding the card data can never reach user data. The schema is a set of ordered
SQL migrations. `migrate.py` applies them on startup, idempotently, and never drops.

Three security properties are easy to break and quiet when broken. Emails and OAuth subject ids are
never stored in the clear, only as an HMAC blind index keyed by `YASUKI_EMAIL_HMAC_PEPPER`. That
pepper is effectively un-rotatable: changing it re-hashes every identity and orphans both
duplicate-account detection and banlist tombstones. Session tokens are stored hashed. And the local
dev login shortcut is refused outright when the environment is production.

The whole surface degrades rather than failing open: without the accounts database or the Google
credentials, `/auth/*` returns 503 and these features are simply off, while public card search and
the deck builder keep working.

## What checks it

- The suite, including the tests that assert no identity is stored in the clear
- A live database, for the migrations, which are applied on startup instead of in a test

## How it fits

This subsystem has no page on the documentation site yet, which is why this skill carries none. The
configuration it needs (the accounts DSN, the pepper, the OAuth credentials, SMTP) is documented in
`.env.example`.

It bolts onto the web server through `auth.py` and `saved_decks.py`; that server is the
`play-server` skill. The card database it is kept apart from is `card-data`.
