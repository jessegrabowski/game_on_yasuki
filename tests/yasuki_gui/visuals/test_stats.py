import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, HoldingPrint, PersonalityPrint

from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W, STAT_DIGIT_W
from yasuki_gui.visuals.stats import StatReading, draw_stat_stamps, stamped_stats

CARD = (0, 0, CARD_W, CARD_H)
BOWED = (0, 0, CARD_H, CARD_W)


def personality(card_id="hida", force=3, chi=4):
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        name="Hida",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        force=force,
        chi=chi,
    )


def follower(card_id="banner", force=2):
    return L5RCard.of(
        AttachmentPrint,
        id=card_id,
        name="Banner",
        side=Side.FATE,
        owner=PlayerId.P1,
        attachment_type=AttachmentType.FOLLOWER,
        force=force,
    )


def holding(card_id="mine"):
    return L5RCard.of(HoldingPrint, id=card_id, name="Mine", side=Side.DYNASTY, owner=PlayerId.P1)


@pytest.fixture
def canvas(root):
    return tk.Canvas(root, width=400, height=400)


def _boxes(canvas):
    """Every stamp's tab, in the order they were drawn — Force first, then Chi."""
    return [canvas.coords(i) for i in canvas.find_all() if canvas.type(i) == "rectangle"]


def _text_items(canvas):
    """Every stamp's canvas item, keyed by the number it reads.

    Raises on a repeat, so a test that happens to give both stats the same value fails rather than
    quietly asserting twice about one of them.
    """
    items = {}
    for item in canvas.find_all():
        if canvas.type(item) != "text":
            continue
        text = canvas.itemcget(item, "text")
        assert text not in items, f"two stamps both read {text!r}"
        items[text] = item
    return items


class TestWhichCardsCarryAStat:
    def test_a_personality_reports_force_and_chi(self):
        assert stamped_stats(personality(force=3, chi=4), {}) == {
            Stat.FORCE: StatReading(3, 3),
            Stat.CHI: StatReading(4, 4),
        }

    def test_a_follower_reports_force_but_no_chi(self):
        """It stands in the unit and so has a Force of its own; Chi belongs to the Personality, and
        a Follower's print carries a zero that would otherwise stamp as a real number."""
        assert stamped_stats(follower(force=2), {}) == {Stat.FORCE: StatReading(2, 2)}

    def test_a_holding_reports_neither(self):
        assert stamped_stats(holding(), {}) == {}

    def test_a_modifier_replaces_the_printed_number_and_keeps_it_to_compare(self):
        """The printed number is what says whether the live one is up or down, so it travels with
        it rather than being read off the card a second time at drawing."""
        card = personality(force=3, chi=4)

        assert stamped_stats(card, {"hida": {Stat.FORCE: 7}}) == {
            Stat.FORCE: StatReading(7, 3),
            Stat.CHI: StatReading(4, 4),
        }

    def test_a_card_no_modifier_reaches_keeps_its_print(self):
        """GameView.stats holds only the modified cards, so an absent id is not a zero."""
        readings = stamped_stats(personality(force=3, chi=4), {"someone-else": {Stat.FORCE: 9}})

        assert readings == {Stat.FORCE: StatReading(3, 3), Stat.CHI: StatReading(4, 4)}


