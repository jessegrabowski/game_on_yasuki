from dataclasses import dataclass, field, replace
from pathlib import Path

from yasuki_core.card_art import classify
from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side, AttachmentType
from yasuki_core.game_pieces.dynasty import (
    DynastyCard,
    DynastyPersonality,
    DynastyHolding,
    DynastyEvent,
    DynastyRegion,
    DynastyCelestial,
)
from yasuki_core.game_pieces.fate import (
    FateCard,
    FateAction,
    FateAttachment,
    FateRing,
    FateAncestor,
)
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard

_DYNASTY_BY_TYPE = {
    "Personality": DynastyPersonality,
    "Holding": DynastyHolding,
    "Event": DynastyEvent,
    "Region": DynastyRegion,
    "Celestial": DynastyCelestial,
}
_FATE_BY_TYPE = {
    "Strategy": FateAction,
    "Ring": FateRing,
    "Ancestor": FateAncestor,
    "Item": FateAttachment,
    "Follower": FateAttachment,
    "Spell": FateAttachment,
}
_PREGAME_BY_TYPE = {
    "Stronghold": (StrongholdCard, Side.STRONGHOLD),
    "Sensei": (SenseiCard, Side.FATE),
    "Wind": (WindCard, Side.FATE),
}


@dataclass(slots=True)
class ResolvedDeck:
    """A decklist resolved to live card instances for one seat, plus the names that did not resolve."""

    pre_game: list[L5RCard] = field(default_factory=list)
    dynasty: list[DynastyCard] = field(default_factory=list)
    fate: list[FateCard] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def resolve_decklist(parsed: dict, records: list[dict], owner: PlayerId) -> ResolvedDeck:
    """Resolve a parsed decklist into typed card instances owned by ``owner``.

    Each entry's section (not the record's deck field) decides the card family, so a player's manual
    placement is honored; the record's first type refines the subclass. One instance is built per
    physical copy, with a card id unique across both seats.

    Parameters
    ----------
    parsed : dict
        A decklist parsed by ``parse_deck_yaml`` — the section lists ``pre_game``, ``dynasty``, and
        ``fate``, each of ``{name, count, set_name, art}`` entries.
    records : list of dict
        Card records as returned by ``database.get_cards_by_names``, each with a ``prints`` list.
    owner : PlayerId
        The seat the resolved cards belong to.

    Returns
    -------
    resolved : ResolvedDeck
        The per-section card instances plus any entry names absent from ``records``.
    """
    index = _name_index(records)
    by_id = {record["card_id"]: record for record in records}
    resolved = ResolvedDeck()
    sections = {"pre_game": resolved.pre_game, "dynasty": resolved.dynasty, "fate": resolved.fate}
    next_id = 0
    for section, target in sections.items():
        for entry in parsed.get(section, []):
            record = index.get(entry["name"].lower())
            if record is None:
                resolved.unresolved.append(entry["name"])
                continue
            for _ in range(entry["count"]):
                target.append(
                    _build_card(
                        record,
                        entry.get("set_name"),
                        section,
                        by_id,
                        owner=owner,
                        card_id=f"{owner.name}-{next_id}",
                        art=entry.get("art"),
                        name_index=index,
                    )
                )
                next_id += 1
    return resolved


def _name_index(records: list[dict]) -> dict[str, dict]:
    """Case-insensitive name → record index, keyed by extended title first, then plain name."""
    index: dict[str, dict] = {}
    for record in records:
        index.setdefault((record.get("extended_title") or record["name"]).lower(), record)
    for record in records:
        index.setdefault(record["name"].lower(), record)
    return index


def _classify(section: str, card_type: str | None) -> tuple[type, Side]:
    if section == "dynasty":
        return _DYNASTY_BY_TYPE.get(card_type, DynastyCard), Side.DYNASTY
    if section == "fate":
        return _FATE_BY_TYPE.get(card_type, FateCard), Side.FATE
    return _PREGAME_BY_TYPE.get(card_type, (L5RCard, Side.STRONGHOLD))


def _select_print(record: dict, set_name: str | None) -> dict | None:
    prints = record.get("prints") or []
    if set_name:
        for print_info in prints:
            if print_info.get("set_name") == set_name:
                return print_info
    return prints[0] if prints else None


