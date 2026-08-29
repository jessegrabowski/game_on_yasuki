from collections.abc import Callable, Iterable
from typing import Protocol

from numpy.random import Generator, default_rng

from yasuki_core.engine.rules.actions import (
    Action,
    ActivateAbility,
    Cycle,
    DeclareAttack,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.agents import PayingAgent
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    assignment,
    assignment_token,
    ChooseAbilityTarget,
    ChooseCards,
    DecisionRequest,
    DecisionResponse,
)
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.projection import AttackView, GameView
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint


class Policy(Protocol):
    """Chooses which action a seat takes from the ones open to it.

    The counterpart to :class:`~yasuki_core.engine.rules.agents.Agent`: a policy picks an action, an
    agent answers a decision that action raises. A Recruit needs both — the policy chooses to
    recruit, the agent answers the payment.

    Policies read the seat's :class:`GameView` rather than the game itself, so one cannot see the
    opponent's hand and works unchanged over a network. The view carries live card objects, so a
    policy weighing a card's Gold Production or Gold Cost has them to hand.

    Attributes
    ----------
    name : str
        How this policy is reported. A simulation's numbers describe a deck *under a policy*, so a
        result quoted without one cannot be compared against anything.
    """

    name: str

    def choose(self, view: GameView, actions: list[Action]) -> Action: ...


class PassPolicy:
    """Passes whenever it can. The baseline a metric is validated against: a game played this way
    barely changes, so its numbers are checkable by hand."""

    name = "pass"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next((action for action in actions if isinstance(action, Pass)), actions[0])


class RandomPolicy:
    """Picks uniformly among the offered actions.

    Takes its own :class:`numpy.random.Generator` rather than reaching for a module-level one, so
    two runs of the same simulation with the same seed play the same game. Built without one it
    seeds itself, which is fine for a smoke run and useless for a reproducible one.
    """

    name = "random"

    def __init__(self, rng: Generator | None = None):
        self._rng = default_rng() if rng is None else rng

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return actions[int(self._rng.integers(len(actions)))]


class EconomicPolicy:
    """Buys the best economy on offer, and passes when there is nothing to buy.

    Ranks the plain Recruits by the province card's Gold Production first and its Gold Cost second,
    so the bigger producer wins and cost only breaks a tie between equals. Ties beyond that go to
    the lowest card id, which keeps a run reproducible rather than dependent on zone ordering.

    Affordability is never rechecked: :meth:`~yasuki_core.engine.session.EngineSession.legal_actions`
    withholds a recruit the seat cannot reach, so a policy deciding for itself would drift from the
    engine and offer choices the driver then refuses.

    Two things it deliberately does not weigh. Invest and Proclaim variants are skipped, because each
    changes what the payment has to answer without serving the economic aim. And the ranking reads
    the card's printed cost, which is what a view carries — a card whose cost a discount lowers is
    ranked as though it cost full price.

    This models a fixed player rather than a good one. The harness compares decks under one
    policy, which makes the policy a control variable: tuning it leaves runs from either side of
    the change incomparable.
    """

    name = "economic"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        purchases = [
            action
            for action in actions
            if isinstance(action, Recruit) and not action.invest and not action.proclaim
        ]
        if not purchases:
            return next((action for action in actions if isinstance(action, Pass)), actions[0])
        cards = _readable_province_cards(view)
        return min(purchases, key=lambda purchase: _rank(view, cards[purchase.card_id]))


