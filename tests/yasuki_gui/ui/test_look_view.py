import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_gui.ui.look_view import LookView

from tests.yasuki_core.engine.builders import fate_card
from tests.yasuki_gui.conftest import DummyEventNamespace, PreviewOnlyImages

P1 = PlayerId.P1


@pytest.fixture
def view():
    root = tk.Tk()
    root.withdraw()
    look_view = LookView(root, PreviewOnlyImages())
    look_view.open_at(0, 0)
    root.update_idletasks()
    try:
        yield look_view
    finally:
        root.destroy()


def _cards(*ids: str):
    cards = [fate_card(card_id, P1) for card_id in ids]
    for card in cards:
        card.turn_face_down()  # as a card in a deck is
    return cards


def _center(view, tag):
    left, top, right, bottom = view.canvas.bbox(tag)
    return DummyEventNamespace(x=(left + right) // 2, y=(top + bottom) // 2)


def test_cards_are_laid_left_to_right_top_of_the_deck_first(view):
    view.refresh(_cards("top", "second", "third"), frozenset({"top", "second", "third"}))

    xs = [view._drawn[f"card:{card_id}"].x for card_id in ("top", "second", "third")]
    assert xs == sorted(xs)


def test_a_looked_at_card_is_drawn_face_up_though_it_lies_face_down_in_the_deck(view):
    view.refresh(_cards("top"), frozenset({"top"}))

    drawn = view._drawn["card:top"].card
    assert drawn.face_up
    assert view.card_under_pointer(
        view.canvas.winfo_rootx() + view._drawn["card:top"].x,
        view.canvas.winfo_rooty() + view._drawn["card:top"].y,
    )[0].face_up


def test_clicking_an_offered_card_reports_it(view):
    picked = []
    view.on_card_click = picked.append
    view.refresh(_cards("top", "second"), frozenset({"top", "second"}))

    view._on_click(_center(view, "card:second"))

    assert picked == ["second"]


def test_a_card_the_question_does_not_offer_is_veiled_and_reports_nothing(view):
    picked = []
    view.on_card_click = picked.append
    view.refresh(_cards("top", "second"), frozenset({"top"}))

    view._on_click(_center(view, "card:shown:second"))

    assert picked == []
    assert view.canvas.find_withtag("veil")


def test_a_placed_card_is_not_drawn(view):
    view.refresh(_cards("top", "second"), frozenset({"top", "second"}), placed=frozenset({"top"}))

    assert set(view._drawn) == {"card:second"}
