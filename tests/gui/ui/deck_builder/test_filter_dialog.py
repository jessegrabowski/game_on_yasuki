from app.gui.ui.deck_builder.filter_dialog import FilterOptions, FilterDialog
import tkinter as tk


def test_filter_options_default():
    """Test FilterOptions dataclass with defaults."""
    opts = FilterOptions()
    assert not opts.has_filters()
    assert opts.filters == {}


def test_filter_options_add_filter():
    """Test adding a filter to FilterOptions."""
    opts = FilterOptions()
    opts.add_filter("legality", ("Ivory Edition", ["legal"]))
    assert opts.has_filters()
    assert opts.get_filter("legality") == ("Ivory Edition", ["legal"])


def test_filter_options_multiple_filters():
    """Test FilterOptions with multiple filters."""
    opts = FilterOptions()
    opts.add_filter("legality", ("Emperor Edition", ["legal"]))
    opts.add_filter("type", "personality")
    opts.add_filter("clan", "Crane")

    assert opts.has_filters()
    assert opts.get_filter("legality") == ("Emperor Edition", ["legal"])
    assert opts.get_filter("type") == "personality"
    assert opts.get_filter("clan") == "Crane"


def test_filter_options_remove_filter():
    """Test removing a filter from FilterOptions."""
    opts = FilterOptions()
    opts.add_filter("legality", ("Ivory Edition", ["legal"]))
    opts.add_filter("type", "personality")

    opts.remove_filter("type")
    assert opts.get_filter("type") is None
    assert opts.get_filter("legality") == ("Ivory Edition", ["legal"])
    assert opts.has_filters()


def test_filter_options_clear():
    """Test clearing all filters from FilterOptions."""
    opts = FilterOptions()
    opts.add_filter("legality", ("Ivory Edition", ["legal"]))
    opts.add_filter("type", "personality")
    opts.add_filter("clan", "Lion")

    opts.clear()
    assert not opts.has_filters()
    assert opts.filters == {}


def test_filter_dialog_with_existing_options():
    """Test that FilterDialog can be created with existing filter options without errors."""
    root = tk.Tk()
    try:
        # Create filter options with legality filter (simulates reopening dialog)
        existing_opts = FilterOptions()
        existing_opts.add_filter("legality", ("Modern", ["legal"]))

        # This should not raise AttributeError about legal_var
        dialog = FilterDialog(root, current_options=existing_opts)

        # Verify dialog was created successfully
        assert dialog.win is not None
        assert dialog.current_options == existing_opts

        # Clean up
        dialog.win.destroy()
    finally:
        root.destroy()


def test_filter_dialog_format_grouping():
    """Test that formats are properly grouped into Arc, Formats, and Misc categories."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        assert hasattr(dialog, "arc_frame")
        assert hasattr(dialog, "formats_frame")
        assert hasattr(dialog, "misc_frame")
        assert hasattr(dialog, "arc_listbox")
        assert hasattr(dialog, "formats_listbox")
        assert hasattr(dialog, "misc_listbox")

        arc_items = dialog.arc_listbox.get(0, tk.END)
        arc_formats_present = any(
            "Clan Wars" in fmt or "Hidden Emperor" in fmt for fmt in arc_items
        )
        assert arc_formats_present, "Arc formats should be present"

        format_items = dialog.formats_listbox.get(0, tk.END)
        assert "Modern" in format_items or "Legacy" in format_items

        misc_items = dialog.misc_listbox.get(0, tk.END)
        misc_present = any("Not Legal" in fmt or "Unreleased" in fmt for fmt in misc_items)
        assert misc_present, "Misc formats should be present"

        assert hasattr(dialog, "all_listboxes")
        assert len(dialog.all_listboxes) == 3

        dialog.win.destroy()
    finally:
        root.destroy()


def test_filter_dialog_set_filter():
    """Test that set filter column exists and works."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        assert hasattr(dialog, "set_listbox")
        assert dialog.set_listbox.cget("selectmode") == "extended"

        set_items = dialog.set_listbox.get(0, tk.END)
        assert len(set_items) > 0, "Should have loaded sets from database"

        dialog.win.destroy()
    finally:
        root.destroy()


