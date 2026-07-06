from yasuki_core.card_diff import unified_diff


def _text(row):
    return "".join(s["text"] for s in row["segments"])


def test_identical_text_is_all_context():
    rows = unified_diff("<b>Open:</b> Dishonor a target.", "<b>Open:</b> Dishonor a target.")
    assert [r["type"] for r in rows] == ["context"]
    assert all(s["kind"] == "eq" for r in rows for s in r["segments"])


def test_unchanged_line_is_context_changed_line_is_del_then_ins():
    old = "Gain 1 Honor.<br>bow your target Personality"
    new = "Gain 1 Honor.<br>target your unbowed Personality"
    rows = unified_diff(old, new)
    assert [r["type"] for r in rows] == ["context", "del", "ins"]
    assert _text(rows[0]) == "Gain 1 Honor."
    assert _text(rows[1]) == "bow your target Personality"
    assert _text(rows[2]) == "target your unbowed Personality"


def test_replace_highlights_only_the_changed_words():
    rows = unified_diff("lose 3 Honor", "lose 5 Honor")
    del_row = next(r for r in rows if r["type"] == "del")
    ins_row = next(r for r in rows if r["type"] == "ins")
    # 'lose ' and ' Honor' are shared; only the number is flagged as changed.
    assert [(s["kind"], s["text"]) for s in del_row["segments"] if s["kind"] == "chg"] == [
        ("chg", "3")
    ]
    assert [(s["kind"], s["text"]) for s in ins_row["segments"] if s["kind"] == "chg"] == [
        ("chg", "5")
    ]
    assert any(s["kind"] == "eq" and "lose" in s["text"] for s in del_row["segments"])


def test_pure_insert_and_delete_lines():
    assert [r["type"] for r in unified_diff("a", "a<br>b")] == ["context", "ins"]
    assert [r["type"] for r in unified_diff("a<br>b", "a")] == ["context", "del"]


def test_replace_with_unequal_line_counts_marks_the_leftover_line():
    # Two old clauses collapse into one: the paired lines get word-level marks, and the unpaired old
    # line is emitted whole.
    rows = unified_diff("First clause.<br>Second clause.", "One merged clause.")
    assert [r["type"] for r in rows] == ["del", "ins", "del"]
    assert _text(rows[2]) == "Second clause."
    assert all(s["kind"] == "chg" for s in rows[2]["segments"])


def test_formatting_only_change_is_not_a_diff():
    # Bold vs italic on the same words normalizes away, so restyling never reads as an errata.
    rows = unified_diff("<b>Open:</b> foo bar", "<i>Open:</i> foo bar")
    assert [r["type"] for r in rows] == ["context"]
