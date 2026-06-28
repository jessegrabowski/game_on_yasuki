-- Accounts database — a SEPARATE Railway Postgres from the card DB, so the card installer's
-- DROP SCHEMA ... CASCADE can never reach user data. Consequence: no foreign keys to `cards`;
-- every `card_id` here is plain text, validated against the card DB in the application at save time.
--
-- Applied on its own idempotent migration path (CREATE ... IF NOT EXISTS), independent of the card
-- installer and never dropped by it. No extensions required: identity columns avoid
-- gen_random_uuid(); hashes are computed in Python (hmac/hashlib) and stored as bytea.
--
-- Email is never stored in the clear: only a deterministic blind index, HMAC-SHA256(lower(email),
-- pepper), where `pepper` is a secret held outside the database (env / secret manager). Google
-- re-presents the email on every login, so the plaintext is never needed at rest — auth, dedup, and
-- ban-by-email all run as exact-match lookups on the HMAC. A database-only breach exposes no
-- addresses: the low-entropy emails can't be brute-forced without the pepper, which isn't in the DB.

-- ─────────────────────────────────────────────────────────────────────────────
-- users — one row per Google account. Identity key is the Google `sub`.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    google_sub     text        NOT NULL UNIQUE,            -- stable opaque identity from Google
    email_hmac     bytea       NOT NULL UNIQUE,            -- HMAC-SHA256(lower(email), pepper); no plaintext stored
    email_verified boolean     NOT NULL DEFAULT false,     -- rejected at signup if false; kept for record
    display_name   text        NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 40),
    avatar_url     text,                                   -- Google `picture`, for display; nullable
    is_banned      boolean     NOT NULL DEFAULT false,     -- live-user ban flag; checked on every session resolve
    banned_at      timestamptz,
    ban_reason     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),     -- app-managed (set on write); no trigger, to keep the migration lean
    last_login_at  timestamptz
);
-- The UNIQUE on email_hmac is the dup-account guard and the ban-by-email lookup path; the HMAC is
-- taken over lower(email) app-side, so case folding happens before hashing.

-- ─────────────────────────────────────────────────────────────────────────────
-- sessions — server-side and revocable (this is why we don't use stateless JWTs): deleting the row
-- ends the session instantly, so a ban or "log out everywhere" takes effect immediately. The client
-- holds only the raw token in one HttpOnly+Secure+SameSite=Lax cookie; we store its SHA-256 so a DB
-- leak can't mint sessions.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    token_hash bytea       PRIMARY KEY,                    -- sha256(raw token); raw token never stored
    user_id    bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,                       -- TTL sweep; absence-of-row = revoked
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    user_agent text                                        -- for a "your active sessions" view; nullable
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);   -- revoke-all / list by user
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at); -- expiry sweep

-- ─────────────────────────────────────────────────────────────────────────────
-- decks — normalized, id-based deck storage. The deck-builder already holds an id-keyed model;
-- YAML is only the human import/export interchange. Summary columns are denormalized so the lobby
-- deck list renders without joining deck_cards.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decks (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug         text        NOT NULL UNIQUE,              -- short random base62; the public/shareable id
    owner_id     bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name         text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    format       text,                                     -- targeted format slug; app-validated vs card DB
    description  text        CHECK (description IS NULL OR char_length(description) <= 2000),
    visibility   text        NOT NULL DEFAULT 'private'
                             CHECK (visibility IN ('private', 'unlisted', 'public')),
    -- Denormalized summary for the deck-tile / list view:
    stronghold_card_id text,                              -- the deck's stronghold (also the default cover)
    clan         text,
    dynasty_count int        NOT NULL DEFAULT 0,
    fate_count    int        NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),       -- app-managed
    deleted_at   timestamptz                               -- soft delete; shared links survive, recoverable
);

CREATE INDEX IF NOT EXISTS idx_decks_owner ON decks (owner_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_decks_public ON decks (visibility) WHERE visibility = 'public' AND deleted_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- deck_cards — one row per (deck, card, side, art-variant). `card_id` is the stable card slug,
-- app-validated (no cross-DB FK). card_name + set_name are denormalized on purpose: if a card_id
-- ever drifts (a title edit on a card lacking an explicit `id:`), the entry is re-linkable by name
-- instead of lost. Art-swap is captured semantically (donor card + sets), not via the builder's
-- volatile synthetic print_id.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deck_cards (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    deck_id      bigint  NOT NULL REFERENCES decks (id) ON DELETE CASCADE,
    card_id      text    NOT NULL,                         -- stable card slug; validated app-side
    card_name    text    NOT NULL,                         -- denormalized recovery handle
    set_name     text,                                     -- chosen printing's set; null = default print
    side         text    NOT NULL CHECK (side IN ('dynasty', 'fate', 'pre_game')),
    quantity     int     NOT NULL CHECK (quantity > 0),
    art_donor_card_id text,                                -- art-swap: whose art (card slug)
    art_donor_set     text                                 -- art-swap: donor printing's set
);

-- One row per distinct visual variant; COALESCE makes the uniqueness null-safe (a plain card and an
-- art-swapped copy of it are different rows, but two identical plain entries collapse to one).
CREATE UNIQUE INDEX IF NOT EXISTS idx_deck_cards_variant ON deck_cards (
    deck_id, card_id, side,
    coalesce(set_name, ''), coalesce(art_donor_card_id, ''), coalesce(art_donor_set, '')
);
CREATE INDEX IF NOT EXISTS idx_deck_cards_deck ON deck_cards (deck_id);   -- load a deck
CREATE INDEX IF NOT EXISTS idx_deck_cards_card ON deck_cards (card_id);   -- "decks running card X" + orphan audit

-- ─────────────────────────────────────────────────────────────────────────────
-- banlist — a tombstone that outlives account deletion. A live user's ban is users.is_banned; when
-- that user deletes their account (GDPR erasure), the raw row goes but these HASHES remain, so the
-- banned person can't simply re-register. Hashes only — no raw PII retained. Checked at signup.
-- Both use the same pepper'd HMAC as users.email_hmac (not bare sha256), so a DB-only breach can't
-- brute-force the low-entropy sub/email back out.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS banlist (
    sub_hmac   bytea       PRIMARY KEY,                    -- HMAC-SHA256(google_sub, pepper)
    email_hmac bytea       NOT NULL,                       -- HMAC-SHA256(lower(email), pepper)
    reason     text,
    banned_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_banlist_email_hmac ON banlist (email_hmac);  -- ban-by-email lookup at signup