def test_filter_options_with_sets():
    """Test that FilterOptions can store set filters."""
    opts = FilterOptions()
    opts.add_filter("sets", ["Set A", "Set B", "Set C"])

    assert opts.has_filters()
    assert opts.get_filter("sets") == ["Set A", "Set B", "Set C"]

    opts.remove_filter("sets")
    assert not opts.has_filters()


def test_format_deselection():
    """Test that clicking on selected format deselects it in all format listboxes."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        dialog.arc_listbox.selection_set(0)
        assert len(dialog.arc_listbox.curselection()) == 1

        event = type("Event", (), {"y": 0})()
        dialog._on_format_listbox_click(event, dialog.arc_listbox)

        assert len(dialog.arc_listbox.curselection()) == 0, "Arc listbox should deselect"

        dialog.formats_listbox.selection_set(0)
        assert len(dialog.formats_listbox.curselection()) == 1

        event2 = type("Event", (), {"y": 0})()
        dialog._on_format_listbox_click(event2, dialog.formats_listbox)

        assert len(dialog.formats_listbox.curselection()) == 0, "Formats listbox should deselect"

        dialog.misc_listbox.selection_set(0)
        assert len(dialog.misc_listbox.curselection()) == 1

        event3 = type("Event", (), {"y": 0})()
        dialog._on_format_listbox_click(event3, dialog.misc_listbox)

        assert len(dialog.misc_listbox.curselection()) == 0, "Misc listbox should deselect"

        dialog.win.destroy()
    finally:
        root.destroy()


def test_set_listbox_spreadsheet_selection():
    """Test spreadsheet-style selection in set listbox."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        event = type("Event", (), {"y": 0})()
        dialog._on_generic_listbox_click(event, dialog.set_listbox, "set")

        assert len(dialog.set_listbox.curselection()) == 1
        assert hasattr(dialog, "last_set_click_index")
        assert dialog.last_set_click_index == 0

        dialog.win.destroy()
    finally:
        root.destroy()


