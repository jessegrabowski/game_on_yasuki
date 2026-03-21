# L5R Deck Builder - Search Query Quick Reference

## Basic Syntax

| Syntax | Description | Example |
|--------|-------------|---------|
| `text` | Plain text search | `Doji` |
| `field:value` | Field-specific | `clan:Crane` |
| `field>number` | Numeric comparison | `force>3` |
| `"exact phrase"` | Exact match | `"Doji Hoturi"` |
| `-term` | Exclude | `-type:event` |
| `term1 term2` | AND logic | `clan:Crane force>3` |
| `term1 OR term2` | OR logic | `clan:Crane OR clan:Lion` |

## Field Shortcuts

| Short | Full | Example |
|-------|------|---------|
| `t:` | `type:` | `t:personality` |
| `c:` | `clan:` | `c:Crane` |
| `f` | `force` | `f>3` |
| `o:` | `text:` (oracle) | `o:battle` |
| `s:` | `set:` | `s:"Imperial Edition"` |
| `r:` | `rarity:` | `r:rare` |
| `has:` | `is:` | `has:cavalry` |

## Numeric Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `:` or `=` | Equals | `force:3` |
| `>` | Greater than | `chi>2` |
| `>=` | Greater or equal | `gold>=4` |
| `<` | Less than | `focus<5` |
| `<=` | Less or equal | `ph<=1` |

## Special Filters

| Filter | Description |
|--------|-------------|
| `is:unique` or `has:unique` | Only unique cards |
| `is:cavalry` or `has:cavalry` | Cards with cavalry keyword |
| `is:experienced` or `has:experienced` | Cards with experienced keyword |
| `is:kenshi` or `has:kenshi` | Cards with kenshi keyword |
| `is:<keyword>` or `has:<keyword>` | Any keyword from database |

**Note**: Multiple keywords use AND logic (cards must have ALL keywords):
- `is:shugenja is:shadowlands` → Cards with both keywords
- `has:cavalry has:experienced` → Cards with both keywords

## Common Queries

### By Type & Clan
```
t:personality c:Crane
```

### Multiple Keywords (AND Logic)
```
is:shugenja is:shadowlands
has:cavalry has:experienced
```

### Power Level
```
f>=4 chi>=2
```

### Cost Range
```
gold<=3 -type:holding
```

### Keywords
```
is:cavalry clan:Unicorn
```

### Combined
```
c:Crane t:personality f>3 is:unique
```

### Multiple Clans
```
clan:Crane OR clan:Lion
```

### Experienced Cards
```
is:experienced clan:Dragon
```

### Budget Cards
```
gold<=2 -type:event
```

### Unique Personalities
```
is:unique t:personality f>=3
```

### Cavalry Search
```
is:cavalry force>3
```

## Tips

1. **Case insensitive**: `clan:crane` = `clan:Crane`
2. **Spaces in values**: Use quotes `set:"Imperial Edition"`
3. **Multiple keywords**: `is:cavalry is:experienced` (OR logic)
4. **Combine filters**: Mix search box and Filter dialog
5. **Help button**: Click `?` next to search box for full help

## Examples by Playstyle

### Aggro
```
t:personality f>=4 gold<=4
```

### Control
```
t:holding OR t:region
```

### Cavalry Rush
```
is:cavalry clan:Unicorn force>=3
```

### Experienced Characters
```
is:experienced is:unique
```

### Cheap Spam
```
t:personality gold<=2 -is:unique
```

### High Force
```
t:personality f>=5
```

### Chi Support
```
chi>=2 t:personality
```

---

**Need more help?** Click the **?** button next to the search box!
