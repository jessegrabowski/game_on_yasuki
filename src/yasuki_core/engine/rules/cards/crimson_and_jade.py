from yasuki_core.engine.rules.rulebook.lobby import may_not_lobby
from yasuki_core.engine.rules.abilities.idioms import register_event_entry


# --- Matsu Goemon ---

# "Goemon may not Lobby." His Follower-Equip line needs no handler here.
may_not_lobby("matsu_goemon")


# --- Shadow of the Dark God ---

register_event_entry("shadow_of_the_dark_god")
