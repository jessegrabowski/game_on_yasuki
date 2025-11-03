import tkinter as tk

from app.gui.ui.dialogs import Dialogs
from app.gui.ui.images import ImageProvider


def build_menubar(root: tk.Misc, field_view) -> tk.Menu:
    menubar = tk.Menu(root)
    app_menu = tk.Menu(menubar, tearoff=0)

    def open_prefs() -> None:
        # Determine which player panel is local from the field_view and update a stored profile on field_view
        name = getattr(field_view, "profile_name", "Player")
        avatar = getattr(field_view, "profile_avatar", None)
        dialogs = Dialogs(root, ImageProvider(root))

        def apply_prefs(new_name: str, new_avatar: str | None) -> None:
            setattr(field_view, "profile_name", new_name)
            setattr(field_view, "profile_avatar", new_avatar)
            # Notify UI to update player panels if available
            cb = getattr(field_view, "apply_profile_to_panels", None)
            if callable(cb):
                cb()

        dialogs.preferences(name, avatar, apply_prefs)

    app_menu.add_command(label="Preferences…", command=open_prefs)
    app_menu.add_separator()
    app_menu.add_command(label="Quit", command=lambda: root.winfo_toplevel().destroy())
    menubar.add_cascade(label="App", menu=app_menu)
    return menubar
