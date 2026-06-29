-- New accounts start unapproved and are gated out of the product surfaces (playing online, saving
-- decks to the account) until an admin approves them; profile self-service and browsing stay open.
-- Existing accounts are grandfathered approved, so the gate only ever applies to fresh sign-ups.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved boolean NOT NULL DEFAULT false;
UPDATE users SET is_approved = true;
