import difflib
import re

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\S+|\s+")


def _normalize(text: str) -> str:
    """Card markup to readable plain text: ``<br>`` becomes a newline, other inline tags (``<b>``,
    ``<i>``) are dropped, so the diff runs over words rather than markup."""
    return _TAG_RE.sub("", _BR_RE.sub("\n", text))


def _word_segments(old_line: str, new_line: str) -> tuple[list[dict], list[dict]]:
    """Split a changed line pair into inline segments that mark just the words that differ.

    Returns ``(removed, added)`` lists of ``{"kind", "text"}`` — ``kind`` is ``"eq"`` for shared
    words and ``"chg"`` for the words unique to that side.
    """
    a = _TOKEN_RE.findall(old_line)
    b = _TOKEN_RE.findall(new_line)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    removed: list[dict] = []
    added: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        a_text, b_text = "".join(a[i1:i2]), "".join(b[j1:j2])
        kind = "eq" if op == "equal" else "chg"
        if a_text:
            removed.append({"kind": kind, "text": a_text})
        if b_text:
            added.append({"kind": kind, "text": b_text})
    return removed, added


def unified_diff(old: str, new: str) -> list[dict]:
    """A GitHub-style unified line diff from ``old`` to ``new``.

    Parameters
    ----------
    old : str
        The earlier revision's rules text (the base).
    new : str
        The later revision's rules text (the incoming errata).

    Returns
    -------
    rows : list of dict
        Rows for a single-column diff view, top to bottom. Each row is ``{"type", "segments"}`` where
        ``type`` is ``"context"`` (unchanged line), ``"del"`` (only in ``old``), or ``"ins"`` (only in
        ``new``); ``segments`` carry the line text as ``{"kind", "text"}`` pieces so a replaced line
        highlights just the words that changed. A replace is emitted as its ``del`` rows followed by
        its ``ins`` rows, lines paired for word-level refinement.
    """
    old_lines = _normalize(old).split("\n")
    new_lines = _normalize(new).split("\n")
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    rows: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            rows += [
                {"type": "context", "segments": [{"kind": "eq", "text": ln}]}
                for ln in old_lines[i1:i2]
            ]
        elif op == "delete":
            rows += [
                {"type": "del", "segments": [{"kind": "eq", "text": ln}]} for ln in old_lines[i1:i2]
            ]
        elif op == "insert":
            rows += [
                {"type": "ins", "segments": [{"kind": "eq", "text": ln}]} for ln in new_lines[j1:j2]
            ]
        else:
            olds, news = old_lines[i1:i2], new_lines[j1:j2]
            for k in range(max(len(olds), len(news))):
                o = olds[k] if k < len(olds) else None
                n = news[k] if k < len(news) else None
                if o is not None and n is not None:
                    removed, added = _word_segments(o, n)
                    rows.append({"type": "del", "segments": removed})
                    rows.append({"type": "ins", "segments": added})
                elif o is not None:
                    rows.append({"type": "del", "segments": [{"kind": "chg", "text": o}]})
                else:
                    rows.append({"type": "ins", "segments": [{"kind": "chg", "text": n}]})
    return rows