def test_arrow_key_navigation_in_arc_listbox():
    """Test that arrow keys work in arc listbox and update sets dynamically."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        arc_count = dialog.arc_listbox.size()
        assert arc_count >= 2, "Need at least 2 arc formats for this test"

        dialog.arc_listbox.selection_set(0)
        dialog.arc_listbox.activate(0)
        assert dialog.arc_listbox.curselection() == (0,)

        first_arc = dialog.arc_listbox.get(0)

        dialog._update_sets_for_selected_format()

        down_event = type("Event", (), {"keysym": "Down"})()

        result = dialog._on_format_arrow_key(down_event, dialog.arc_listbox)

        assert result == "break", "Arrow key handler should return 'break'"

        assert dialog.arc_listbox.curselection() == (1,), (
            f"Selection should be at index 1, but is {dialog.arc_listbox.curselection()}"
        )

        second_arc = dialog.arc_listbox.get(1)
        assert first_arc != second_arc, "First and second arc should be different"

        new_set_count = dialog.set_listbox.size()
        assert new_set_count > 0, "Should have some sets loaded"

        up_event = type("Event", (), {"keysym": "Up"})()
        result = dialog._on_format_arrow_key(up_event, dialog.arc_listbox)

        assert dialog.arc_listbox.curselection() == (0,), (
            f"Selection should be back at index 0, but is {dialog.arc_listbox.curselection()}"
        )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_shift_arrow_key_multi_select():
    """Test that Shift+arrow keys expand selection in multi-select listboxes."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        assert dialog.set_listbox.size() >= 3, "Need at least 3 sets for this test"

        dialog.set_listbox.selection_set(0)
        dialog.set_listbox.activate(0)
        dialog.set_listbox.focus_set()
        assert dialog.set_listbox.curselection() == (0,)

        shift_down_event = type("Event", (), {"keysym": "Down", "state": 0x0001})()

        result = dialog._on_arrow_key(shift_down_event, dialog.set_listbox)
        assert result == "break"

        assert dialog.set_listbox.curselection() == (0, 1), (
            f"Expected (0, 1), got {dialog.set_listbox.curselection()}"
        )

        result = dialog._on_arrow_key(shift_down_event, dialog.set_listbox)

        assert dialog.set_listbox.curselection() == (0, 1, 2), (
            f"Expected (0, 1, 2), got {dialog.set_listbox.curselection()}"
        )

        shift_up_event = type("Event", (), {"keysym": "Up", "state": 0x0001})()
        result = dialog._on_arrow_key(shift_up_event, dialog.set_listbox)

        selection = dialog.set_listbox.curselection()
        assert len(selection) >= 2, "Should have at least 2 items selected after Shift+Up"

        plain_down_event = type("Event", (), {"keysym": "Down", "state": 0})()
        result = dialog._on_arrow_key(plain_down_event, dialog.set_listbox)

        assert len(dialog.set_listbox.curselection()) == 1, (
            "Plain arrow should select only one item"
        )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_statistics_spinbox_filters_exist():
    """Test that all statistics filters are created."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        expected_stats = [
            "force",
            "chi",
            "honor_requirement",
            "gold_cost",
            "personal_honor",
            "province_strength",
            "gold_production",
            "starting_honor",
            "focus",
        ]

        for stat in expected_stats:
            assert stat in dialog.stat_filters

        dialog.win.destroy()
    finally:
        root.destroy()


def test_statistics_filter_value_combinations():
    """Test statistics filters with various min/max combinations."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        test_cases = [
            ("force", "5", "", (5, None)),
            ("gold_cost", "", "3", (None, 3)),
            ("chi", "2", "8", (2, 8)),
            ("personal_honor", "", "", None),
        ]

        for stat_name, min_val, max_val, expected in test_cases:
            dialog.stat_filters[stat_name]["min_var"].set(min_val)
            dialog.stat_filters[stat_name]["max_var"].set(max_val)

        dialog._apply()

        assert dialog.result is not None
        for stat_name, _, _, expected in test_cases:
            assert dialog.result.get_filter(stat_name) == expected

    finally:
        root.destroy()


def test_statistics_clear_filters():
    """Test that clear filters resets all statistics spinboxes to default ranges."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        dialog.stat_filters["force"]["min_var"].set("5")
        dialog.stat_filters["chi"]["max_var"].set("3")

        dialog._clear_filters()

        for stat_name, stat_data in dialog.stat_filters.items():
            range_min, range_max = stat_data["range"]
            assert stat_data["min_var"].get() == str(range_min), (
                f"{stat_name} min should be reset to {range_min}"
            )
            assert stat_data["max_var"].get() == str(range_max), (
                f"{stat_name} max should be reset to {range_max}"
            )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_clear_filters_batches_updates():
    """Test that clear filters batches updates to avoid multiple database queries."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)
        update_count = 0
        original_update = dialog._update_card_count

        def counted_update():
            nonlocal update_count
            update_count += 1
            original_update()

        dialog._update_card_count = counted_update

        dialog.stat_filters["force"]["min_var"].set("5")
        dialog.stat_filters["chi"]["max_var"].set("3")
        update_count = 0

        dialog._clear_filters()

        assert update_count == 1, (
            f"Clear filters should update card count once, not {update_count} times"
        )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_card_count_displays_correctly():
    """Test that card count label displays number, not ???"""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        dialog._update_card_count()

        count_text = dialog.card_count_label.cget("text")

        assert "???" not in count_text
        assert "cards" in count_text.lower()

        dialog.win.destroy()
    finally:
        root.destroy()


