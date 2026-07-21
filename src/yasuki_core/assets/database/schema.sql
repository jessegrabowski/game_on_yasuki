CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Controlled vocabularies; values match the source strings.
CREATE TYPE deck_type AS ENUM ('Fate', 'Dynasty', 'Pre-Game', 'Other');

CREATE TYPE card_type AS ENUM (
  'Ancestor', 'Celestial', 'Clock', 'Event', 'Follower', 'Holding', 'Item', 'Other',
  'Personality', 'Proxy', 'Region', 'Ring', 'Sensei', 'Spell', 'Strategy', 'Stronghold',
  'Territory', 'Token', 'Wind'
);


-- `card_id` is a slug of the extended title, with a numeric suffix when two cards would collide.
-- Multi-valued attributes (clan, type, deck) live in junction tables; source fields without a
-- dedicated column go in `extra`.
CREATE TABLE cards (
  card_id           TEXT PRIMARY KEY,            -- slug, e.g. 'bayushi_kachiko_exp'
  slug              TEXT NOT NULL,                  -- display / URL only
  name              TEXT NOT NULL,                  -- title
  extended_title    TEXT NOT NULL,                  -- formattedtitle (experience-disambiguated)
  -- Experience rank parsed from extended_title, for ordering a name's versions: Inexperienced (-1),
  -- base (0), Experienced (1), Experienced 2 (2), ... Set-code variants share their number's rank.
  experience        INTEGER NOT NULL DEFAULT 0,
  name_normalized   TEXT NOT NULL,                  -- ASCII-folded lowercase, for search/sort

  rules_text        TEXT NOT NULL DEFAULT '',       -- entity-decoded

  gold_cost         INTEGER,
  focus             INTEGER,
  force             INTEGER,
  chi               INTEGER,
  honor_requirement INTEGER,
  personal_honor    INTEGER,
  province_strength INTEGER,
  starting_honor    INTEGER,
  gold_production   INTEGER,

  -- Double-faced cards (flip strongholds): the front row points at the back via back_card_id; the
  -- back row is flagged is_back. The FK is deferred so a front can be inserted before its back.
  back_card_id      TEXT REFERENCES cards(card_id) DEFERRABLE INITIALLY DEFERRED,
  is_back           BOOLEAN NOT NULL DEFAULT FALSE,

  is_unique         BOOLEAN NOT NULL DEFAULT FALSE, -- from keywords
  is_proxy          BOOLEAN NOT NULL DEFAULT FALSE, -- has the 'Proxy' type
  is_banned         BOOLEAN NOT NULL DEFAULT FALSE,

  errata_text       TEXT,
  story             TEXT,
  notes             TEXT,

  extra             JSONB NOT NULL DEFAULT '{}'::jsonb,

  rules_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(rules_text, ''))) STORED
);

CREATE TABLE card_clans (
  card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  clan    TEXT NOT NULL,
  PRIMARY KEY (card_id, clan)
);

CREATE TABLE card_card_types (
  card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  type    card_type NOT NULL,
  PRIMARY KEY (card_id, type)
);

CREATE TABLE card_decks (
  card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  deck    deck_type NOT NULL,
  PRIMARY KEY (card_id, deck)
);

CREATE TABLE keywords (
  keyword TEXT PRIMARY KEY
);

CREATE TABLE card_keywords (
  card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  keyword TEXT NOT NULL REFERENCES keywords(keyword) ON DELETE CASCADE,
  PRIMARY KEY (card_id, keyword)
);

-- Tokens a card creates in play. Both sides are cards: `created_card_id` is the token's own card
-- row (a marker Token card, or a created-card proxy).
CREATE TABLE card_creates (
  creator_card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  created_card_id TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  PRIMARY KEY (creator_card_id, created_card_id),
  CHECK (creator_card_id <> created_card_id)
);


-- One row per physical set. `arc` is the storyline block the set belongs to (also the legality
-- block). `set_slug` is the filesystem/URL slug.
CREATE TABLE l5r_sets (
  set_id            SERIAL PRIMARY KEY,
  set_name          TEXT NOT NULL UNIQUE,
  set_slug          TEXT NOT NULL UNIQUE,
  code              TEXT,                   -- short set identifier, e.g. 'GE' (Gold Edition)
  arc               TEXT,
  release_date      DATE,
  digital           BOOLEAN NOT NULL DEFAULT FALSE,
  featured_factions TEXT,
  size_raw          INTEGER,
  border            TEXT,
  notes             TEXT
);