class EconomicLegacyPolicy:
    """Buys like :class:`EconomicPolicy`, and takes the Legacy ability when it improves the board.

    Legacy banishes a card from hand to search the seat's dynasty deck and face-down provinces for a
    Legacy card, then places it face-up over a province card, discarding what was there. It is worth
    taking only when the best producer it could find beats the best one already face-up in its own
    provinces — otherwise it spends two cards to reach production the seat could simply buy.

    Finding nothing loses the game outright, so an empty ``legacy_pool`` is a hard veto rather than a
    weighing.

    Two simplifications it makes, both of which flatter the ability. It ranks on printed Gold
    Production, since a card not yet in play has no effective value to read. And it treats the
    banished hand card as free, which it is under this policy — nothing here ever plays from hand.
    """

    name = "economic-legacy"

    def __init__(self) -> None:
        self._buying = EconomicPolicy()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        legacy = next((action for action in actions if isinstance(action, Legacy)), None)
        if legacy is not None and _legacy_worth_taking(view):
            return legacy
        return self._buying.choose(view, actions)


def _legacy_worth_taking(view: GameView) -> bool:
    """Whether the Legacy pool holds a better producer than any the seat could actually buy.

    Measured against the Province cards within reach this turn: one the seat cannot pay for is no
    alternative to searching, it is a slot the seat is stuck with.
    """
    if not view.legacy_pool:
        # Unreachable while the comparison below is strict, since an empty pool produces 0 and no
        # board produces less. Kept because loosening that comparison would otherwise turn an empty
        # pool into a lost game.
        return False
    reach = _spendable(view)
    within_reach = [
        card
        for card in _readable_province_cards(view).values()
        if view.stat(card, Stat.GOLD_COST) <= reach
    ]
    return _best_production(view, view.legacy_pool) > _best_production(view, within_reach)


def cards_to_cycle(view: GameView) -> tuple[str, ...]:
    """The face-up Province cards worth putting on the bottom of the deck, by id.

    A card is worth replacing when it produces less Gold than a card drawn off the deck would on
    average, the deck being exactly the distribution a redraw samples from. A card with no Gold
    Production stat — a Personality — counts as producing nothing, so an economic seat replaces it
    whenever its deck produces at all.

    Returns empty when the deck is empty — a redraw would hand the same cards straight back — or
    when every face-up card already beats what the deck offers.
    """
    deck = view.dynasty_deck
    if not deck:
        return ()
    average = sum(_production(view, card) for card in deck) / len(deck)
    return tuple(
        sorted(
            card_id
            for card_id, card in _readable_province_cards(view).items()
            # Identifiable is not the same as face-up: a seat peeking its own face-down Province
            # cards can read one Cycle would refuse to be given.
            if card.face_up and _production(view, card) < average
        )
    )


class EconomicCyclePolicy:
    """Buys like :class:`EconomicPolicy`, and cycles an opening that its deck can beat.

    Cycle is a first-turn-only rulebook ability: put one or more face-up Province cards on the
    bottom of the dynasty deck, refill, and reveal. It is taken when :func:`cards_to_cycle` finds
    anything worth replacing.

    Answers its own Cycle decision as well as choosing it, so the cards put back are the ones the
    choice was made over. Every other decision falls through to :class:`PayingAgent`.
    """

    name = "economic-cycle"

    def __init__(self) -> None:
        self._buying = EconomicPolicy()
        self._answering = PayingAgent()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        cycle = next((action for action in actions if isinstance(action, Cycle)), None)
        if cycle is not None and cards_to_cycle(view):
            return cycle
        return self._buying.choose(view, actions)

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChooseCards) and request.resolver == "cycle":
            return DecisionResponse(cards_to_cycle(view))
        return self._answering.decide(request, view)


