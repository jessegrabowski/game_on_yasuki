CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TYPE deck_type AS ENUM ('FATE', 'DYNASTY', 'PRE_GAME', 'OTHER');

CREATE TYPE card_type AS ENUM (
  'Strategy',
  'Region',
  'Event',
  'Spell',
  'Holding',
  'Item',
  'Personality',
  'Follower',
  'Wind',
  'Celestial',
  'Stronghold',
  'Sensei',
  'Ancestor',
  'Ring',
  'Proxy',
  'Other',
  'Clock',
  'Territory'
);

CREATE TYPE legality_status AS ENUM ('legal', 'restricted', 'banned', 'not_legal');

CREATE TABLE cards (
  id              TEXT PRIMARY KEY,

  name            TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  extended_title  TEXT NOT NULL,

  deck            deck_type NOT NULL,
  type            card_type NOT NULL,
  clan            TEXT,

  rules_text      TEXT NOT NULL DEFAULT '',

  gold_cost       INT,
  focus           INT,

  force           INT,
  chi             INT,

  honor_requirement INT,
  personal_honor    INT,

  gold_production INT,

  province_strength INT,
  starting_honor    INT,

  is_unique       BOOLEAN NOT NULL DEFAULT FALSE,
  is_proxy        BOOLEAN NOT NULL DEFAULT FALSE,

  errata_text     TEXT,
  notes           TEXT,

  extra           JSONB NOT NULL DEFAULT '{}'::jsonb,

  rules_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(rules_text, ''))
  ) STORED
);


DROP TABLE IF EXISTS print_numbers;
DROP TABLE IF EXISTS prints;

CREATE TABLE prints (
  print_id             SERIAL PRIMARY KEY,
  card_id              TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,

  set_name             TEXT NOT NULL,
  set_code             TEXT,

  rarity               TEXT,
  flavor_text          TEXT,
  artist               TEXT,

  -- primary number for convenience
  primary_subset       TEXT,
  primary_number_int   INT,
  collector_number_raw TEXT,  -- full original string

  notes                TEXT,
  image_path           TEXT,
  release_date         DATE,
  extra                JSONB NOT NULL DEFAULT '{}'::jsonb,

  UNIQUE (card_id, set_name, collector_number_raw)
);

CREATE TABLE print_numbers (
  id          SERIAL PRIMARY KEY,
  print_id    INT NOT NULL REFERENCES prints(print_id) ON DELETE CASCADE,
  subset      TEXT,
  number_int  INT NOT NULL,
  position    INT NOT NULL
);

CREATE INDEX idx_print_numbers_print_id ON print_numbers(print_id);


CREATE TABLE keywords (
  keyword TEXT PRIMARY KEY
);

CREATE TABLE card_keywords (
  card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  keyword TEXT NOT NULL REFERENCES keywords(keyword) ON DELETE CASCADE,
  PRIMARY KEY (card_id, keyword)
);


CREATE TABLE formats (
  name TEXT PRIMARY KEY
);

CREATE TABLE card_legalities (
  card_id     TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  format_name TEXT NOT NULL REFERENCES formats(name) ON DELETE CASCADE,
  status      legality_status NOT NULL DEFAULT 'legal',
  PRIMARY KEY (card_id, format_name)
);

CREATE TABLE l5r_sets (
  id                SERIAL PRIMARY KEY,
  arc               TEXT NOT NULL,
  set_name          TEXT,
  release_raw       TEXT,
  featured_factions TEXT,
  size_raw          INT,
  border            TEXT,
  code              TEXT,
  notes             TEXT
);

-- Fuzzy name search
CREATE INDEX idx_cards_name_trgm
  ON cards USING gin (name gin_trgm_ops);

-- Normalized name search/sorting
CREATE INDEX idx_cards_name_normalized
  ON cards (name_normalized);

-- Text search (substring style)
CREATE INDEX idx_cards_rules_text_trgm
  ON cards USING gin (rules_text gin_trgm_ops);

-- Full-text search on rules text
CREATE INDEX idx_cards_rules_tsv
  ON cards USING gin (rules_tsv);

-- Common filters: deck/type/clan
CREATE INDEX idx_cards_deck_type_clan
  ON cards (deck, type, clan);

-- Numeric stat filters
CREATE INDEX idx_cards_gold_cost
  ON cards (gold_cost);

CREATE INDEX idx_cards_focus
  ON cards (focus);

CREATE INDEX idx_cards_force
  ON cards (force);

CREATE INDEX idx_cards_chi
  ON cards (chi);

CREATE INDEX idx_cards_personal_honor
  ON cards (personal_honor);

CREATE INDEX idx_cards_province_strength
  ON cards (province_strength);

CREATE INDEX idx_cards_starting_honor
  ON cards (starting_honor);

-- Keyword & legality lookups
CREATE INDEX idx_card_keywords_keyword
  ON card_keywords (keyword);

CREATE INDEX idx_card_legalities_format
  ON card_legalities (format_name);

CREATE INDEX idx_l5r_sets_code ON l5r_sets(code);
