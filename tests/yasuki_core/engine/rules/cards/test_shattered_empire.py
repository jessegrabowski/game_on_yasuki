from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_force
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.cards.shattered_empire import FINE_SWORD
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


def _artist_game(*, carrying: tuple[str, ...] = (), free_handed: bool = False):
    """P1's Weapon Artist in play beside "hero", who is already carrying ``carrying`` Weapons, and
    with an empty-handed "rival" beside him when ``free_handed``."""
    game = two_seat_game()
    token_template(
        game,
        FINE_SWORD,
        name="Fine Sword",
        card_type="Item",
        keywords=("One-Handed", "Sword", "Weapon"),
        force=2,
        chi=1,
    )
    put_in_play(game, holding("artist", printed_id="weapon_artist", gold_production=6))
    put_in_play(game, personality("hero", force=3, chi=3))
    for index, keyword in enumerate(carrying):
        attached(
            game,
            attachment(f"held{index}", keywords=("Weapon", keyword), force_modifier=1),
            "hero",
        )
    if free_handed:
        put_in_play(game, personality("rival", force=3, chi=3))
    return game


def test_weapon_artist_bows_to_equip_a_created_sword():
    session = EngineSession.start(_artist_game().table, P1)

    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    hero = game.table.cards_by_id["hero"]
    sword = attachments_of(game, hero)[0]
    assert sword.name == "Fine Sword"
    assert sword.is_token is True
    assert game.table.cards_by_id["artist"].bowed is True  # the cost
    assert effective_force(game, hero) == 5  # 3 printed, +2 from the sword


def test_the_created_sword_is_a_one_handed_weapon():
    """The +1C half, and the keywords the next Weapon has to fit around, come off the token print
    rather than being spelled out at the creation site."""
    session = EngineSession.start(_artist_game().table, P1)

    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    sword = attachments_of(session.game, session.game.table.cards_by_id["hero"])[0]
    assert sword.chi_modifier == 1
    assert set(sword.keywords) == {"One-Handed", "Sword", "Weapon"}


def test_weapon_artist_offers_only_the_personalities_with_a_hand_free():
    """One Weapon per Personality, so the sword has nowhere to go on the one already carrying — the
    Weapon rules judge it before it exists. The filter has to narrow the targets rather than
    withdraw the ability, which is what the empty-handed rival is here to show."""
    session = EngineSession.start(
        _artist_game(carrying=("One-Handed",), free_handed=True).table, P1
    )

    session.act(P1, ActivateAbility("artist"))

    assert session.game.pending.candidates == ("rival",)


def test_weapon_artist_is_withheld_when_every_personality_is_carrying():
    session = EngineSession.start(_artist_game(carrying=("One-Handed",)).table, P1)

    assert ActivateAbility("artist") not in session.legal_actions(P1)


def test_weapon_artist_is_withheld_while_bowed():
    """His bow is the cost, so a Weapon Artist who has already bowed for gold makes nothing."""
    session = EngineSession.start(_artist_game().table, P1)
    session.game.table.cards_by_id["artist"].bow()

    assert ActivateAbility("artist") not in session.legal_actions(P1)


def test_the_created_sword_leaves_the_game_with_its_personality():
    """A created card has no discard pile: it exists only in play, so a destroyed unit takes it off
    the table entirely rather than into the pile its Personality goes to."""
    session = EngineSession.start(_artist_game().table, P1)
    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))
    game = session.game
    sword_id = attachments_of(game, game.table.cards_by_id["hero"])[0].id

    resolve_effects(game, [Destroy("hero", P1)])

    discard = game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert sword_id not in game.table.cards_by_id
    assert [card.id for card in discard.cards] == ["hero"]


def test_weapon_artist_replays_to_the_same_board():
    session = EngineSession.start(_artist_game().table, P1)
    session.act(P1, ActivateAbility("artist"))
    session.submit(P1, DecisionResponse(("hero",)))

    assert replay(session.log).table == session.game.table