class GoldRushPolicy:
    """Drives for gold as hard as the rulebook allows: take Legacy, run the economy abilities on the
    board, buy, else clear the way.

    Five things in a fixed order of preference, each taken whenever it is offered. Cycle first: it
    is the seat's first turn only, costs nothing, and reshapes the opening the rest of the turn is
    decided against, so weighing anything before it would weigh a board about to be replaced. It
    puts back what the Dynasty Discard would flush and nothing else — a first turn raises three or
    four Gold, so the cheap producers a deck-average rule would bin are exactly the ones this policy
    can afford to buy with it. Then Legacy, when the pool holds a better producer than the board —
    it puts that card face-up in a Province where the same turn's Recruit can reach it. Then an
    activated ability this policy has an economic model for, which :data:`ABILITY_HEURISTICS`
    decides. Then the best purchase, ranked as :class:`EconomicPolicy` ranks it, which takes a
    Personality once no Holding is within reach: gold left in the pool is cleared at the phase
    change, and buying empties the Province either way. Then a Dynasty Discard of any face-up
    Province card it has no use for — one producing nothing, or one priced beyond what it could
    raise — which costs nothing and refills the Province for next turn.

    The discard is what separates this from :class:`EconomicPolicy`. Nothing else in the registry
    ever takes it, so a Province holding a card the seat cannot afford would stay held for the rest
    of the game and the seat would play on with fewer slots than it has. One discard is one choice,
    so a turn ending with three unaffordable Personalities flushes them over three windows and
    passes only once the Provinces are clear.

    Answers its own decisions as well as choosing, because an ability is only worth as much as the
    answers behind it: which card it targets, and whether to pay an optional cost the resolution
    offers. Everything it has no model for falls through to :class:`PayingAgent`.

    A ceiling rather than a player: it prices every non-producing card at nothing, so it throws away
    Personalities a real deck wins with. Its numbers bound what a deck's economy can do, and say
    nothing about how the deck is meant to be played.
    """

    name = "gold-rush"

    def __init__(self) -> None:
        self._buying = EconomicPolicy()
        self._answering = PayingAgent()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        cycle = next((action for action in actions if isinstance(action, Cycle)), None)
        if cycle is not None and _barren_province_cards(view):
            return cycle
        legacy = next((action for action in actions if isinstance(action, Legacy)), None)
        if legacy is not None and _legacy_worth_taking(view):
            return legacy
        ability = _worthwhile_ability(view, actions)
        if ability is not None:
            return ability
        chosen = self._buying.choose(view, actions)
        if not isinstance(chosen, Pass):
            return chosen
        flush = _flushable(view, actions)
        return flush if flush is not None else chosen

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChooseAbilityTarget):
            return DecisionResponse((_best_ability_target(request, view),))
        if isinstance(request, ChooseCards):
            if request.resolver == "cycle":
                return DecisionResponse(_barren_province_cards(view))
            if request.resolver == MODEST_FARM_STRAIGHTEN:
                return DecisionResponse(
                    request.candidates if _worth_sacrificing(request, view) else ()
                )
        return self._answering.decide(request, view)


class MilitaryPolicy:
    """Plays the gold rush, and defends its Provinces when it is attacked.

    Everything away from a battle is :class:`GoldRushPolicy`, which this wraps: the seat still
    cycles, tutors, runs its abilities, buys and flushes. What it adds is the one question a
    Defender is ever asked — where its units go.

    It attacks when it holds more Force than the seat it faces. Where those units go is not its
    question yet.

    It defends to save a Province rather than to win a battle. Resolution destroys a Province only
    when the attacking Force exceeds the defending Force *plus* the Province's Strength, so a
    defense that loses the battle outright can still hold the ground — and a seat that only
    contested what it could beat would concede most of the board while its army sat at home. Each
    Province it can save takes the fewest units that save it, cheapest first, and one it cannot save
    is left alone: units spent on a Province that falls anyway are units it does not have next turn.

    Not a player. It weighs no Province above another, keeps no reserve against the counterattack it
    invites, never attacks to destroy an army rather than to take ground, and cannot act inside a
    battle because nothing can yet.
    """

    name = "military"

    def __init__(self) -> None:
        self._playing = GoldRushPolicy()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        attack = next((action for action in actions if isinstance(action, DeclareAttack)), None)
        if attack is not None and _holds_the_initiative(view):
            return attack
        return self._playing.choose(view, actions)

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, AssignUnits):
            # The request is checked first because everything it delegates may arrive without a
            # view — the paying agent behind it answers a payment from the request alone.
            defending = _attack_being_defended(view)
            if defending is not None:
                return DecisionResponse(_defense(request, view, defending))
        return self._playing.decide(request, view)


