from __future__ import annotations
import sys
import re
import html
import xml.etree.ElementTree as ET
from collections.abc import Iterable


# --- Helpers ---------------------------------------------------------------
def sql_value(v):
    """Render Python values for Postgres, with correct booleans."""
    if v is None:
        return "NULL"
    # bool BEFORE int: bool is a subclass of int in Python
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return f"'{q(str(v))}'"


def norm_text(t: str | None) -> str:
    if not t:
        return ""
    # Unescape HTML entities and strip simple HTML-like tags
    s = html.unescape(t)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?b>", "", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)  # drop remaining tags
    return s.strip()


BOLD_BLOCK = re.compile(r"<(?:b|B)>(.*?)</(?:b|B)>", re.S)
SENTENCE_SPLIT = re.compile(r"\s*[.;]\s*")


def extract_keywords_traits(text_html: str) -> tuple[list[str], list[str]]:
    """
    Heuristic: many AEG XML entries list keywords/traits in an initial <B>...</B> block,
    separated by periods. We return (keywords, traits). For now we treat all as traits.
    """
    if not text_html:
        return [], []
    m = BOLD_BLOCK.search(text_html)
    if not m:
        return [], []
    raw = m.group(1)
    pieces = [p.strip() for p in SENTENCE_SPLIT.split(raw) if p.strip()]
    # Store everything as traits initially; you can curate later if you want a keywords/traits split.
    return [], pieces


SIDE_MAP = {
    "strategy": "FATE",
    "item": "FATE",
    "follower": "FATE",
    "spell": "FATE",
    "ring": "FATE",
    "region": "DYNASTY",
    "holding": "DYNASTY",
    "personality": "DYNASTY",
    "event": "DYNASTY",
    "celestial": "DYNASTY",
}


# --- SQL builders ---------------------------------------------------------


def q(s: str) -> str:
    return s.replace("'", "''")


def upsert_cards(card: dict) -> str:
    cols = [
        ("id", card.get("id")),
        ("name", card.get("name")),
        ("side", card.get("side")),
        ("clan", card.get("clan")),
        ("text", card.get("text")),
        ("rarity", card.get("rarity")),
        ("honor_req", card.get("honor_req")),
        ("arc", card.get("arc")),
        ("legal", card.get("legal", True)),
    ]
    cols_names = ", ".join(k for k, _ in cols)
    vals = ", ".join(sql_value(v) for _, v in cols)
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k, _ in cols if k != "id")
    return f"INSERT INTO cards ({cols_names}) VALUES ({vals}) ON CONFLICT (id) DO UPDATE SET {updates};"


def upsert_fate(card_id: str, focus: int | None, gold_cost: int | None) -> str:
    return (
        "INSERT INTO fate_cards (id, focus, gold_cost) VALUES "
        f"({sql_value(card_id)}, {sql_value(focus)}, {sql_value(gold_cost)}) "
        "ON CONFLICT (id) DO UPDATE SET focus=EXCLUDED.focus, gold_cost=EXCLUDED.gold_cost;"
    )


def upsert_dynasty(card_id: str, d: dict) -> str:
    cols = [
        ("id", card_id),
        ("gold_cost", d.get("cost")),
        ("force", d.get("force")),
        ("chi", d.get("chi")),
        ("personal_honor", d.get("personal_honor")),
        ("gold_production", d.get("gold_production")),
    ]
    names = ", ".join(k for k, _ in cols)
    vals = ", ".join(sql_value(v) for _, v in cols)
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k, _ in cols if k != "id")
    return f"INSERT INTO dynasty_cards ({names}) VALUES ({vals}) ON CONFLICT (id) DO UPDATE SET {updates};"


def upsert_keyword(kw: str) -> str:
    return f"INSERT INTO keywords (keyword) VALUES ('{q(kw)}') ON CONFLICT DO NOTHING;"


def link_keyword(card_id: str, kw: str) -> str:
    return f"INSERT INTO card_keywords (card_id, keyword) VALUES ('{q(card_id)}', '{q(kw)}') ON CONFLICT DO NOTHING;"


