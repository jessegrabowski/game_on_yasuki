-- Transient per-login OAuth state, held between /auth/login and /auth/callback: the CSRF state, the
-- OIDC nonce, and the PKCE verifier. Server-authoritative, so no signed cookie is needed. Rows are
-- single-use (deleted when the callback consumes them) and bounded by created_at. Not user data —
-- a row is meaningless once its login completes or ages out.
CREATE TABLE IF NOT EXISTS oauth_logins (
    state         text        PRIMARY KEY,        -- random; Google echoes it back, the CSRF guard
    nonce         text        NOT NULL,           -- bound into the id_token, a replay guard
    code_verifier text        NOT NULL,           -- PKCE; proves the callback was initiated by us
    redirect_to   text,                           -- optional same-site landing path after login
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oauth_logins_created_at ON oauth_logins (created_at);
