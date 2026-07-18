# Search Query Language

The deck builder search box accepts a Scryfall-inspired query syntax. Type a query
to filter cards in real time; click the **?** button next to the box for inline help.

## Quick Start

| Query | Finds |
|-------|-------|
| `Doji` | Cards with "Doji" in the name or text |
| `clan:Crane type:personality` | Crane personalities |
| `force>3 is:unique` | Unique cards with Force greater than 3 |

## Field Search

| Field | Aliases | Example |
|-------|---------|---------|
| `name:` | — | `name:Hoturi` (accent-insensitive) |
| `text:` | `o:` (oracle) | `o:battle` |
| `type:` | `t:` | `t:personality` |
| `clan:` | `c:` | `c:Crane` |
| `set:` | `s:` | `s:"Imperial Edition"` |
| `rarity:` | `r:` | `r:rare` |
| `deck:` | `side:` | `deck:fate` |
| `format:` | — | `format:"Ivory Edition"` |
| `year:` | `yr:` | `year>=2010` |

Values with spaces need quotes: `set:"Imperial Edition"`. `year:` matches a card's
release year against any printing's set, and takes the numeric operators
(`year:2005`, `year>=2010`, `year<2000`).

## Numeric Fields

`force` (`f`), `chi`, `focus`, `gold` (cost), `ph` (personal honor),
`province` (strength), `startinghonor`, `honor_requirement`, and `experience`
(`exp`) — the version rank, from `-1` (Inexperienced) through `0` (base) to
Experienced 2 and up.

| Operator | Meaning | Example |
|----------|---------|---------|
| `:` or `=` | Equals | `focus:2` |
| `>` | Greater than | `force>3` |
| `>=` | Greater or equal | `force>=4` |
| `<` | Less than | `chi<2` |
| `<=` | Less or equal | `gold<=3` |
| `N-M` | Inclusive range | `force:2-4` |

## Keyword Filters

`is:<keyword>` (alias `has:`) matches any card keyword: `is:unique`,
`is:experienced`, `is:cavalry`, `is:kenshi`, `is:shugenja`, and so on. Multiple
keyword filters use AND — cards must have all of them:

```
is:shugenja is:shadowlands
```

Besides keywords and `is:unique`/`is:banned`, two card flags are searchable:
`is:flip` (a double-faced flip stronghold) and `is:errata` (has errata text).

## Combining Terms

Terms are ANDed by default. Use `OR` for alternatives, `(...)` to group, `-` to
exclude, and `!"..."` for an exact card-name match:

```
clan:Crane type:personality force>3            # all three (AND)
clan:Crane OR clan:Lion                         # either clan
(c:crane is:courtier) OR (c:lion is:samurai)    # Crane courtiers or Lion samurai
is:shugenja|courtier                            # either keyword (is: pipe)
clan:Crane -type:event                          # Crane, excluding events
-(c:crab OR c:scorpion)                         # neither clan
-doji                                           # exclude cards matching "doji"
"Doji Hoturi"                                   # substring phrase
!"Doji Hoturi"                                  # exact card name (all its versions)
```

`AND` binds tighter than `OR`, so `a OR b c` means `a OR (b AND c)`; parentheses
override that. Queries are case-insensitive (`clan:crane` = `clan:Crane`).

`-` works on any field: `-type:event`, `-clan:crane`, `-artist:Hara`,
`-format>=diamond`. For an inequality it is the strict complement of the positive
filter — `-format>=diamond` means "legal in **no** format at or after diamond"
(cards that rotated out earlier), not "legal in some earlier format". An
unresolvable reference in a negated `format`/`set` term (a typo like `-set:xyz`)
matches nothing rather than everything.

## Examples

```
c:Crane t:personality f>=4                # powerful Crane personalities
gold<=2 -type:holding                     # cheap non-holdings
c:crane t:personality is:shugenja|courtier # Crane shugenja or courtiers
(c:dragon OR c:phoenix) t:personality f>=3 # Dragon or Phoenix bruisers
is:unique t:personality chi>=2            # unique personalities, high chi
is:cavalry clan:Unicorn force>=3          # Unicorn cavalry rush
t:personality gold<=2 -is:unique          # cheap spam
```

The search box and the filter dialog combine — queries parse alongside any active
dialog filters.
