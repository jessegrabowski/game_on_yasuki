import tkinter as tk
from collections.abc import Callable

from yasuki_gui import theme
from yasuki_gui.ui.floating_panel import FloatingPanel

OPTIONS_W = 460
# Where the panel starts before it has laid out a question, which then sizes it to fit.
OPTIONS_H = 160
# Inside the panel's padding, how wide an outcome's wording runs before it wraps.
OPTION_WRAP = OPTIONS_W - 48


class OptionsView(FloatingPanel):
    """A question whose outcomes may be picked several at once, as which of a Strategy's Invests
    to pay: a tick box per outcome and a button that answers with what is ticked.

    Opened and closed by the game rather than the player, like the look: a stray dismissal would
    hide a question the seat still owes an answer to.
    """

    def __init__(self, master: tk.Misc):
        super().__init__(master, "Choose", width=OPTIONS_W, height=OPTIONS_H)
        self._ticks: dict[str, tk.BooleanVar] = {}

    def ask(
        self,
        question: str,
        options: tuple[str, ...],
        accepts: Callable[[tuple[str, ...]], bool],
        on_submit: Callable[[tuple[str, ...]], None],
        on_cancel: Callable[[], None] | None,
    ) -> None:
        """Lay out ``question`` with a tick box per outcome in ``options``, all unticked, and size
        the panel to fit them.

        Submit is enabled only while the ticked set is one ``accepts`` takes, and calls
        ``on_submit`` with it in the order listed. Cancel calls ``on_cancel``, and is offered only
        when there is one.
        """
        for child in self.body.winfo_children():
            child.destroy()
        tk.Label(
            self.body,
            text=question,
            bg=theme.SURFACE,
            fg=theme.INK,
            font=theme.serif(12, "bold"),
            wraplength=OPTION_WRAP,
            justify="left",
            anchor="w",
        ).pack(side="top", fill="x", padx=12, pady=(10, 6))
        self._ticks = {option: tk.BooleanVar(value=False) for option in options}
        buttons = tk.Frame(self.body, bg=theme.SURFACE)
        submit = tk.Button(buttons, text="Submit", command=lambda: on_submit(self.ticked()))

        def refresh() -> None:
            submit.configure(state="normal" if accepts(self.ticked()) else "disabled")

        for option, ticked in self._ticks.items():
            tk.Checkbutton(
                self.body,
                text=option,
                variable=ticked,
                command=refresh,
                anchor="w",
                justify="left",
                wraplength=OPTION_WRAP,
                bg=theme.SURFACE,
                fg=theme.INK,
                activebackground=theme.SURFACE,
            ).pack(side="top", fill="x", padx=12, pady=2)
        buttons.pack(side="top", pady=(8, 10))
        submit.pack(side="left", padx=4)
        if on_cancel is not None:
            tk.Button(buttons, text="Cancel", command=on_cancel).pack(side="left", padx=4)
        refresh()
        # The wording wraps to the panel's width, so the height it needs is only known once laid
        # out, and a fixed one leaves a short question floating in empty panel.
        self.update_idletasks()
        self._panel_height = self.winfo_reqheight()

    def ticked(self) -> tuple[str, ...]:
        """The outcomes ticked, in the order they are listed."""
        return tuple(option for option, ticked in self._ticks.items() if ticked.get())