def upsert_trait(tr: str) -> str:
    return f"INSERT INTO traits (trait) VALUES ('{q(tr)}') ON CONFLICT DO NOTHING;"


def link_trait(card_id: str, tr: str) -> str:
    return f"INSERT INTO card_traits (card_id, trait) VALUES ('{q(card_id)}', '{q(tr)}') ON CONFLICT DO NOTHING;"


def link_legality(card_id: str, legality: str) -> str:
    return f"INSERT INTO card_legalities (card_id, legality) VALUES ('{q(card_id)}', '{q(legality)}') ON CONFLICT DO NOTHING;"


def link_edition(card_id: str, edition: str) -> str:
    return f"INSERT INTO card_editions (card_id, edition) VALUES ('{q(card_id)}', '{q(edition)}') ON CONFLICT DO NOTHING;"


def upsert_image(card_id: str, edition: str, path: str) -> str:
    return (
        "INSERT INTO card_images (card_id, edition, path) VALUES "
        f"('{q(card_id)}', '{q(edition)}', '{q(path)}') "
        "ON CONFLICT (card_id, edition) DO UPDATE SET path=EXCLUDED.path;"
    )


# --- XML parsing ----------------------------------------------------------


def parse_int(val: str | None) -> int | None:
    if val is None:
        return None
    val = val.strip()
    if val == "" or val == "*":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def emit_sql_from_xml(xml_path: str) -> Iterable[str]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    for card in root.findall("card"):
        cid = card.attrib.get("id", "").strip()
        ctype = (card.attrib.get("type", "").strip() or "").lower()
        name = (card.findtext("name") or "").strip()
        rarity = (card.findtext("rarity") or "").strip()
        clan = (card.findtext("clan") or "").strip() or None
        text_raw = (
            ET.tostring(card.find("text")).decode("utf-8") if card.find("text") is not None else ""
        )
        text_html = re.sub(r"^<text[^>]*>|</text>$", "", text_raw, flags=re.S)
        text_clean = norm_text(text_html)

        side = SIDE_MAP.get(ctype) or "FATE"

        honor_req = parse_int(card.findtext("honor_req"))
        cost = parse_int(card.findtext("cost"))
        focus = parse_int(card.findtext("focus"))
        force = parse_int(card.findtext("force"))
        chi = parse_int(card.findtext("chi"))
        personal_honor = parse_int(card.findtext("personal_honor"))
        gold_production = parse_int(card.findtext("gold_production"))

        kws, traits = extract_keywords_traits(text_html)

        # Base card
        base = {
            "id": cid,
            "name": name,
            "side": side,
            "clan": clan,
            "text": text_clean,
            "rarity": rarity or None,
            "honor_req": honor_req,
            "arc": None,
            "legal": True,
        }
        yield upsert_cards(base)

        # Subtype tables
        if side == "FATE":
            yield upsert_fate(cid, focus=focus, gold_cost=cost)
        else:
            d = {
                "cost": cost,
                "force": force,
                "chi": chi,
                "personal_honor": personal_honor,
                "gold_production": gold_production,
            }
            yield upsert_dynasty(cid, d)

        # Legalities
        for leg in card.findall("legal"):
            v = (leg.text or "").strip()
            if v:
                yield link_legality(cid, v)

        # Editions and images
        for ed in card.findall("edition"):
            v = (ed.text or "").strip()
            if v:
                yield link_edition(cid, v)
        for img in card.findall("image"):
            ed = img.attrib.get("edition", "").strip()
            path = (img.text or "").strip()
            if ed and path:
                yield upsert_image(cid, ed, path)

        # Keywords/traits
        for tr in traits:
            yield upsert_trait(tr)
            yield link_trait(cid, tr)
        for kw in kws:
            yield upsert_keyword(kw)
            yield link_keyword(cid, kw)


# --- CLI ------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.tools.xml_to_sql path/to/cards.xml", file=sys.stderr)
        return 2
    xml_path = argv[1]
    for stmt in emit_sql_from_xml(xml_path):
        print(stmt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
