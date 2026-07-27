# Design & Architecture

How Game on, Yasuki! is built as software: the core engine and its data model, and how the web server
and desktop client surface that same engine. The dependency direction is one-way —
`yasuki_core ← yasuki_web` and `yasuki_core ← yasuki_gui`, with no coupling between web and gui.

```{toctree}
:maxdepth: 1

engine
database
web-app
tk-client
search
```