def test_statistics_partial_range_applies_filter():
    """Test that changing only min or max still applies the filter."""
    from app.database import query_stat_ranges

    root = tk.Tk()
    try:
        dialog = FilterDialog(root)
        db_ranges = query_stat_ranges()
        force_min, force_max = db_ranges["force"]

        dialog.stat_filters["force"]["min_var"].set("3")
        dialog._apply()

        assert dialog.result is not None
        assert "force" in dialog.result.filters, "Filter should be applied when min changes"
        assert dialog.result.filters["force"] == (3, force_max)

        dialog.win.destroy()

        dialog2 = FilterDialog(root)
        dialog2.stat_filters["force"]["max_var"].set("15")
        dialog2._apply()

        assert dialog2.result is not None
        assert "force" in dialog2.result.filters, "Filter should be applied when max changes"
        assert dialog2.result.filters["force"] == (force_min, 15)

        dialog2.win.destroy()

        dialog3 = FilterDialog(root)
        dialog3._apply()

        assert dialog3.result is not None
        assert "force" not in dialog3.result.filters, (
            "Filter should NOT be applied when both min and max are at defaults"
        )

        dialog3.win.destroy()

    finally:
        root.destroy()


def test_statistics_with_other_filters():
    """Test statistics filters combined with other filter types."""
    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        dialog.arc_listbox.selection_set(0)
        dialog.deck_listbox.selection_set(0)
        dialog.stat_filters["force"]["min_var"].set("5")
        dialog.stat_filters["force"]["max_var"].set("")
        dialog.stat_filters["gold_cost"]["min_var"].set("")
        dialog.stat_filters["gold_cost"]["max_var"].set("3")

        dialog._apply()

        assert dialog.result.get_filter("legality") is not None
        assert dialog.result.get_filter("decks") is not None
        assert dialog.result.get_filter("force") == (5, None)
        assert dialog.result.get_filter("gold_cost") == (None, 3)

    finally:
        root.destroy()


def test_statistics_filter_options_storage():
    """Test FilterOptions stores statistics tuples correctly."""
    opts = FilterOptions()

    opts.add_filter("force", (5, 10))
    opts.add_filter("chi", (None, 8))
    opts.add_filter("gold_cost", (2, None))

    assert opts.get_filter("force") == (5, 10)
    assert opts.get_filter("chi") == (None, 8)
    assert opts.get_filter("gold_cost") == (2, None)

    opts.remove_filter("chi")
    assert opts.get_filter("chi") is None
    assert opts.get_filter("force") == (5, 10)


