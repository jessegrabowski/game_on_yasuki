from dataclasses import dataclass

from collections.abc import Callable

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.invest import equip_invest_amount
from yasuki_core.engine.rules.effects import Invest
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.board.queries import owned_personalities
from yasuki_core.engine.rules.vocabulary.decisions import ChooseEquipTarget, DecisionResponse
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.discounts import discounted_gold, equip_purchase
from yasuki_core.engine.rules.gold.payment import RequestPayment
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_weapon_limit
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import CardPrint
from yasuki_core.game_pieces.prints import AttachmentPrint
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.engine.rules.units.membership import attached_to


def weapons_on(game: GameState, personality: L5RCard) -> tuple[L5RCard, ...]:
    """The Weapon Items attached to ``personality``."""
    return tuple(
        card
        for card in attachments_of(game, personality)
        if keywords.WEAPON in effective_keywords(game, card)
    )


def may_hold_weapon(game: GameState, personality: L5RCard, weapon_keywords: frozenset[str]) -> bool:
    """Whether ``personality`` has room for a Weapon carrying ``weapon_keywords`` under the Weapon
    rules.

    Two independent rules apply. How many Weapons fit is a characteristic: one by default, two for
    a Kensai, so raising it is a modifier rather than an exemption from a rule. Two-Handed is
    exclusive on top of that: a Personality, "even a Kensai", cannot hold a Two-Handed Weapon
    beside any other Weapon, in either order (CR, Weapon, Kensai, Two-Handed).

    Takes the keywords rather than the Weapon so a card about to be created can be judged before it
    exists.
    """
    held = weapons_on(game, personality)
    if len(held) >= effective_weapon_limit(game, personality):
        return False
    if keywords.TWO_HANDED in weapon_keywords:
        return not held
    return not any(keywords.TWO_HANDED in effective_keywords(game, card) for card in held)


def may_attach_weapon(game: GameState, personality: L5RCard, weapon: L5RCard) -> bool:
    """Whether ``weapon`` may join ``personality`` under the Weapon rules."""
    return may_hold_weapon(game, personality, effective_keywords(game, weapon))


# What a card's own text says may attach: an attachment's "Can only attach to a Samurai", or a
# Personality's "Will not attach Followers". Read for both the attachment and the Personality it
# would join, and keyed by printed id like the other per-card registries. The rulebook's
# restrictions live in this module as code. A restriction only one card states lives with that card.
AttachRestriction = Callable[[GameState, L5RCard, L5RCard], bool]
ATTACH_RESTRICTIONS: HandlerRegistry[AttachRestriction] = HandlerRegistry(
    "attach restrictions", "already has an attach restriction"
)
attach_restriction = ATTACH_RESTRICTIONS.make_decorator()


# What a card's own text takes off the Gold of Equipping one card onto one Personality: a
# Personality's "O-Win Equips Jade cards for 1 less", or an attachment's "Equips to a Crab Clan
# Personality for 1 less". Read for both cards, like the attach restrictions above.
EquipDiscount = Callable[[GameState, L5RCard, L5RCard], int]
EQUIP_DISCOUNTS: HandlerRegistry[EquipDiscount] = HandlerRegistry(
    "equip discounts", "already has an Equip discount"
)
equip_discount = EQUIP_DISCOUNTS.make_decorator()


def equip_discount_onto(game: GameState, personality: L5RCard, card: L5RCard) -> int:
    """The Gold the texts of ``card`` and ``personality`` take off Equipping the one onto the
    other."""
    return sum(
        handler(game, personality, card)
        for holder in (card, personality)
        if (handler := EQUIP_DISCOUNTS.get(holder.printed_id)) is not None
    )


# Cards whose own text lets the rulebook Equip ability target them in their owner's Fate discard
# pile, by printed id, each with whether it may right now. Tao Defenders: "Compassion: The rulebook
# Equip ability may target this Follower in the discard pile (paying all costs)."
EquipFromDiscard = Callable[[GameState, L5RCard], bool]
EQUIPS_FROM_DISCARD: HandlerRegistry[EquipFromDiscard] = HandlerRegistry(
    "equips from discard", "already lets Equip reach it in the discard pile"
)
equips_from_discard = EQUIPS_FROM_DISCARD.make_decorator()