def _holds_the_initiative(view: GameView) -> bool:
    """Whether the viewer has more Force to send than the seat it would attack.

    Declaring costs nothing on its own — an attack nobody assigns to resolves every battlefield with
    both sides empty and destroys nothing — so this only has to be right about who is ahead. Which
    Provinces are worth taking is settled at the assignment, where the attack exists and the
    Provinces' Strength can be read.
    """
    other = next(seat for seat in PlayerId if seat is not view.viewer)
    return _force_at_home(view, view.viewer) > _force_at_home(view, other)


def _force_at_home(view: GameView, seat: PlayerId) -> int:
    """The Force ``seat`` could still send: its unbowed Personalities standing at home.

    What a seat could assign rather than what it has — a bowed Personality may not be assigned at
    all, and one already at a battlefield has been. A card the viewer cannot identify is redacted to
    a :class:`HiddenCard` and so is never counted, which is why an opponent's face-down card cannot
    be weighed.
    """
    return sum(
        view.unit_force[entry.card.id]
        for entry in view.table.battlefield
        if isinstance(entry.card, L5RCard)
        and entry.card.owner is seat
        and isinstance(entry.card.printed, PersonalityPrint)
        and not entry.card.bowed
        and _is_home(view, entry.card.id)
    )


def _is_home(view: GameView, card_id: str) -> bool:
    """Whether ``card_id`` stands at home. An absent location is home, which is where a card is
    until an attack moves it."""
    location = view.table.locations.get(card_id)
    return location is None or location.is_home


def _attack_being_defended(view: GameView) -> AttackView | None:
    """The attack the viewer is defending, or None when it is the Attacker or there is no attack.

    The Attacker answers the same request class, so a policy that read the request alone would send
    its own units where the defense rule points them.
    """
    attack = view.attack
    return attack if attack is not None and attack.defender is view.viewer else None


def _defense(request: AssignUnits, view: GameView, attack: AttackView) -> tuple[str, ...]:
    """Where to send the Defender's units: the fewest that save each Province it can save.

    A Province survives when the attacking Force does not exceed the defending Force plus its
    Strength, so what it costs to hold is the attack against it less what it withstands on its own.
    Cheapest first, so a seat short of units saves as many Provinces as it can, and one it cannot
    reach is left alone. A unit is spent once — :meth:`AssignUnits.accepts` refuses the same
    Personality twice.

    Reads the candidates as a set of units rather than of places, which holds because
    :func:`~yasuki_core.engine.rules.battle.assignment_candidates` pairs every assignable unit with
    every battlefield.
    """
    unspent = {assignment(token)[0] for token in request.candidates}
    chosen: list[str] = []
    by_cost = sorted(
        (field.attacking_force - field.strength, index)
        for index, field in enumerate(attack.battlefields)
    )
    for needed, index in by_cost:
        if needed <= 0:  # the Province survives whatever happens here
            continue
        holding = _fewest_reaching(unspent, needed, view)
        if holding is None:  # nothing it could send saves this one
            continue
        unspent -= holding
        chosen.extend(assignment_token(card_id, index) for card_id in sorted(holding))
    return tuple(chosen)


def _fewest_reaching(unspent: set[str], needed: int, view: GameView) -> set[str] | None:
    """The fewest of ``unspent`` whose Force reaches ``needed``, or None if together they cannot.

    Largest first: a seat that spends three small units where one large one would do has two fewer
    to save the next Province with.
    """
    strongest = sorted(unspent, key=lambda card_id: (-view.unit_force[card_id], card_id))
    holding: set[str] = set()
    brought = 0
    for card_id in strongest:
        if brought >= needed:
            break
        holding.add(card_id)
        brought += view.unit_force[card_id]
    return holding if brought >= needed else None


