import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from numpy.random import Generator

from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.decisions import ChoosePayment
from yasuki_gui.config import load_hotkeys
from yasuki_gui.services.game_host import GameHost
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.session import DEMO_DECK_PATH
from yasuki_gui.ui.game_window import GameWindow


@dataclass(frozen=True, slots=True)
class Client:
    """A built desktop client, handed back so a caller can run it and a test can drive it.

    Scaffolding, and temporary: it exposes the collaborators the entry point wires together so a
    caller can reach them, and it disappears once the entry point is only that wiring.

    Attributes
    ----------
    window : GameWindow
        Every widget the client draws.
    host : GameHost
        The live game — the decks it was dealt from, the session, and the runner driving it. Held
        rather than the runner itself, which a deck load replaces.
    presenter : Presenter
        Turns what the engine wants next into what the board and the prompt show, and answers back.
    load_human_deck : callable
        Deals the decklist at the given path to the human and restarts the game.
    load_opponent_deck : callable
        Deals the decklist at the given path to the AI opponent and restarts the game.
    """

    window: GameWindow
    host: GameHost
    presenter: Presenter
    load_human_deck: Callable[[str], None]
    load_opponent_deck: Callable[[str], None]

    def run(self) -> None:
        """Enter the event loop. The client is already built and has presented its opening state."""
        self.window.root.mainloop()


def build_client(
    *,
    human_deck: Path = DEMO_DECK_PATH,
    opponent_deck: Path = DEMO_DECK_PATH,
    rng: Generator | None = None,
) -> Client:
    """Build the client and hand it back unrun.

    Parameters
    ----------
    human_deck : pathlib.Path, optional
        The decklist dealt to the human. Default the bundled deck.
    opponent_deck : pathlib.Path, optional
        The decklist dealt to the AI opponent. Default the bundled deck, a mirror match.
    rng : numpy.random.Generator, optional
        Deals every game this client starts, including the ones a deck load restarts. Default None,
        which deals from system entropy — what a game wants, where a repeated opening is a defect.
    """
    # The human always sits at P1; who takes the first turn is decided by Family Honor at deal.
    host = GameHost(human_deck, opponent_deck, rng=rng)
    window = GameWindow(host.session.game.table, host.human_seat)
    presenter = Presenter(host, window)

    def popup_action_menu(items: list[tuple[str, Action]]) -> None:
        """Pop up a left-click action menu at the pointer; each entry performs its action. No-op
        when there is nothing to offer."""
        if not items:
            return
        menu = tk.Menu(window.root, tearoff=0)
        for label, action in items:
            menu.add_command(label=label, command=lambda chosen=action: presenter.act(chosen))
        try:
            menu.tk_popup(window.root.winfo_pointerx(), window.root.winfo_pointery())
        finally:
            menu.grab_release()

    def on_card_activated(card_id: str) -> None:
        # A left-click opens what the card offers: a face-up province card's Recruit / Dynasty
        # Discard, a hand card's Kharmic, or an in-play card's activated ability. The ensuing
        # target/payment is picked through the board-selection path.
        popup_action_menu(
            host.runner.province_menu(card_id)
            + host.runner.hand_menu(card_id)
            + host.runner.ability_menu(card_id)
            + host.runner.inheritance_menu(card_id)
        )

    def on_board_menu() -> None:
        # A right-click on empty board opens the rulebook abilities. They act on whole zones rather
        # than on a card, so there is no card to left-click for them.
        popup_action_menu(host.runner.board_menu())

    def undo(_event=None) -> None:
        # Ctrl+Z: back out of an open boost question first, else while paying unbow the last producer
        # tapped for gold, else undo a just-made Dynasty Discard, if nothing else has happened since.
        if window.field.pending_boost is not None:
            window.field.cancel_boost()
            presenter.refresh()
        elif isinstance(host.runner.pending, ChoosePayment):
            window.field.undo_last_selection()
        elif host.runner.undo_last():
            window.field.state = host.session.game.table
            window.field.end_selection()
            presenter.refresh()

    def cancel_via_escape(_event=None) -> None:
        # Escape backs out of a cancellable pending decision (a recruit payment); no effect
        # otherwise, leaving the board's own Escape (clear selection) untouched.
        pending = host.runner.pending
        if pending is not None and pending.cancellable:
            presenter.cancel()

    # Re-render (board borders + confirm-button state) as the player toggles candidates.
    window.field.on_boost_request = presenter.request_boost
    window.field.on_selection_changed = presenter.refresh
    window.field.on_card_activated = on_card_activated
    window.field.on_board_menu = on_board_menu
    window.root.bind("<Control-z>", undo)
    window.root.bind("<Escape>", cancel_via_escape)
    window.field.configure_hotkeys(load_hotkeys())

    def show_new_game() -> None:
        """Render the game the host just dealt. Every deck load ends here."""
        window.field.state = host.session.game.table
        window.field.seat = host.human_seat
        window.field.end_selection()
        window.relayout_panels()
        presenter.present()

    def load_human_deck(path: str) -> None:
        host.load_human_deck(path)
        show_new_game()

    def load_opponent_deck(path: str) -> None:
        host.load_opponent_deck(path)
        show_new_game()

    window.field.load_deck_from_file = load_human_deck
    window.field.load_opponent_deck_from_file = load_opponent_deck

    # Renders the opening board and hands over to the opponent, which is what moves a game
    # whose first turn is not the human's.
    presenter.present()

    return Client(
        window=window,
        host=host,
        presenter=presenter,
        load_human_deck=load_human_deck,
        load_opponent_deck=load_opponent_deck,
    )


def main() -> None:
    build_client().run()


if __name__ == "__main__":
    main()