def equippable(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The cards the rulebook Equip ability may reach for ``seat``: those in its hand, and those in
    its Fate discard pile whose own text lets Equip target them there."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
    discard = game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
    reachable = tuple(card for card in discard if _may_equip_from_discard(game, card))
    return (*hand, *reachable)


def _may_equip_from_discard(game: GameState, card: L5RCard) -> bool:
    permission = EQUIPS_FROM_DISCARD.get(card.printed_id)
    return permission is not None and permission(game, card)


def may_attach(game: GameState, personality: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` may attach to ``personality``, by the text of each and by the rulebook's
    limits on Spells and Weapons.

    Only Weapons answer to the Weapon rules. A Follower or a plain Item is limited by neither the
    count nor Two-Handed exclusivity.
    """
    if not _texts_admit(game, personality, card, holders=(card, personality)):
        return False
    if is_spell(card) and not may_cast_spells(game, personality):
        return False
    if keywords.WEAPON not in effective_keywords(game, card):
        return True
    return may_attach_weapon(game, personality, card)


def may_attach_created(game: GameState, personality: L5RCard, printed: CardPrint) -> bool:
    """Whether a card created from ``printed`` may attach to ``personality``.

    The card does not exist yet, so its keywords come off the print rather than through the grants a
    card in play reads. A created card carries the plain proxy print of what it is and no text of its
    own, so only the Personality's text and the rulebook's rules apply.
    """
    created = L5RCard(id=printed.printed_id, printed=printed, owner=personality.owner)
    if not _texts_admit(game, personality, created, holders=(personality,)):
        return False
    printed_keywords = frozenset(printed.keywords)
    if keywords.WEAPON not in printed_keywords:
        return True
    return may_hold_weapon(game, personality, printed_keywords)


def _texts_admit(
    game: GameState, personality: L5RCard, card: L5RCard, *, holders: tuple[L5RCard, ...]
) -> bool:
    """Whether the attach restriction each of ``holders`` prints, if any, lets ``card`` join
    ``personality``."""
    for holder in holders:
        restriction = ATTACH_RESTRICTIONS.get(holder.printed_id)
        if restriction is not None and not restriction(game, personality, card):
            return False
    return True


def creation_targets(
    game: GameState, seat: PlayerId, printed: CardPrint, *, keyword: str | None = None
) -> tuple[L5RCard, ...]:
    """The Personalities ``seat`` may create a card from ``printed`` onto: its own, that the
    attachment rules still admit. A player creates onto their own, as they attach (CR, Attachments).

    Parameters
    ----------
    game : GameState
        The live game the board is read from.
    seat : PlayerId
        The seat creating the card.
    printed : CardPrint
        The template the created card is stamped from, judged by the attachment rules.
    keyword : str, optional
        Narrows the Personalities to those carrying it, the "your target Samurai Personality" a
        card names. Default None, which offers them all.
    """
    return tuple(
        personality
        for personality in owned_personalities(game, seat)
        if may_attach_created(game, personality, printed)
        and (keyword is None or keyword in effective_keywords(game, personality))
    )


def equip_targets(game: GameState, card: L5RCard, *, discount: int = 0) -> tuple[L5RCard, ...]:
    """The Personalities ``card`` may be Equipped to: the ones its own owner has in play, that the
    attachment rules still admit. A player may only attach to their own (CR, Attachments).

    Parameters
    ----------
    discount : int, optional
        The discount the Equip is paid at, which narrows the Personalities to those granting it
        (CR, Targeting Paradoxes). Default 0, the full price, which narrows nothing.
    """
    return tuple(
        personality
        for personality in owned_personalities(game, card.owner)
        if may_attach(game, personality, card)
        and (not discount or equip_discount_onto(game, personality, card) == discount)
    )


def equip(game: GameState, card_id: str, *, invest: bool = False, discount: int = 0) -> None:
    """Announce an Equip: take the card out of the hand into its entering-play area, settle the
    board that leaves, then ask for its cost with the choice of which Personality it joins queued
    behind. Answering that choice attaches the card (CR, Action Sequence steps B and C; CR,
    Entering-Play Areas).

    Equip is the rulebook action, with a cost and a target. An effect that merely *attaches* a card
    reaches the same board without paying (CR, Equip), so the two do not share a path.

    With ``invest``, the card is Invested in before its cost is asked for, so the cost is its raised
    Gold Cost (CR, Invest). Raise ``ValueError`` if ``invest`` names an Invest whose amount the
    player chooses. Every
    attachment printing one prints a fixed cost, so the amount is settled here rather than through a
    decision, and a variable one would need a step this path does not have.

    With ``discount``, the Equip is paid that much less and may join only the Personalities granting
    it (CR, Targeting Paradoxes).
    """
    card = game.table.cards_by_id[card_id]
    candidates = tuple(target.id for target in equip_targets(game, card, discount=discount))
    hand = game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards
    if any(held is card for held in hand):
        game.announced_cards |= {card_id}
    if invest:
        triggers.pay_costs(game, [Invest(card.id, equip_invest_amount(game, card))])
    game.stack.append(SelectEquipTarget(card_id, candidates))
    price = equip_gold(game, card, discount=discount)
    game.stack.append(RequestPayment(card.owner, price, card.name, card_id))
    triggers.enforce_state_based_actions(game)


def equip_gold(game: GameState, card: L5RCard, *, invest: bool = False, discount: int = 0) -> int:
    """The Gold Equipping ``card`` charges: its Gold Cost less the seat's discount on the Equip and
    less ``discount``, the one its target's text grants, floored at zero. With ``invest``, its Gold
    Cost as the Invest about to be laid will raise it, so a card already Invested in is priced
    without the flag. Raise ``ValueError`` for ``invest`` on a card printing no fixed Invest."""
    invest_amount = equip_invest_amount(game, card) if invest else 0
    paid = discounted_gold(
        game, equip_purchase(card), effective_gold_cost(game, card) + invest_amount
    )
    return max(0, paid - discount)


@dataclass(frozen=True, slots=True)
class SelectEquipTarget:
    """Raise an Equip's target choice once its cost has been paid. Deferred so a payment whose own
    cascade pauses for a decision resolves fully before the Personality is chosen.

    Attributes
    ----------
    card_id : str
        The attachment being Equipped, still in hand.
    candidates : tuple of str
        The Personalities it may join, fixed before paying so the choice is never left empty.
    """

    card_id: str
    candidates: tuple[str, ...]

    def resume(self, game: GameState) -> None:
        owner = game.table.cards_by_id[self.card_id].owner
        game.pending = ChooseEquipTarget(
            seat=owner,
            candidates=self.candidates,
            source_card_id=self.card_id,
        )


def apply_equip_target(
    game: GameState, request: ChooseEquipTarget, response: DecisionResponse
) -> None:
    """Attach the paid-for card to the chosen Personality."""
    resolve_equip(game, request.source_card_id, response.choices[0])


def resolve_equip(game: GameState, card_id: str, target_id: str) -> None:
    """Bring the paid-for attachment out of its hand or discard pile and onto its Personality."""
    card = game.table.cards_by_id[card_id]
    from_hand = card_id in game.announced_cards
    game.announced_cards -= {card_id}
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    ops.attach_to_personality(game.table, card, game.table.cards_by_id[target_id])
    # Queued beneath the settling, which may stop to ask a question: the board is legal before
    # anything is told the card arrived, for the reason _put_into_play gives.
    game.stack.append(triggers.AnnounceEvent(EnteredPlay(card_id, from_hand=from_hand)))
    triggers.enforce_state_based_actions(game)


def is_spell(card: L5RCard) -> bool:
    """Whether ``card`` is a Spell. Only attachments carry a type, so the print answers first."""
    return (
        isinstance(card.printed, AttachmentPrint) and card.attachment_type is AttachmentType.SPELL
    )


def may_cast_spells(game: GameState, personality: L5RCard) -> bool:
    """Whether ``personality`` may hold and cast a Spell, which only a Shugenja may (CR, Spell)."""
    return keywords.SHUGENJA in effective_keywords(game, personality)


def has_caster(game: GameState, spell: L5RCard) -> bool:
    """Whether ``spell`` hangs on a Personality who may cast it."""
    caster = attached_to(game, spell)
    return caster is not None and may_cast_spells(game, caster)