def _art_swap(
    record: dict, front_print: dict, art: dict, name_index: dict[str, dict]
) -> dict | None:
    """The client-side art-swap payload for a card whose deck entry borrows another printing's art.

    Carries the donor print's image and both frames' (era, layout) plus the recipient's keywords —
    everything the browser canvas needs to recomposite the borrowed art onto the recipient frame.
    Returns None when the donor card or a usable donor print is absent, leaving the recipient's own
    art to stand."""
    donor_record = name_index.get(art["name"].lower())
    if donor_record is None:
        return None
    donor_print = _select_print(donor_record, art.get("set_name"))
    if not (donor_print and donor_print.get("image_path")):
        return None
    era, layout = classify(record, front_print.get("set_name"))
    donor_era, donor_layout = classify(donor_record, donor_print.get("set_name"))
    return {
        "donor_img": donor_print["image_path"],
        "donor_era": donor_era,
        "donor_layout": donor_layout,
        "era": era,
        "layout": layout,
        "keywords": list(record.get("keywords") or ()),
    }


def _build_card(
    record: dict,
    set_name: str | None,
    section: str,
    by_id: dict[str, dict],
    *,
    owner: PlayerId,
    card_id: str,
    art: dict | None = None,
    name_index: dict[str, dict] | None = None,
) -> L5RCard:
    """Build the front face of a card. For a double-faced card, nest its back face: the fully built
    back when its record is on hand, else one synthesised from the front carrying the back art the
    front's print records, so a flip shows the other side. With neither, only the ``back_card_id``
    link is carried."""
    back_card_id = record.get("back_card_id")
    front_print = _select_print(record, set_name)
    back = None
    if back_card_id and back_card_id in by_id:
        back_record = by_id[back_card_id]
        back = _construct_face(
            back_record,
            _select_print(back_record, set_name),
            section,
            owner=owner,
            card_id=back_card_id,
            back_card_id=None,
            back=None,
        )
    front = _construct_face(
        record,
        front_print,
        section,
        owner=owner,
        card_id=card_id,
        back_card_id=back_card_id,
        back=back,
    )
    # The back-face row is excluded from deck queries (is_back), so there is usually no back record
    # to nest. The front's print still records the back art, so synthesise a back face from the
    # front carrying that art — the only field the manual table needs to draw the flipped side.
    if back is None and back_card_id and front_print and front_print.get("back_image_path"):
        synthetic_back = replace(
            front,
            id=back_card_id,
            image_front=Path(front_print["back_image_path"]),
            back_card_id=None,
            back=None,
        )
        front = replace(front, back=synthetic_back)
    if art and front_print and name_index is not None:
        art_swap = _art_swap(record, front_print, art, name_index)
        if art_swap is not None:
            front = replace(front, art_swap=art_swap)
    return front


def _construct_face(
    record: dict,
    print_info: dict | None,
    section: str,
    *,
    owner: PlayerId,
    card_id: str,
    back_card_id: str | None,
    back: L5RCard | None,
) -> L5RCard:
    card_type = (record.get("types") or [None])[0]
    card_cls, side = _classify(section, card_type)
    # image_front is the database-relative print path; the web client resolves it against the image
    # base URL. The subclasses' local default art is for the desktop/PDF renderers, not the wire.
    image_path = print_info.get("image_path") if print_info else None
    clans = record.get("clans") or []
    return card_cls(
        id=card_id,
        name=record.get("extended_title") or record["name"],
        side=side,
        owner=owner,
        clan=clans[0] if clans else None,
        keywords=tuple(record.get("keywords") or ()),
        text=record.get("text") or "",
        is_unique=bool(record.get("is_unique")),
        image_front=Path(image_path) if image_path else None,
        back_card_id=back_card_id,
        back=back,
        **_stat_fields(card_cls, card_type, record),
    )


def _stat_fields(card_cls: type, card_type: str | None, record: dict) -> dict:
    """The numeric and category stats a given card subclass holds, drawn from the database record."""
    if issubclass(card_cls, DynastyCard):
        fields = {"gold_cost": record.get("gold_cost")}
        if card_cls is DynastyPersonality:
            fields.update(
                force=record.get("force") or 0,
                chi=record.get("chi") or 0,
                personal_honor=record.get("personal_honor") or 0,
                honor_requirement=record.get("honor_requirement") or 0,
            )
        elif card_cls is DynastyHolding:
            fields["gold_production"] = record.get("gold_production") or 0
        return fields
    if issubclass(card_cls, FateCard):
        fields = {"focus": record.get("focus"), "gold_cost": record.get("gold_cost")}
        if card_cls is FateAttachment:
            fields["attachment_type"] = AttachmentType(card_type)
        return fields
    if card_cls is StrongholdCard:
        return {
            "starting_honor": record.get("starting_honor") or 0,
            "gold_production": record.get("gold_production") or 0,
            "province_strength": record.get("province_strength") or 0,
        }
    if card_cls is SenseiCard:
        return {"starting_honor": record.get("starting_honor") or 0}
    return {}