-- Competitive formats / storyline blocks, with rotation date windows that overlap at transitions.
-- A NULL `legal_until` marks an eternal format (Legacy, Modern).
CREATE TABLE formats (
  name        TEXT PRIMARY KEY,   -- e.g. 'Age of Enlightenment (Lotus)'
  block       TEXT,               -- e.g. 'Lotus'
  arc         TEXT,               -- joins to l5r_sets.arc
  legal_from  DATE,
  legal_until DATE
);

-- Card-level legality: the union across a card's printings — "is this card ever legal in format F".
CREATE TABLE card_legalities (
  card_id     TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  format_name TEXT NOT NULL REFERENCES formats(name) ON DELETE CASCADE,
  PRIMARY KEY (card_id, format_name)
);


-- `printing_id` is a within-card key derived from the set slug, suffixed when a card has several
-- printings in one set. Per-printing field overrides and unmapped source fields live in `extra`.
CREATE TABLE prints (
  print_id             SERIAL PRIMARY KEY,
  card_id              TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  printing_id          TEXT NOT NULL,
  set_id               INTEGER REFERENCES l5r_sets(set_id),

  rarity               TEXT,
  flavor_text          TEXT,
  -- This printing's own rules wording, kept only when it differs from the card's canonical text
  -- (e.g. a reprint reworded the ability). NULL means "no printing-specific text"; readers fall
  -- back to cards.rules_text, which follows the most-recent-printing + errata standard.
  rules_text           TEXT,
  -- Some printings carry a special back -- a story scroll or a clan card-back -- instead of the
  -- generic one. The art is a role='back' print_image; back_flavor holds a scroll's prose and
  -- back_title its name (both usually null). Distinct from cards.back_card_id, which is a flip face.
  back_title           TEXT,
  back_flavor          TEXT,
  artist               TEXT,
  designer             TEXT,
  collector_number_raw TEXT,
  publisher            TEXT,
  publisher_url        TEXT,
  doublesided          BOOLEAN NOT NULL DEFAULT FALSE,
  legal_date           DATE,

  extra                JSONB NOT NULL DEFAULT '{}'::jsonb,

  UNIQUE (card_id, printing_id)
);

-- Collector numbers normalized for sorting; position 0 is the primary. The raw string lives on
-- prints.collector_number_raw and never participates in identity.
CREATE TABLE print_numbers (
  id         SERIAL PRIMARY KEY,
  print_id   INTEGER NOT NULL REFERENCES prints(print_id) ON DELETE CASCADE,
  subset     TEXT,
  number_int INTEGER NOT NULL,
  position   INTEGER NOT NULL
);

-- The "bug": which formats a specific printing is legal in.
CREATE TABLE print_legalities (
  print_id    INTEGER NOT NULL REFERENCES prints(print_id) ON DELETE CASCADE,
  format_name TEXT NOT NULL REFERENCES formats(name) ON DELETE CASCADE,
  PRIMARY KEY (print_id, format_name)
);

-- Every image a printing carries, in source order. `role` is front / back / alt; `sha256` is the
-- image's content hash; `path` is its sets/<set_slug>/<file> location.
CREATE TABLE print_images (
  print_id    INTEGER NOT NULL REFERENCES prints(print_id) ON DELETE CASCADE,
  image_index INTEGER NOT NULL,
  role        TEXT NOT NULL DEFAULT 'front',
  size        TEXT NOT NULL DEFAULT 'master',
  sha256      TEXT,
  source_url  TEXT,
  path        TEXT,
  PRIMARY KEY (print_id, image_index, size)
);

-- Generic card backs, selected by (deck, era). A printing's own special back is a role='back' row in
-- print_images instead.
CREATE TABLE card_backs (
  deck       deck_type NOT NULL,
  era        TEXT NOT NULL,        -- 'old' | 'new' | 'token'
  image_path TEXT NOT NULL,
  PRIMARY KEY (deck, era)
);


