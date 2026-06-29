-- A coarse account role for authorization. 'user' is the default; 'admin' unlocks the admin
-- dashboard (account list + ban). A text column, not a table, keeps it simple while leaving room
-- for more roles later. Bootstrap the first admin with a manual UPDATE.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'user';
