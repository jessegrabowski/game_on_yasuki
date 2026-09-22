from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.idioms import register_entry, register_event_entry
from yasuki_core.engine.rules.effects import PutIntoPlay, RecruitCard
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import Equip, PlayStrategy, Recruit
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    EventPrint,
    PersonalityPrint,
    RingPrint,
)

from tests.yasuki_core.engine.builders import (
    attached,
    end_phase,
    holding,
    personality,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
TITLE = "probe_hitomi"

register_entry("unique_entry_probe")
register_event_entry("singular_event_probe")


def _titled_personality(
    card_id: str,
    *,
    owner: PlayerId = P1,
    title: str = TITLE,
    name: str | None = None,
    is_unique: bool = True,
    keywords: tuple[str, ...] = (),
) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        name=name or title,
        printed_id=title,
        side=Side.DYNASTY,
        owner=owner,
        is_unique=is_unique,
        force=2,
        chi=3,
        personal_honor=0,
        gold_cost=0,
        keywords=keywords,
    )


def _unique_item(card_id: str, *, title: str = "probe_sword") -> L5RCard:
    return L5RCard.of(
        AttachmentPrint,
        id=card_id,
        name=title,
        printed_id=title,
        side=Side.FATE,
        owner=P1,
        is_unique=True,
        attachment_type=AttachmentType.ITEM,
        force=0,
        chi=0,
        gold_cost=0,
    )


def _dynasty_phase(*in_play: L5RCard, province: L5RCard) -> EngineSession:
    """P1's Dynasty Phase with ``province`` face-up in its first Province."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1))
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [register(state, holding("refill", owner=P1))]
    for card in in_play:
        put_in_play(state, register(state, card))
    register(state, province).turn_face_up()
    zone = ProvinceZone(owner=P1)
    zone.add(province)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = zone
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


def test_a_second_unique_card_of_one_title_is_not_offered_for_recruit():
    session = _dynasty_phase(_titled_personality("held"), province=_titled_personality("dup"))

    assert Recruit("dup") not in session.legal_actions(P1)


def test_a_non_unique_card_in_play_withholds_nothing():
    in_play = _titled_personality("held", is_unique=False)
    session = _dynasty_phase(in_play, province=_titled_personality("dup"))

    assert Recruit("dup") in session.legal_actions(P1)


def test_a_unique_card_of_another_title_is_offered():
    session = _dynasty_phase(
        _titled_personality("held"), province=_titled_personality("other", title="probe_toshimoko")
    )

    assert Recruit("other") in session.legal_actions(P1)


def test_the_opponents_copy_withholds_nothing():
    session = _dynasty_phase(
        _titled_personality("theirs", owner=P2), province=_titled_personality("dup")
    )

    assert Recruit("dup") in session.legal_actions(P1)


def test_an_experienced_version_is_refused_until_overlaying_exists():
    # The CR's Experienced exception to Unique is overlaying, which replaces the lesser version
    # without the new card entering play. Nothing overlays yet, so entering normally is refused.
    experienced = _titled_personality(
        "hitomi_x", title=f"{TITLE}_experienced", keywords=("Experienced",)
    )
    session = _dynasty_phase(_titled_personality("held"), province=experienced)

    assert Recruit("hitomi_x") not in session.legal_actions(P1)


def test_a_unique_experienced_version_may_join_a_non_unique_base():
    # The base card is not Unique, so the seat controls no Unique card of the title (CR, Unique).
    experienced = _titled_personality(
        "hitomi_x", title=f"{TITLE}_experienced", keywords=("Experienced",)
    )
    session = _dynasty_phase(_titled_personality("held", is_unique=False), province=experienced)

    assert Recruit("hitomi_x") in session.legal_actions(P1)


def test_a_unique_attachment_beside_its_copy_is_not_offered_to_equip():
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1))
    put_in_play(state, personality("hero"))
    attached(state, _unique_item("worn"), "hero")
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _unique_item("spare")))
    session = EngineSession.start(state, P1)

    assert Equip("spare") not in session.legal_actions(P1)


def _ring(card_id: str) -> L5RCard:
    return L5RCard.of(
        RingPrint,
        id=card_id,
        name="Ring of Air",
        printed_id="unique_entry_probe",
        side=Side.FATE,
        owner=P1,
        is_unique=True,
    )


def test_put_into_play_of_a_duplicate_does_nothing():
    game = two_seat_game()
    put_in_play(game, _ring("worn"))
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, _ring("held")))

    resolve_effects(game, [PutIntoPlay("held")])

    assert "held" in {card.id for card in hand.cards}
    assert "held" not in {card.id for card in game.table.battlefield.cards}


def test_recruit_card_of_a_duplicate_asks_no_payment():
    session = _dynasty_phase(_titled_personality("held"), province=_titled_personality("dup"))
    game = session.game

    resolve_effects(game, [RecruitCard("dup")])

    assert game.pending is None
    assert "dup" not in {card.id for card in game.table.battlefield.cards}


def test_an_entry_from_hand_is_withheld_beside_its_copy():
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1))
    put_in_play(state, register(state, _ring("worn")))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, _ring("held")))
    session = EngineSession.start(state, P1)

    assert PlayStrategy("held") not in session.legal_actions(P1)


def _singular(card_id: str, *, owner: PlayerId = P1, title: str = "probe_shadow") -> L5RCard:
    return _titled_personality(
        card_id, owner=owner, title=title, is_unique=False, keywords=(keywords.SINGULAR,)
    )


def test_a_singular_card_is_withheld_while_any_seat_has_a_copy_in_play():
    session = _dynasty_phase(_singular("theirs", owner=P2), province=_singular("dup"))

    assert Recruit("dup") not in session.legal_actions(P1)


def test_a_singular_card_of_another_title_is_offered():
    session = _dynasty_phase(
        _singular("theirs", owner=P2), province=_singular("other", title="probe_truth")
    )

    assert Recruit("other") in session.legal_actions(P1)


def test_a_singular_event_is_not_offered_beside_its_copy():
    event = L5RCard.of(
        EventPrint,
        id="event",
        name="Death of the Mantis Clan",
        printed_id="singular_event_probe",
        side=Side.DYNASTY,
        owner=P1,
        keywords=(keywords.SINGULAR,),
    )
    in_play = _singular("theirs", owner=P2, title="singular_event_probe")
    session = _dynasty_phase(in_play, province=event)

    assert not any(
        action.card_id == "event"
        for action in session.legal_actions(P1)
        if isinstance(action, PlayStrategy)
    )
