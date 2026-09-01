import tkinter as tk
from collections.abc import Callable, Iterable

from yasuki_gui import theme

# A button to offer: its label, the callback to run, and whether it is enabled.
ButtonSpec = tuple[str, Callable[[], None], bool]


class PromptBox(tk.Frame):
    """The prompt panel between the two seats: what is being asked, and a button for each offered
    choice. The host (presenter) builds the status text and the buttons; this widget only renders
    them."""

    def __init__(self, master: tk.Misc):
        super().__init__(master, bg=theme.PANEL)
        self._status = tk.Label(
            self, bg=theme.PANEL, fg=theme.INK, font=theme.serif(12, "bold"), wraplength=180
        )
        self._status.pack(side="top", fill="x", padx=8, pady=(12, 8))
        self._actions = tk.Frame(self, bg=theme.PANEL)
        self._actions.pack(side="top", fill="x", padx=8)
        self._buttons: list[tk.Button] = []
        self._spinner: tk.Spinbox | None = None

    def show(
        self, status: str, buttons: Iterable[ButtonSpec], amounts: tuple[str, ...] | None = None
    ) -> None:
        """Render ``status``, a spinner over ``amounts`` when there are any, and a button per spec.

        A seat naming its own number gets one control it steps through rather than a button per
        value: the amounts a variable Gold cost offers run as high as the seat can pay, and that is
        a list no panel this width can hold.
        """
        self._status.configure(text=status)
        for child in self._actions.winfo_children():
            child.destroy()
        self._buttons = []
        self._spinner = None
        if amounts:
            self._spinner = tk.Spinbox(
                self._actions,
                values=amounts,
                state="readonly",
                justify="center",
                width=6,
                font=theme.serif(13, "bold"),
            )
            self._spinner.pack(side="top", pady=(0, 6))
        for label, command, enabled in buttons:
            button = tk.Button(
                self._actions,
                text=label,
                state="normal" if enabled else "disabled",
                command=command,
            )
            button.pack(side="top", fill="x", pady=2)
            self._buttons.append(button)

    def amount(self) -> str:
        """The number the spinner is showing, or an empty string when none is up."""
        return self._spinner.get() if self._spinner is not None else ""

    def invoke_primary(self) -> None:
        """Invoke the primary action — the first button — when enabled; the spacebar shortcut. The
        presenter lists the affirmative action (Pass/Pay/Discard) first, so a secondary button such
        as Cancel is never triggered this way."""
        if self._buttons and str(self._buttons[0].cget("state")) == "normal":
            self._buttons[0].invoke()
