from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint, HoldingPrint
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules.projection import project


def _game() -> GameState:
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=7)


def test_rules_fields_are_public_to_both_seats():
    game = _game()
    game.phase = Phase.DYNASTY
    game.add_gold(PlayerId.P1, 3)
    game.add_gold(PlayerId.P2, 1)

    for viewer in PlayerId:
        view = project(game, viewer)
        assert view.viewer is viewer
        assert view.turn == 1
        assert view.active is PlayerId.P1
        assert view.phase is Phase.DYNASTY
        assert view.first_player is PlayerId.P1
        # Both seats' gold pools are visible to either viewer.
        assert view.gold == {PlayerId.P1: 3, PlayerId.P2: 1}


def test_pending_decision_reaches_only_the_answerer():
    game = _game()
    request = DiscardToHandSize(PlayerId.P1, ("a", "b", "c"), count=2)
    game.pending = request

    assert project(game, PlayerId.P1).pending == request
    assert project(game, PlayerId.P2).pending is None


def test_table_is_redacted_for_the_viewer():
    game = _game()
    secret = L5RCard.of(FatePrint, id="P1-secret", name="Ambush", side=Side.FATE, owner=PlayerId.P1)
    game.table.cards_by_id[secret.id] = secret
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(secret)

    owner_view = project(game, PlayerId.P1)
    opponent_view = project(game, PlayerId.P2)

    hand_key = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    assert owner_view.table.zones[hand_key].cards[0] is secret
    assert isinstance(opponent_view.table.zones[hand_key].cards[0], HiddenCard)


def test_gold_view_is_decoupled_from_the_live_pool():
    game = _game()
    view = project(game, PlayerId.P1)
    game.add_gold(PlayerId.P1, 5)
    # The projection captured a snapshot; later production does not mutate it.
    assert view.gold[PlayerId.P1] == 0


# --- the viewer's own Legacy pool -----------------------------------------------------------------


def _legacy_holding(card_id: str, owner=PlayerId.P1, production=3) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=card_id,
        name=f"Estate {card_id}",
        side=Side.DYNASTY,
        owner=owner,
        gold_production=production,
        keywords=("Legacy",),
    )


def _dynasty_holding(card_id: str, owner=PlayerId.P1) -> L5RCard:
    """A plain Holding, for tests where the Legacy keyword would be a false signal."""
    return L5RCard.of(
        HoldingPrint, id=card_id, name=f"Holding {card_id}", side=Side.DYNASTY, owner=owner
    )


def _seed_deck(game: GameState, owner: PlayerId, *cards) -> None:
    game.table.decks[DeckKey(owner, Side.DYNASTY)].cards = list(cards)
    for card in cards:
        game.table.cards_by_id[card.id] = card


def test_the_pool_holds_the_viewers_findable_legacy_cards():
    game = _game()
    estate = _legacy_holding("P1-9")
    plain = L5RCard.of(
        HoldingPrint,
        id="P1-1",
        name="Mine",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_production=2,
    )
    _seed_deck(game, PlayerId.P1, plain, estate)

    assert project(game, PlayerId.P1).legacy_pool == (estate,)


def test_the_pool_is_empty_when_no_legacy_card_remains():
    game = _game()
    _seed_deck(
        game,
        PlayerId.P1,
        L5RCard.of(HoldingPrint, id="P1-1", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1),
    )

    assert project(game, PlayerId.P1).legacy_pool == ()


def test_the_pool_never_reaches_the_other_seat():
    """A seat knows what it built; its opponent's buried cards stay buried."""
    game = _game()
    _seed_deck(game, PlayerId.P1, _legacy_holding("P1-9"))

    assert project(game, PlayerId.P2).legacy_pool == ()


def test_the_pool_is_sorted_rather_than_left_in_deck_order():
    """Which Legacy cards remain is the seat's knowledge; where they sit in the shuffle is not, so
    the deck's order must not survive into the view."""
    game = _game()
    first, second = _legacy_holding("P1-2"), _legacy_holding("P1-1")
    _seed_deck(game, PlayerId.P1, first, second)  # deck order puts P1-2 ahead of P1-1

    assert [card.id for card in project(game, PlayerId.P1).legacy_pool] == ["P1-1", "P1-2"]


def test_the_dynasty_deck_shows_the_seat_what_it_still_holds():
    # A seat built its deck, so what remains in it is its own knowledge — the basis for judging
    # whether a redraw beats the row it is looking at.
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-a"), _dynasty_holding("P1-b"))

    assert [card.id for card in project(game, PlayerId.P1).dynasty_deck] == ["P1-a", "P1-b"]


def test_the_dynasty_deck_never_reaches_the_other_seat():
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-a"))

    assert project(game, PlayerId.P2).dynasty_deck == ()


def test_the_dynasty_deck_is_sorted_rather_than_left_in_deck_order():
    # Composition is the seat's knowledge; the shuffle is not. Leaving deck order in the view would
    # hand a policy the next card to be drawn.
    game = _game()
    _seed_deck(game, PlayerId.P1, _dynasty_holding("P1-2"), _dynasty_holding("P1-1"))

    assert [card.id for card in project(game, PlayerId.P1).dynasty_deck] == ["P1-1", "P1-2"]


def test_a_face_down_province_card_is_still_findable():
    game = _game()
    buried = _legacy_holding("P1-9")
    buried.turn_face_down()
    zone = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(
        owner=PlayerId.P1
    )
    zone.add(buried)
    game.table.cards_by_id[buried.id] = buried

    assert project(game, PlayerId.P1).legacy_pool == (buried,)


def test_a_revealed_province_card_has_left_the_pool():
    """A face-up province card is already recruitable, so the search does not reach it — and the
    policy would see it among its Recruits instead."""
    game = _game()
    revealed = _legacy_holding("P1-9")
    revealed.turn_face_up()
    zone = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(
        owner=PlayerId.P1
    )
    zone.add(revealed)
    game.table.cards_by_id[revealed.id] = revealed

    assert project(game, PlayerId.P1).legacy_pool == ()


def test_a_conditionally_granted_legacy_card_is_findable():
    """Shrine of Courtesy grants itself Legacy while its controller went second, so a search that
    read printed keywords alone would never surface it."""

    def shrine(owner: PlayerId) -> L5RCard:
        return L5RCard.of(
            HoldingPrint,
            id=f"{owner.name}-4",
            name="Shrine of Courtesy",
            side=Side.DYNASTY,
            owner=owner,
            printed_id="shrine_of_courtesy",
            keywords=("Temple", "Unique"),
            gold_production=2,
        )

    game = _game()  # first_player is P1, so P2 went second
    second_players = shrine(PlayerId.P2)
    _seed_deck(game, PlayerId.P2, second_players)
    assert project(game, PlayerId.P2).legacy_pool == (second_players,)

    # The same Holding stays unfindable for the seat that went first: the grant is conditional.
    _seed_deck(game, PlayerId.P1, shrine(PlayerId.P1))
    assert project(game, PlayerId.P1).legacy_pool == ()
