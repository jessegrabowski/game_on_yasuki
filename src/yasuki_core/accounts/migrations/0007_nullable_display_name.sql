-- A new account no longer gets an auto-generated handle; display_name is NULL until the user picks
-- one during onboarding (a NULL display_name is the "not yet onboarded" signal). The length CHECK
-- stays and is simply not evaluated for NULL. Existing accounts already have names, so none are
-- affected.
ALTER TABLE users ALTER COLUMN display_name DROP NOT NULL;
