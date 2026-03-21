# Search Query Language

The deck builder now includes a powerful Scryfall-inspired search query language that allows you to quickly filter cards using a concise syntax.

## Quick Start

Just type in the search box:
- `Doji` - Find cards with "Doji" in name or text
- `clan:Crane type:personality` - Crane personalities
- `force>3 is:unique` - Unique cards with Force > 3

Click the **?** button next to the search box for full syntax help.

## Features

### Field-Specific Search
Search specific card properties:
- `name:Hoturi` - Card name
- `text:battle` or `o:battle` - Rules text (o = oracle)
- `type:personality` or `t:personality` - Card type
- `clan:Crane` or `c:Crane` - Clan
- `deck:fate` or `side:fate` - Deck side (FATE/DYNASTY)
- `set:"Imperial Edition"` - Set name
- `rarity:rare` or `r:rare` - Rarity
- `format:"Ivory Edition"` - Format legality

### Numeric Comparisons
Use operators for numeric searches:
- `force>3` - Greater than
- `force>=3` - Greater than or equal
- `chi<2` - Less than
- `gold<=3` - Less than or equal (gold = gold_cost)
- `focus:2` or `focus=2` - Exactly equal

Supported numeric fields:
- `force`, `chi`, `focus`, `gold` (cost)
- `ph` (personal honor), `province` (strength)
- `startinghonor`, `honor_requirement`

### Special Filters
- `is:unique` - Only unique cards
- `is:experienced` - Cards with "experienced" keyword
- `is:cavalry` - Cards with "cavalry" keyword
- `is:kenshi` - Cards with "kenshi" keyword
- `is:<keyword>` - Any card keyword

### Combining Terms
Multiple terms use AND by default:
```
clan:Crane type:personality force>3
```

Use OR for alternatives:
```
clan:Crane OR clan:Lion
```

### Negation
Use `-` to exclude:
```
clan:Crane -type:event
```

### Exact Match
Use quotes for exact phrases:
```
"Doji Hoturi"
```

## Examples

Find powerful Crane personalities:
```
c:Crane t:personality f>=4
```

Find cheap non-holding cards:
```
gold<=2 -type:holding
```

Find Experienced cards from specific clans:
```
name:Experienced (c:Dragon OR c:Phoenix)
```

Find unique personalities with high chi:
```
is:unique t:personality chi>=2
```

Find cavalry personalities:
```
is:cavalry t:personality
```

Find experienced Crane cards:
```
is:experienced clan:Crane
```

## Integration with Filter Dialog

The search query language works alongside the filter dialog. Filters from both sources are combined:
- Search box queries parse in real-time
- Filter dialog provides GUI-based filtering
- Both can be used together for maximum control

## Implementation Details

### Parser Architecture
- **Tokenizer**: Handles quoted strings and field:value pairs
- **Parser**: Converts tokens to SearchTerm objects with field, operator, value
- **Filter Builder**: Converts parsed terms to database query format
- **Integration**: Merges with FilterOptions from dialog

### Files
- `parse_search.py` - Core parser implementation
- `search_help.py` - Help dialog
- `deck_components.py` - Integration with FilteredCardList
- `test_parse_search.py` - Comprehensive test suite (48 tests)

### Field Aliases

Short aliases for quick typing:

| Alias | Full Field | Example |
|-------|------------|---------|
| `o` | `text` | `o:battle` |
| `t` | `type` | `t:personality` |
| `c` | `clan` | `c:Crane` |
| `f` | `force` | `f>3` |
| `s` | `set` | `s:IE` |
| `r` | `rarity` | `r:rare` |
| `gold` | `gold_cost` | `gold<=3` |
| `ph` | `personal_honor` | `ph>=2` |
| `province` | `province_strength` | `province>5` |

## Testing

Run tests:
```bash
pytest tests/gui/ui/deck_builder/test_parse_search.py -v
```

All 48 parser tests cover:
- Field normalization and aliases
- Tokenization (including quoted strings)
- Token parsing (operators, negation, special fields)
- Query parsing (AND/OR logic)
- Filter building (conversion to database format)
- End-to-end integration tests

## Future Enhancements

Potential additions:
- Regex support: `/pattern/`
- Keywords search: `keyword:cavalry`
- Full-text search operators
- Saved search queries
- Search history
- Auto-complete suggestions