# The activated abilities this policy has an economic model for, by printed id. An ability absent
# here is never activated: a policy cannot read what a card does, and guessing at an unmodelled one
# would spend a bow on an effect it has no way to value.
ABILITY_HEURISTICS: dict[str, "Callable[[GameView, L5RCard], bool]"] = {}

# Modest Farm's optional "you may destroy this Holding to straighten the target", by resolver name.
MODEST_FARM_STRAIGHTEN = "modest_farm_straighten"

# The Gold Production Millet Farm grants a Farm for the turn.
MILLET_FARM_BOOST = 2

# How much more a non-Farm target must produce than the Modest Farm spent to reach it, before the
# chain is worth the face-down Province refill that recruiting a non-Farm costs.
CHAIN_PAYOFF_RATIO = 3


def _worthwhile_ability(view: GameView, actions: list[Action]) -> ActivateAbility | None:
    """The lowest-id activation among ``actions`` whose heuristic says it is worth taking now, or
    None when none of them is modelled or any modelled one declines."""
    cards = _identifiable(view)
    worthwhile = [
        action
        for action in actions
        if isinstance(action, ActivateAbility)
        and (card := cards.get(action.card_id)) is not None
        and (heuristic := ABILITY_HEURISTICS.get(card.printed_id)) is not None
        and heuristic(view, card)
    ]
    return min(worthwhile, key=lambda action: action.card_id, default=None)


