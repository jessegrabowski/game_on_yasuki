from pathlib import Path

from numpy.random import Generator

from yasuki_gui.services.game_host import GameHost
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.session import DEMO_DECK_PATH
from yasuki_gui.ui.game_window import GameWindow


def build_client(
    *,
    human_deck: Path = DEMO_DECK_PATH,
    opponent_deck: Path = DEMO_DECK_PATH,
    rng: Generator | None = None,
) -> Presenter:
    """Build the desktop client and hand back the presenter driving it, with its opening board
    already shown and its event loop not yet entered.

    Parameters
    ----------
    human_deck : pathlib.Path, optional
        The decklist dealt to the human. Default the bundled deck.
    opponent_deck : pathlib.Path, optional
        The decklist dealt to the AI opponent. Default the bundled deck, a mirror match.
    rng : numpy.random.Generator, optional
        Deals every game this client starts, including the ones a deck load restarts. Default None,
        which deals from system entropy — what a game wants, where a repeated opening is a defect.

    Returns
    -------
    Presenter
        The client's controller, holding the host it plays and the window it draws on.
    """
    # The human always sits at P1; who takes the first turn is decided by Family Honor at deal.
    host = GameHost(human_deck, opponent_deck, rng=rng)
    window = GameWindow(host.session.game.table, host.human_seat)
    presenter = Presenter(host, window)
    window.bind_to(presenter)
    # Renders the opening board and hands over to the opponent, which is what moves a game whose
    # first turn is not the human's.
    presenter.present()
    return presenter


def main() -> None:
    build_client().window.run()


if __name__ == "__main__":
    main()
