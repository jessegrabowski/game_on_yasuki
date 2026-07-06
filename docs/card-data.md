# Card Data & Images

How card data, printings, errata, and art are stored, edited, and loaded.

## The golden rule

**The committed YAML files are the source of truth.** Card text, stats, printings, errata, and the
image manifests all live in version-controlled YAML under `src/yasuki_core/assets/database/`. Edit
those, reload the database, and you're done.

Image **bytes** are the one thing never committed — they live in the R2 bucket (durable) and a local
`sets/` cache. Everything else about a card is in the repo.

## Where everything lives

| What | Path | Tracked? | Role |
|------|------|----------|------|
| Card data (per set) | `src/yasuki_core/assets/database/sets/<slug>.yaml` | ✅ git | Titles, text, stats, keywords, per-printing fields, **errata** |
| Image manifests (per set) | `src/yasuki_core/assets/database/images/<slug>.yaml` | ✅ git | Maps `(card_id, printing_id)` → image files + sha256 |
| Set metadata | `src/yasuki_core/assets/database/set_info.yaml`, `set_alias.yaml` | ✅ git | Set names, codes, release dates, arcs |
| Schema | `src/yasuki_core/assets/database/schema.sql` | ✅ git | The Postgres schema |
| Local image cache | `sets/<slug>/<file>.jpg` | ❌ gitignored | Image **bytes**, served locally |
| Durable image store | R2 bucket `l5r-card-images` | — (cloud) | Image **bytes**, served in production |

**Two planes, kept separate.** *Metadata* (which cards/printings/images exist, their paths + sha256)
is the committed YAML. *Image bytes* live only in R2 and the local `sets/` cache. The manifests
reference bytes by path + sha; the bytes are synced, not versioned.

## Loading data into the database

```bash
pixi run install-db --force     # drop + rebuild the card DB from the YAML
```

`install-db` reads the set YAML (`yaml_to_sql`) and the image manifests (`images_to_sql`) into
Postgres. Without `--force` it is do-nothing-on-conflict, so use `--force` to pick up edits. The
accounts database is separate and untouched by this.

## How images resolve at read time

A manifest stores a relative path `sets/<slug>/<file>`. `IMAGE_BASE_URL` is prefixed at read time:

- **Locally** — `IMAGE_BASE_URL=/images`, served from the `sets/` directory mount.
- **Production** — `IMAGE_BASE_URL=https://pub-<id>.r2.dev`, served from R2.

So a card shows art only if (a) its manifest entry exists *and* (b) the bytes exist at that path in
`sets/` (local) or R2 (prod). A missing manifest entry OR missing bytes → no image.

To populate a fresh `sets/`, pull the bytes down from R2. With the rclone remote configured (R2 is
S3-compatible, so `aws s3` works too):

```bash
rclone copy "$R2_REMOTE:$R2_BUCKET/sets" ./sets   # remote/bucket from .env; copy is additive
```

No credentials? The public CDN can't list, but you can still fetch specific files by path — see the
[Recovery playbook](#recovery-playbook).

## Recipes

### Fix a card's rules text or stats

Edit the card's entry in `sets/<slug>.yaml`, then `pixi run install-db --force`. Decks reference the
logical `card_id`, so every deck and search result updates automatically.

### Add a new printing of an existing card

A card is one row keyed by `card_id` (a slug of its extended title); each YAML **entry** is one
printing. To add a printing, add another entry with the same title in the new set's YAML, plus its
image manifest entry. Same-set reprints get suffixed printing ids (`<slug>`, `<slug>_2`, …). Distinct
gameplay versions (e.g. Experienced) need a distinct `extended_title` so they slug to a distinct
`card_id` instead of merging.

### Issue an errata (a revision)

Errata are a **revision time-axis, orthogonal to printings** — a card can have many printings *and*
many errata independently. **Append**, never overwrite: keep the original `text:` and add an `errata:`
list to the card's entry (put it on the printing the erratum applies to; the loader collects errata
across all of a card's entries, so file order doesn't matter):