def _modest_farm_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Modest Farm should recruit out of sequence now.

    Nothing caps how many cards a seat recruits in its Dynasty Phase, so an out-of-sequence recruit
    is not an extra purchase on its own — the turn's production bounds the spending either way, and
    Modest Farm bows itself out of that production to grant it. Two things do pay for it, and one
    of them has to be true of some Holding the seat can still reach once that yield is gone.

    A Farm target is granted Renew, which refills the vacated Province face-up. Any other target
    refills it face-down, leaving the seat choosing from three live Provinces for the rest of the
    turn — a real cost, and one only a payoff elsewhere covers.

    That payoff is the chain. Destroying Modest Farm straightens the card it just recruited, so a
    big producer is spendable the moment it lands; when that Gold reaches a second producer the seat
    could not otherwise pay for, the recruit funds the recruit after it. Both halves are demanded of
    the chain — a target worth :data:`CHAIN_PAYOFF_RATIO` times the Farm being spent, and a producer
    on the other side of it. Firing on any purchase at all costs more in face-down refills than the
    chain returns.
    """
    reach = _spendable(view) - _production(view, source)
    cards = _readable_province_cards(view)
    for card in cards.values():
        cost = view.stat(card, Stat.GOLD_COST)
        if not card.face_up or cost > reach:
            continue
        if "Farm" in card.keywords:
            return True
        if _production(view, card) < CHAIN_PAYOFF_RATIO * max(_production(view, source), 1):
            continue
        left = reach - cost
        if any(
            other.face_up
            and other.id != card.id
            and _production(view, other) > 0
            and left < view.stat(other, Stat.GOLD_COST) <= left + _production(view, card)
            for other in cards.values()
        ):
            return True
    return False


def _millet_farm_worth_activating(view: GameView, source: L5RCard) -> bool:
    """Whether Millet Farm should grant its Farm bonus now.

    The grant lasts until end of turn and Millet Farm bows itself to give it, so the seat nets
    :data:`MILLET_FARM_BOOST` less whatever Millet Farm would have yielded — and only on a Farm
    still straight enough to be bowed for it. Taken when that net puts a Province card in reach
    that is out of it, and declined otherwise: an unspent bonus expires at end of turn.
    """
    straight_farms = any(
        card.id != source.id and not card.bowed and "Farm" in card.keywords
        for card in _in_play(view)
    )
    if not straight_farms:
        return False
    before = _spendable(view)
    return _newly_affordable(view, before, before - _production(view, source) + MILLET_FARM_BOOST)


ABILITY_HEURISTICS.update(
    {
        "modest_farm": _modest_farm_worth_activating,
        "millet_farm": _millet_farm_worth_activating,
    }
)


def _best_ability_target(request: ChooseAbilityTarget, view: GameView) -> str:
    """Which of ``request``'s candidates the ability should hit.

    Modest Farm takes a Farm ahead of anything else, because only a Farm target is granted the Renew
    that refills the vacated Province face-up; among equals it ranks them as purchases. Millet Farm's
    bonus is only collected by bowing the Farm that receives it, so it wants a straight one, and the
    largest — the bonus is flat, and the yield beside it is not. Anything else takes the first
    candidate, which is what a generic agent would have answered.
    """
    cards = _identifiable(view)
    source = cards.get(request.source_card_id)
    printed_id = None if source is None else source.printed_id
    if printed_id == "modest_farm":
        return min(
            request.candidates,
            key=lambda card_id: (
                "Farm" not in cards[card_id].keywords,
                _rank(view, cards[card_id]),
            ),
        )
    if printed_id == "millet_farm":
        return min(
            request.candidates,
            key=lambda card_id: (
                cards[card_id].bowed,
                -_production(view, cards[card_id]),
                card_id,
            ),
        )
    return request.candidates[0]


def _worth_sacrificing(request: ChooseCards, view: GameView) -> bool:
    """Whether to destroy Modest Farm to straighten the card it just recruited.

    Modest Farm is an engine rather than a producer: it straightens every turn its owner's turn
    begins, and each straightening is another out-of-sequence recruit. Trading that for one turn of
    the target being straight is only worth it when that turn buys something — the recruit enters
    play bowed, so straightening it is worth exactly the Gold it could still raise this turn.

    Taken when that Gold puts a Province card in reach that is out of it, and declined otherwise,
    which keeps the engine.
    """
    target = _identifiable(view).get(request.source_id or "")
    if target is None:
        return False
    before = _spendable(view)
    return _newly_affordable(view, before, before + _production(view, target))


def _barren_province_cards(view: GameView) -> tuple[str, ...]:
    """The viewer's face-up Province cards producing no Gold, by id, sorted so a run reproduces.

    What both this policy's Cycle and its Dynasty Discard act on: it prices a card at its Gold
    Production, so a card with none is one it would rather redraw. Empty when the dynasty deck is —
    a redraw would hand the same cards straight back.
    """
    if not view.dynasty_deck:
        return ()
    return tuple(
        sorted(
            card_id
            for card_id, card in _readable_province_cards(view).items()
            if card.face_up and _production(view, card) == 0
        )
    )


def _flushable(view: GameView, actions: list[Action]) -> DynastyDiscard | None:
    """The lowest-id Dynasty Discard among ``actions`` that clears a Province card the seat has no
    use for — one producing no Gold, or one costing more than it could raise — or None when every
    discard on offer would throw away a producer it can buy.

    An unaffordable card counts as junk because the slot is what matters: held, it produces nothing
    and blocks the refill.

    A card the viewer cannot identify is left alone: a discard is irreversible, and a seat that
    cannot read a card cannot know it is worthless.
    """
    cards = _readable_province_cards(view)
    reach = _spendable(view)
    junk = [
        action
        for action in actions
        if isinstance(action, DynastyDiscard)
        and action.card_id in cards
        and (
            _production(view, cards[action.card_id]) == 0
            or view.stat(cards[action.card_id], Stat.GOLD_COST) > reach
        )
    ]
    return min(junk, key=lambda action: action.card_id, default=None)


def _in_play(view: GameView) -> Iterable[L5RCard]:
    """The viewer's own cards on the battlefield that it can identify."""
    return (
        entry.card
        for entry in view.table.battlefield
        if not isinstance(entry.card, HiddenCard) and entry.card.owner is view.viewer
    )