def test_statistics_ranges_from_database():
    """Test that statistics ranges are fetched from database, not hard-coded."""
    from app.database import query_stat_ranges

    root = tk.Tk()
    try:
        dialog = FilterDialog(root)

        db_ranges = query_stat_ranges()
        stats_config = dialog._get_stats_config()

        for display_name, db_name, min_val, max_val in stats_config:
            assert db_name in db_ranges, f"{db_name} should be in database ranges"
            expected_min, expected_max = db_ranges[db_name]
            assert min_val == expected_min, (
                f"{display_name} min should match database: expected {expected_min}, got {min_val}"
            )
            assert max_val == expected_max, (
                f"{display_name} max should match database: expected {expected_max}, got {max_val}"
            )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_filter_state_restoration():
    """Test that all filter states are properly restored when reopening the dialog."""
    root = tk.Tk()
    try:
        existing_opts = FilterOptions()
        existing_opts.add_filter("legality", ("Modern", ["legal"]))
        existing_opts.add_filter("sets", ["Imperial Edition", "Jade Edition"])
        existing_opts.add_filter("decks", ["FATE", "DYNASTY"])
        existing_opts.add_filter("types", ["Personality", "Holding"])
        existing_opts.add_filter("clans", ["Crab", "Crane"])
        existing_opts.add_filter("rarities", ["Rare", "Uncommon"])
        existing_opts.add_filter("force", (2, 5))
        existing_opts.add_filter("chi", (1, 3))

        dialog = FilterDialog(root, current_options=existing_opts)

        legality_filter = dialog.current_options.get_filter("legality")
        assert legality_filter == ("Modern", ["legal"])
        assert dialog.legal_var.get()
        assert not dialog.not_legal_var.get()

        deck_filter = dialog.current_options.get_filter("decks")
        assert "FATE" in deck_filter
        assert "DYNASTY" in deck_filter

        type_filter = dialog.current_options.get_filter("types")
        assert "Personality" in type_filter
        assert "Holding" in type_filter

        clan_filter = dialog.current_options.get_filter("clans")
        assert "Crab" in clan_filter
        assert "Crane" in clan_filter

        rarity_filter = dialog.current_options.get_filter("rarities")
        assert "Rare" in rarity_filter
        assert "Uncommon" in rarity_filter

        force_filter = dialog.current_options.get_filter("force")
        assert force_filter == (2, 5)
        assert dialog.stat_filters["force"]["min_var"].get() == "2"
        assert dialog.stat_filters["force"]["max_var"].get() == "5"

        chi_filter = dialog.current_options.get_filter("chi")
        assert chi_filter == (1, 3)
        assert dialog.stat_filters["chi"]["min_var"].get() == "1"
        assert dialog.stat_filters["chi"]["max_var"].get() == "3"

        force_spinbox = dialog.stat_filters["force"]["min_spinbox"]
        assert str(force_spinbox.cget("state")) == "normal", (
            "Force should be enabled for Personality"
        )

        chi_spinbox = dialog.stat_filters["chi"]["min_spinbox"]
        assert str(chi_spinbox.cget("state")) == "normal", (
            "Chi should be enabled for selected types"
        )

        dialog.win.destroy()
    finally:
        root.destroy()


def test_stat_availability_restoration():
    """Test that stat filter enabled/disabled states are properly restored."""
    root = tk.Tk()
    try:
        opts_all_stats = FilterOptions()
        dialog1 = FilterDialog(root, current_options=opts_all_stats)

        for stat_name, stat_data in dialog1.stat_filters.items():
            spinbox_state = str(stat_data["min_spinbox"].cget("state"))
            assert spinbox_state == "normal", f"{stat_name} should be enabled with no filters"

        dialog1.win.destroy()

        # Create options with a specific type that doesn't have all stats
        # For example, selecting only "Event" type which has limited stats
        opts_limited = FilterOptions()
        opts_limited.add_filter("types", ["Event"])

        dialog2 = FilterDialog(root, current_options=opts_limited)

        # Check that stat availability is determined by the restored type selection
        # Events typically don't have force, chi, etc., so those should be disabled
        available_stats = dialog2._get_available_stats_for_selection()

        for stat_name, stat_data in dialog2.stat_filters.items():
            spinbox_state = str(stat_data["min_spinbox"].cget("state"))
            frame_fg = str(stat_data["frame"].cget("fg"))

            if stat_name in available_stats:
                assert spinbox_state == "normal", f"{stat_name} should be enabled for Event type"
                assert frame_fg == "black", f"{stat_name} frame should not be grayed out"
            else:
                assert spinbox_state == "disabled", f"{stat_name} should be disabled for Event type"
                assert frame_fg == "gray", f"{stat_name} frame should be grayed out"

        dialog2.win.destroy()

        opts_deck = FilterOptions()
        opts_deck.add_filter("decks", ["FATE"])

        dialog3 = FilterDialog(root, current_options=opts_deck)

        available_stats_fate = dialog3._get_available_stats_for_selection()

        # Gold cost and focus should be available for Fate cards
        assert "gold_cost" in available_stats_fate, "Gold cost should be available for Fate deck"
        assert "focus" in available_stats_fate, "Focus should be available for Fate deck"

        gold_cost_state = str(dialog3.stat_filters["gold_cost"]["min_spinbox"].cget("state"))
        assert gold_cost_state == "normal", "Gold cost spinbox should be enabled"

        dialog3.win.destroy()

    finally:
        root.destroy()
