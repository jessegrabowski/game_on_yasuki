# How card data is authored

The committed YAML under `src/yasuki_core/assets/database/sets/` is the source of truth. Postgres
is a cache built from it, so a card that is wrong in the database is wrong in the file, and
`pixi run install-db --force` reloads it.

One file per set. Here is an entry, trimmed of its art and flavor fields, for the card behind the
worked trigger in [Reacting to events](reacting_to_events.md):

```yaml
- title: Rice Farm
  grants:
  - wealth
  types:
  - Holding
  decks:
  - Dynasty
  keywords:
  - Farm
  text: This Holding will not have more than four Wealth tokens.<br>After your turn begins, give
    this Holding a +1GP Wealth token.
  gold_cost: 2
  gold_production: 0
  legality:
  - Shattered Empire
  rarity: Fixed
```

## The id is derived, and it is not in the file

Nothing in that entry is the card's id, and the id is what every handler keys on. It is computed
from the printing's extended title, which is its title, then its subtitle, then the qualifier its
Experienced keyword prints:

```{literalinclude} ../../src/yasuki_core/card_identity.py
:pyobject: extended_title
:language: python
```

```{literalinclude} ../../src/yasuki_core/card_identity.py
:pyobject: card_id
:language: python
```

`card_slug` lowercases, turns `&` into `and`, drops apostrophes, and replaces every other run of
non-alphanumerics with an underscore. So `Rice Farm` is `rice_farm`, and Iweko Miaka with the
subtitle `Princess of Rokugan` is `iweko_miaka_princess_of_rokugan`.

A subtitle is not part of the card's title for play (CR, Card Subtitles), and it belongs to the
printing: a reprint may add one that the card's earlier printings lack. Such a printing pins the
card's existing id with an explicit `id:`, so the reprint stays the same card. An explicit `id:`
appears on 246 of 20,135 entries. Besides those pins, they are tokens, whose ids describe their
stats, and cards sharing their extended title with another card. Each of those ends in the
`short_id` that `set_info.yaml` gives the set that first printed it, as `aulus_goc` and
`aulus_cr3` do, and `pixi run card-index` refuses a shared title without them. A back face takes the
front's id plus `__back`.

Two consequences for a card author. You cannot read a card's id off the file, so derive it or look
it up in `src/yasuki_core/assets/database/card_ids.txt`, which lists every one. And a handler keyed
on a guess registers happily and never fires, which the `registration-audit` pre-commit hook
catches by naming the nearest real id.

## An id never silently disappears

Saved decks store card ids, and exported decklists name cards by the extended title they showed when
the deck was written. So an id that stops deriving from the YAML, because a title changed or two
cards were merged, is listed in `src/yasuki_core/assets/database/retired_ids.yaml` with the id that
replaces it, or `null` for a card that is gone. `pixi run card-index` refuses to drop an id from
`card_ids.txt` that is not listed there. Decklist import and saved decks read a retired id as its
successor, so old decks keep loading the card they meant.

## Card-level against printing-level

A card is one logical thing printed many times. `Rice Farm` is one row in `cards`, keyed by that
derived id, with the canonical text and stats. Each physical printing is a row in `prints`, keyed
by set, and a printing may override the text.

Art attaches to printings, not to cards. That is why showing a card face on a page names the
printing, and why the image manifests under `assets/database/images/` map a card id to a file per
printing.

## Errata are a time axis, not an edit

An erratum appends a revision rather than rewriting the entry. `card_revisions` holds them in
order, revision 0 being the original, and the current one is mirrored onto the `cards` row so an
ordinary read needs no join. A card's text as originally printed and its text as played today are
both available, and the engine reads the latter.

## Adding a set

The full pipeline, the schema and the image workflow are in
[Database and card data](../design/database.md). The short version is in
[Contributing](index.md#adding-a-card-set): add the set YAML and its image manifest, reload the
database, then regenerate the card-id index with `pixi run card-index` and commit it.