def _identifiable(view: GameView) -> dict[str, L5RCard]:
    """Every card the viewer can name, by id — its own board and its own readable Province cards,
    which between them cover what an ability offers as a target."""
    cards: dict[str, L5RCard] = {card.id: card for card in _in_play(view)}
    cards.update(_readable_province_cards(view))
    return cards


def _spendable(view: GameView) -> int:
    """The Gold the viewer could raise right now by bowing what is straight, plus its pool.

    Deliberately smaller than what affordability reaches: a card that can raise its own yield does
    so at a price it sets, and a policy weighing whether a purchase is *worth* making should not
    count Gold it would rather not pay for. `legality.reachable_gold` must count it, because
    withholding a legal action is worse than offering one the seat declines.

    A policy also cannot ask :func:`~yasuki_core.engine.rules.economy.maximum_gold_production`: it
    sees a redacted :class:`GameView` rather than the live game, which is what keeps a policy from
    reading anything its seat is not entitled to.
    """
    return view.gold[view.viewer] + sum(
        _production(view, card) for card in _in_play(view) if not card.bowed
    )


def _newly_affordable(view: GameView, before: int, after: int, exclude: str | None = None) -> bool:
    """Whether any face-up Province card costs more than ``before`` and no more than ``after`` — the
    test of whether extra Gold buys anything rather than merely existing.

    Pass ``exclude`` when the Gold in question comes from recruiting one of those cards, so the card
    being bought is not also counted as what the purchase pays for.
    """
    if after <= before:
        return False
    return any(
        card.face_up and card.id != exclude and before < view.stat(card, Stat.GOLD_COST) <= after
        for card in _readable_province_cards(view).values()
    )


POLICIES: dict[str, type[Policy]] = {
    policy.name: policy
    for policy in (
        PassPolicy,
        RandomPolicy,
        EconomicPolicy,
        EconomicLegacyPolicy,
        EconomicCyclePolicy,
        GoldRushPolicy,
        MilitaryPolicy,
    )
}
"""Every policy a run can be configured with, by name."""


def make_policy(name: str) -> Policy:
    """Build the policy registered under ``name``.

    A stochastic policy seeds itself here; construct it directly with the run's
    :class:`numpy.random.Generator` when the run has to be reproducible.

    Raises
    ------
    KeyError
        If no policy is registered under ``name``, listing those that are.
    """
    if name not in POLICIES:
        raise KeyError(f"unknown policy {name!r}; known: {', '.join(sorted(POLICIES))}")
    return POLICIES[name]()


def _rank(view: GameView, card: L5RCard) -> tuple[int, int, str]:
    """How a province card sorts for purchase, lowest first.

    Gold Production leads and Gold Cost breaks the tie, both negated so the larger wins. The card id
    settles anything still level, so the choice does not follow zone order. Both stats are read
    through the view, so a modified card ranks on its current value.
    """
    production = _production(view, card)
    return -production, -view.stat(card, Stat.GOLD_COST), card.id


def _readable_province_cards(view: GameView) -> dict[str, L5RCard]:
    """The viewer's province cards it can identify, by id — what a Recruit's ``card_id`` refers to.

    Built by scanning rather than looked up, since a redacted view carries no id index. A card the
    viewer cannot identify — a province refilled face-down, until something reveals it — is skipped
    rather than ranked, since no Recruit can name it.
    """
    return {
        card.id: card
        for key, zone in view.table.zones.items()
        if key.owner is view.viewer and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if not isinstance(card, HiddenCard)
    }


def _best_production(view: GameView, cards: Iterable[L5RCard]) -> int:
    """The largest Gold Production among ``cards``, or 0 when none of them produces."""
    return max((_production(view, card) for card in cards), default=0)


def _production(view: GameView, card: L5RCard) -> int:
    """What ``card`` produces right now, or 0 for a card that is not a Holding at all."""
    if not isinstance(card.printed, HoldingPrint):
        return 0
    return view.stat(card, Stat.GOLD_PRODUCTION)