```yaml
- title: What Have You Done!?
  text: '<b>Open:</b> Dishonor a target Personality...'   # original — leave untouched
  # ...printing fields...
  errata:
  - date: 2026-07-01                                       # required, must parse
    source: Onyx Lives July 2026 Errata
    source_url: https://sites.google.com/.../july-2026-errata   # optional; where it was announced
    text: '<b>Open:</b> Dishonor a target Personality...'  # the new wording
    art: what_have_you_done__errata_2026_07.jpg            # optional; the new render
    # optional integer stat overrides, e.g.  force: 5
```

On reload, the loader mirrors the **newest** revision's text (and any stat overrides) onto the `cards`
row — so every read path and deck shows the current wording — and records the full ordered history in
`card_revisions` (revision 0 = original, highest index = current). The card page shows the current
text with an **errata badge** and an expandable history; the errata render leads the art carousel with
the pre-errata art one click away.

A missing or unparseable `date` is a hard error (loud, not a silent null). This pass covers **text +
art + stats**; keyword/type/uniqueness errata are *not* yet modelled (they'd need the junction tables
extended).

### Add or replace card art (including errata renders)

An errata render is not special — it is just a card image, so it lives in `sets/` and R2 like every
other one. To add or replace any card's art:

1. Produce an optimized progressive JPEG (quality ~95, native dimensions) at `sets/<slug>/<file>.jpg`
   — a ~10-line PIL script from whatever source you have (e.g. the errata announcement image).
2. For an errata, name it to match the errata block's `art:` field (which becomes
   `card_revisions.image_path`, e.g. `sets/chaos_reigns_part_iii/what_have_you_done__errata_2026_07.jpg`).
3. Push to R2 so it serves in production and survives a `sets/` wipe (below).

There is no separate tracked source directory: the JPEG in `sets/` + R2 is the canonical copy, exactly
as for archive-materialized cards.

### Sync image bytes to R2

```bash
pixi run sync-images              # dry run (shows what would upload)
pixi run sync-images -- --execute # upload for real (needs R2_REMOTE + R2_BUCKET / rclone configured)
```

This mirrors `sets/` (and bundled overlays/defaults) to R2. **It is a mirror** — it deletes remote
objects not present locally, so only run it against a `sets/` tree you trust to be complete.

## Recovery playbook

If manifest entries or local bytes go missing (a bad edit, an interrupted sync):

1. **Restore the metadata** from git:
   ```bash
   git checkout -- src/yasuki_core/assets/database/images/
   ```
2. **Restore the bytes** from R2. If you have the rclone remote configured (R2 is S3-compatible, so
   `aws s3` works with `--endpoint-url` too), pull the affected prefix — `copy` is additive and won't
   touch anything else:
   ```bash
   rclone copy "$R2_REMOTE:$R2_BUCKET/sets/<slug>" ./sets/<slug>
   # aws equivalent (endpoint = the R2 S3 API URL, https://<account-id>.r2.cloudflarestorage.com,
   # found in rclone.conf or the Cloudflare dashboard):
   # aws s3 sync "s3://$R2_BUCKET/sets/<slug>" "sets/<slug>" --endpoint-url "$R2_ENDPOINT"
   ```
   No credentials? The public CDN can't list, but you can fetch known paths one at a time (the
   manifest gives you the paths and sha256 to verify against):
   ```bash
   curl -sS -A "Mozilla/5.0" -o "sets/<slug>/<file>" \
     "https://pub-<id>.r2.dev/sets/<slug>/<file>"
   ```
3. **Rebuild** the database: `pixi run install-db --force`.

## Reference

### Card entry fields (`sets/<slug>.yaml`)

`title`, `types`, `decks`, `keywords`, `text`, stat fields (`gold_cost`, `focus`, `force`, `chi`,
`personal_honor`, `honor_requirement`, `province_strength`, `starting_honor`, `gold_production`),
`legality`, `rarity`, `artist`, `designer`, `flavor_text`, `collector_number`, `publisher`,
`publisher_url`. Optional identity: `id` (explicit card id), `extended_title` (experience
disambiguation), `is_back` (flip-card back face). Optional: `errata` (list), `errata_text` (a legacy
free-text note, distinct from the structured `errata:` list).

### `card_revisions` columns

`card_id`, `revision_index` (0 = original, highest = current), `effective_date`, `source`,
`source_url` (where the erratum was announced), `rules_text`, `stats` (JSONB stat overrides),
`image_path` (null → fall back to print art), `notes`. Sparse: only errata'd cards have rows.
