-- A user's avatar: the card they chose and the crop box (fractions of the image) shown as their
-- circle. The whole spec is one JSON value — {card_id, image_path, crop:{left,top,right,bottom}} —
-- so it travels as a unit; image_path is denormalized at save time so rendering needs no card-DB
-- lookup. Null until a card is picked, in which case the app falls back to the name's initials.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar jsonb;
