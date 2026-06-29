-- Promote the free-text role to a managed set: a lookup table of valid roles, with users.role a
-- foreign key into it. One role per user (a user_roles join table would only be needed for many).
-- The table is the source of truth the admin dashboard's role dropdown reads, and the FK rejects a
-- role that was never defined. Seed the two the app ships with before adding the constraint.
CREATE TABLE IF NOT EXISTS roles (
    name        text PRIMARY KEY,
    description text NOT NULL DEFAULT ''
);

INSERT INTO roles (name, description) VALUES
    ('user', 'Standard account'),
    ('admin', 'Full access to the admin dashboard')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE users ADD CONSTRAINT users_role_fkey FOREIGN KEY (role) REFERENCES roles (name);