-- Ordered rules-text/art history for cards that have been errata'd. Sparse: only errata'd cards have
-- rows. revision_index 0 is the original printing text; higher indices are successive errata, newest
-- last (the highest index is the current version). The current text and stats are also mirrored onto
-- the cards row, so every existing read path and every deck reference shows the latest without
-- joining here; this table backs the "what did it used to say" history UI and the errata badge.
-- Errata is a time axis orthogonal to printings: a card can have several printings and several
-- errata independently, so revisions live here rather than as extra prints.
CREATE TABLE card_revisions (
  card_id        TEXT NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
  revision_index INTEGER NOT NULL,   -- 0 = original; ascending by effective date; highest = current
  effective_date DATE,               -- when this text took effect; null for the original
  source         TEXT,               -- e.g. 'Onyx Lives July 2026 Errata'; null for the original
  source_url     TEXT,               -- where the erratum was announced; null for the original
  rules_text     TEXT NOT NULL,
  -- Stat changes this revision introduced (gold_cost, focus, ...); empty when the errata was text
  -- only. Cumulative current values live on the cards row.
  stats          JSONB NOT NULL DEFAULT '{}'::jsonb,
  image_path     TEXT,               -- this revision's card render; null falls back to the print art
  notes          TEXT,
  PRIMARY KEY (card_id, revision_index)
);


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Fuzzy + full-text + sort on names and rules text.
CREATE INDEX idx_cards_name_trgm        ON cards USING gin (name gin_trgm_ops);
CREATE INDEX idx_cards_name_norm_trgm   ON cards USING gin (name_normalized gin_trgm_ops);
CREATE INDEX idx_cards_rules_text_trgm  ON cards USING gin (rules_text gin_trgm_ops);
CREATE INDEX idx_cards_rules_tsv        ON cards USING gin (rules_tsv);
-- Partial: only the handful of printings that override their wording get indexed, so text search
-- can reach an old printed phrasing the card's current text no longer contains.
CREATE INDEX idx_prints_rules_text_trgm ON prints USING gin (rules_text gin_trgm_ops) WHERE rules_text IS NOT NULL;
CREATE INDEX idx_cards_name             ON cards (name);
CREATE INDEX idx_cards_name_normalized  ON cards (name_normalized);
CREATE INDEX idx_cards_lower_name       ON cards (lower(name));
CREATE INDEX idx_cards_lower_ext_title  ON cards (lower(extended_title));
-- Backs the default card ordering (base name, then experience version) with an index scan instead
-- of a full sort. Must match _NAME_TIEBREAK in database.py.
CREATE INDEX idx_cards_sort             ON cards (split_part(name, ',', 1), experience, extended_title);

-- Numeric stat filters.
CREATE INDEX idx_cards_gold_cost        ON cards (gold_cost);
CREATE INDEX idx_cards_focus            ON cards (focus);
CREATE INDEX idx_cards_force            ON cards (force);
CREATE INDEX idx_cards_chi              ON cards (chi);
CREATE INDEX idx_cards_personal_honor   ON cards (personal_honor);
CREATE INDEX idx_cards_province_strength ON cards (province_strength);
CREATE INDEX idx_cards_starting_honor   ON cards (starting_honor);

-- Faceted attribute filters (clan/type/deck), covering card_id to avoid heap fetches.
CREATE INDEX idx_card_clans_clan        ON card_clans (clan) INCLUDE (card_id);
CREATE INDEX idx_card_card_types_type   ON card_card_types (type) INCLUDE (card_id);
CREATE INDEX idx_card_decks_deck        ON card_decks (deck) INCLUDE (card_id);
CREATE INDEX idx_card_keywords_lower_kw ON card_keywords (lower(keyword)) INCLUDE (card_id);
CREATE INDEX idx_card_creates_created   ON card_creates (created_card_id) INCLUDE (creator_card_id);
CREATE INDEX idx_card_legalities_format ON card_legalities (format_name);
CREATE INDEX idx_print_legalities_format ON print_legalities (format_name);

-- Print + image lookups (card → its prints → front image).
CREATE INDEX idx_prints_card_id         ON prints (card_id);
CREATE INDEX idx_prints_set_id          ON prints (set_id);
CREATE INDEX idx_print_images_print_role ON print_images (print_id, role) INCLUDE (path);
CREATE INDEX idx_print_numbers_print_id ON print_numbers (print_id);

-- Set metadata joins.
CREATE INDEX idx_l5r_sets_arc           ON l5r_sets (arc);

-- Revision-history lookups (card → its ordered revisions).
CREATE INDEX idx_card_revisions_card    ON card_revisions (card_id);