class TestDrawing:
    def test_both_stats_are_stamped(self, canvas):
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat",))

        assert set(_text_items(canvas)) == {"3", "4"}

    def test_a_board_with_no_rules_game_stamps_nothing(self, canvas):
        """The manual sandbox has no engine to ask, so it cannot say what a card's stats come to —
        and a card whose counters modify it would be stamped with the numbers it prints, which the
        badge beside them contradicts."""
        card = personality(force=3, chi=4)
        card.adjust_counter("aura", 2)  # +1F/+1C each

        draw_stat_stamps(canvas, card, CARD, None, ("stat",))

        assert not canvas.find_all()

    def test_a_face_down_card_is_stamped_with_nothing(self, canvas):
        """Its numbers are not the viewer's to know, and the back has no print to read them off."""
        card = personality()
        card.turn_face_down()

        draw_stat_stamps(canvas, card, CARD, {}, ("stat",))

        assert not canvas.find_all()

    def test_force_stamps_left_and_chi_right(self, canvas):
        """The card prints them that way round, and the stamp covers the printed numeral rather
        than landing somewhere new."""
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat",))

        items = _text_items(canvas)
        assert canvas.coords(items["3"])[0] < canvas.coords(items["4"])[0]

    def test_both_stamps_sit_in_the_band_the_card_prints_its_stats_in(self, canvas):
        """A stamp drifting to the middle of the card still passes a loose "upper half" bound while
        covering the art instead of the numeral it replaces."""
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat",))

        for box in _boxes(canvas):
            assert box[3] <= CARD_H / 6, f"a stamp reaches {box[3]} down a {CARD_H}px card"

    def test_a_raised_stat_reads_as_raised_and_a_lowered_one_as_lowered(self, canvas):
        draw_stat_stamps(
            canvas,
            personality(force=3, chi=4),
            CARD,
            {"hida": {Stat.FORCE: 7, Stat.CHI: 1}},
            ("stat",),
        )

        items = _text_items(canvas)
        assert canvas.itemcget(items["7"], "fill") == theme.STAT_UP
        assert canvas.itemcget(items["1"], "fill") == theme.STAT_DOWN

    def test_an_untouched_stat_is_set_like_the_numeral_it_covers(self, canvas):
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat",))

        items = _text_items(canvas)
        assert canvas.itemcget(items["3"], "fill") == theme.STAT_PRINTED

    def test_each_stat_takes_the_colour_of_its_own_banner(self, canvas):
        """The card prints Force on a tan scroll and Chi on a slate one. One fill for both would
        read as an overlay stuck on the card rather than as the card's own furniture."""
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat",))

        fills = {
            canvas.itemcget(i, "fill") for i in canvas.find_all() if canvas.type(i) == "rectangle"
        }
        assert fills == {theme.FORCE_BANNER, theme.CHI_BANNER}

    def test_every_stamp_is_the_same_shape_whatever_the_digit(self, canvas):
        """Sized to each glyph's own ink, a 0 and a 6 make different boxes — and a bowed card then
        rotates a shape that was never the same twice."""
        sizes = set()
        for force in range(10):
            canvas.delete("all")
            draw_stat_stamps(canvas, personality(force=force, chi=4), CARD, {}, ("stat",))
            x0, y0, x1, y1 = _boxes(canvas)[0]
            sizes.add((x1 - x0, y1 - y0))
        assert len(sizes) == 1

    def test_a_two_digit_stat_widens_by_exactly_one_column(self, canvas):
        draw_stat_stamps(canvas, personality(force=9), CARD, {}, ("stat",))
        one = _boxes(canvas)[0]
        canvas.delete("all")
        draw_stat_stamps(canvas, personality(force=12), CARD, {}, ("stat",))
        two = _boxes(canvas)[0]

        assert (two[2] - two[0]) - (one[2] - one[0]) == STAT_DIGIT_W
        assert (two[3] - two[1]) == (one[3] - one[1])  # wider only, never taller

    def test_a_wide_stat_stays_on_the_card(self, canvas):
        """Force is stamped a few pixels in from the left edge, so a three-digit number would hang
        off it if nothing pushed back."""
        draw_stat_stamps(canvas, personality(force=100, chi=4), CARD, {}, ("stat",))

        for item in canvas.find_all():
            x0, _, x1, _ = canvas.bbox(item)
            assert x0 >= 0 and x1 <= CARD_W, f"{canvas.type(item)} runs off the card at {x0}-{x1}"

    def test_a_follower_is_stamped_with_its_force_alone(self, canvas):
        """Its print carries a Chi of zero it does not have, which would stamp as a real number."""
        draw_stat_stamps(canvas, follower(force=2), CARD, {}, ("stat",))

        assert set(_text_items(canvas)) == {"2"}

    def test_every_item_carries_the_tags_it_was_given(self, canvas):
        """The sprite erases the stamps by tag before redrawing them. An item drawn without them
        survives the erase, so a Personality granted +2F would keep his old number beside the new
        one."""
        draw_stat_stamps(canvas, personality(force=3, chi=4), CARD, {}, ("stat", "card:hida"))

        assert set(canvas.find_withtag("stat")) == set(canvas.find_all())
        assert set(canvas.find_withtag("card:hida")) == set(canvas.find_all())

    def test_a_number_of_any_length_fits_across_its_own_tab(self, canvas):
        """The tab widens by a constant per digit rather than by measuring, so a digit whose advance
        runs wider than the constant spills a little further over the edge with every digit added.

        Width only: Tk reports a text item's layout box, ascender to descender, where what has to
        fit is the ink — the digits sit well inside a box the linespace overhangs.
        """
        for force in (8, 12, 100):
            canvas.delete("all")
            draw_stat_stamps(canvas, personality(force=force, chi=4), CARD, {}, ("stat",))
            box = _boxes(canvas)[0]
            text = next(i for i in canvas.find_all() if canvas.type(i) == "text")
            left, _, right, _ = canvas.bbox(text)
            assert box[0] <= left and right <= box[2], f"{force} runs wider than its tab"

    def test_a_wide_stat_on_a_bowed_card_stays_on_the_card(self, canvas):
        """Bowing swaps the box's sides, so the clamp that holds a wide number on an upright card
        has to hold it in the other axis here."""
        draw_stat_stamps(canvas, personality(force=100, chi=4), BOWED, {}, ("stat",), bowed=True)

        for item in canvas.find_all():
            x0, y0, x1, y1 = canvas.bbox(item)
            assert 0 <= x0 and x1 <= CARD_H, f"{canvas.type(item)} runs off the long edge"
            assert 0 <= y0 and y1 <= CARD_W, f"{canvas.type(item)} runs off the short edge"

    def test_bowing_turns_both_stamps_onto_the_cards_side(self, canvas):
        """The card is drawn a quarter turn over, and its printed numerals go with it — a stamp
        left at the upright fractions lands in two corners the printing never used."""
        draw_stat_stamps(canvas, personality(force=3, chi=4), BOWED, {}, ("stat",), bowed=True)

        items = _text_items(canvas)
        bowed_width = CARD_H  # the card is on its side, so its long edge is its width
        force, chi = canvas.coords(items["3"]), canvas.coords(items["4"])
        assert force[0] > bowed_width * 2 / 3 and chi[0] > bowed_width * 2 / 3  # down the right
        assert force[1] < chi[1]  # Force above Chi, as the turn puts them

    def test_bowing_turns_the_numbers_themselves(self, canvas):
        draw_stat_stamps(canvas, personality(force=3, chi=4), BOWED, {}, ("stat",), bowed=True)

        for item in _text_items(canvas).values():
            assert float(canvas.itemcget(item, "angle")) == 270

    def test_bowing_turns_the_box_with_the_number(self, canvas):
        """A box that keeps its upright width on a turned card is the one thing that reads as a
        mistake rather than as a card lying on its side.

        Two digits, because a single-digit box is square and a square hides the swap.
        """
        draw_stat_stamps(canvas, personality(force=12), CARD, {}, ("stat",))
        upright = _boxes(canvas)[0]
        canvas.delete("all")
        draw_stat_stamps(canvas, personality(force=12), BOWED, {}, ("stat",), bowed=True)
        bowed = _boxes(canvas)[0]

        assert (bowed[2] - bowed[0], bowed[3] - bowed[1]) == (
            upright[3] - upright[1],
            upright[2] - upright[0],
        )
