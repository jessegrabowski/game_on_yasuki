# Game on, Yasuki!

Online client for playing the Legend of the Five Rings (L5R) collectible card
game — a desktop GUI, a card database, a deck builder, and a multiplayer server.

The project is three Python packages with a strict dependency direction
(`yasuki_core ← yasuki_web`, `yasuki_core ← yasuki_gui`):

| Package | Role |
|---------|------|
| **`yasuki_core`** | Game engine, card models, database, search, card data |
| **`yasuki_web`** | FastAPI server — multiplayer rooms, deck builder SPA |
| **`yasuki_gui`** | Tkinter desktop client — board, drag & drop, deck builder |

Start with [Getting Started](getting_started/index.md). For how the software is put together, see
[Design & Architecture](design/index.md); for the per-package reference, see the
[API Reference](api/index.rst).

```{toctree}
:hidden:

getting_started/index
design/index
api/index
contributing/index
style_guide/index
```
