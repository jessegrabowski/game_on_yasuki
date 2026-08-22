import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.deck_builder import open_deck_builder as _open_deck_builder


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
            if field_view.apply_profile_to_panels is not None:
                field_view.apply_profile_to_panels()

        dialogs.preferences(name, avatar, apply_prefs)

    app_menu.add_command(label="Preferences…", command=open_prefs)
    app_menu.add_separator()
    app_menu.add_command(label="Quit", command=lambda: root.winfo_toplevel().destroy())
    menubar.add_cascade(label="App", menu=app_menu)

    # Deck menu: load deck and open deck builder
    deck_menu = tk.Menu(menubar, tearoff=0)

    def pick_deck(title: str, hook: str) -> None:
        """Ask for a decklist and hand it to ``field_view``'s ``hook``, reporting a failed load."""
        path = filedialog.askopenfilename(
            parent=root,
            title=title,
            initialdir=str(Path(__file__).resolve().parent.parent / "assets" / "decks"),
            filetypes=[
                ("Deck lists", ".yaml .yml"),
                ("All files", "*"),
            ],
        )
        if not path:
            return
        loader = getattr(field_view, hook, None)
        if callable(loader):
            try:
                loader(path)
            except Exception as exc:
                messagebox.showerror(title, f"Failed to load deck:\n{exc}", parent=root)
        else:
            messagebox.showinfo(
                title,
                f"Selected deck file:\n{path}\n\n(Loading not yet implemented)",
                parent=root,
            )

    def open_deck_builder() -> None:
        # Open the full deck builder UI
        _open_deck_builder(root)

    deck_menu.add_command(
        label="Load Deck…", command=lambda: pick_deck("Load Deck", "load_deck_from_file")
    )
    deck_menu.add_command(
        label="Load Opponent Deck…",
        command=lambda: pick_deck("Load Opponent Deck", "load_opponent_deck_from_file"),
    )
    deck_menu.add_separator()
    deck_menu.add_command(label="Deck Builder…", command=open_deck_builder)
    menubar.add_cascade(label="Deck", menu=deck_menu)

    return menubar
