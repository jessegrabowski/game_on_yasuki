# Abilities and costs

An activated ability is the most-used hook in the card module. It is also the one that breaks the
rule the others follow.

Every other hook is a decorator on a function. This one is a plain call, and its second argument is
a dataclass carrying five callables. {card}`Poorly Placed Garden` is the plainest complete one:

```python
register_ability(
    "poorly_placed_garden",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="Limited: bow this Holding to gain 2 Honor",
        cost=bow_cost,
        targets=_poorly_placed_garden_targets,
        effects=_poorly_placed_garden_effects,
        hits_every_target=True,
    ),
)
```

The shape is deliberate. An ability is four things that have to travel together, and a decorator on
any one of them would leave the other three somewhere else on the page.

## The four parts

**Timing** says when the ability may be taken, and by whom. `timings` is a tuple because a
Shattered Empire card can print two designators, and an ability carrying several may be used in any
round that permits any of them.

**Cost** is what the seat pays to announce it. It maps the game and the source card to the effects
that paying produces, so a cost is itself a list of effects rather than a number.

**Targets** maps the game and the source to the ids the ability may be pointed at. Returning an
empty list means the ability cannot be offered at all, which is how a card with no legal target
stays off the menu.

**Effects** maps the game, the source and one chosen target to what the ability does.

`hits_every_target=True` changes the last two. The ability resolves against every id `targets`
returns instead of asking the seat to pick one, which is how an untargeted "your other Farms" grant
is written. Poorly Placed Garden above uses it to act on itself.

## Where a cost builder lives

`abilities/costs.py` holds the builders more than one card uses: {func}`~.no_cost`,
{func}`~.bow_cost` and {func}`~.bow_parent_cost`. {func}`~.can_pay` sits beside them and answers
whether a given cost is payable now.

A cost only one card charges lives with that card, as `_<card id>_cost`, the way a target predicate
or an effects function does. That is the same rule `@attach_restriction` and the other per-card
registries follow, and it means a new combination of effects needs no new shared name.

`bow_cost` and `bow_parent_cost` are the pair to be careful with. `bow_cost` bows the card the
ability is on. `bow_parent_cost` bows the Personality an attachment is attached to, and is
unpayable while it is attached to none. The printed card does not make the difference obvious, and
[Reading card text](../../contributing/reading_card_text.md) covers how to tell which one a card
means.

`bow_cost` offers any waiver the card carries before bowing it, so an attachment that waives its
Personality's bow is consulted at the moment of payment.

## The optional fields

`key` names an ability among several its card prints, so an action can say which one it takes.
`targeting_message` is what the ability targets, worded as the card prints it, which the target
prompt reads:
"Target your Courtier at any location for Inexplicable Challenge".
`tireless` lets an ability be used while its card is bowed. `located_at` says where the card must
be, defaulting to the battlefield. `battle_designators` and `targets_any_location` govern what a
battle ability can reach, and [Adding a Card](../../contributing/adding_a_card.md) explains both
under attachments. `keywords` holds the ability keywords printed ahead of the designator, as in
"Political Battle:", so a card asking whether the resolving action was Political has something to
read. `repeatable` is the Repeatable modifier: under an arc whose ruleset sets
`abilities_once_per_turn`, which the current CR does and earlier arcs did not, an ability on a
card in play is once per turn without it. `legality.activatable` enforces that through the same
once-per-turn keys a handler claims by hand. The registration audit compares both with the card's text and rejects a
registration that leaves one off or invents one. `trait` marks a trait worded "after X, you may
...": it is offered in the Response Step like a Response, so its controller orders it among the
other answers to the same action or declines it, but its effects resolve as a trait's, with no
Interrupt step against them, and a card reading "your action" does not see them.

## Abilities a card is given

{func}`~.abilities_for` is the one place the engine asks what abilities a card has, and it answers
with two lists joined: the ones registered for the card's printed id and in force under the
active ruleset, then the ones an {class}`~.AbilityGrant` record in `game.ongoing` gives it. An
ability names no ruleset unless the card's text differs between arcs, in which case the card
registers one `Ability` per ruleset, each with `ruleset=ruleset.SHATTERED_EMPIRE.name` or the
like, and only the one naming `ruleset.ACTIVE` is read.

```{literalinclude} ../../../src/yasuki_core/engine/rules/abilities/registry.py
:pyobject: abilities_for
:language: python
```

A granted ability is code like a printed one. The granting card registers a factory with
`@granted_ability`, and the record carries the `context` the factory builds from, the ids the
granting action chose. Legality, once-per-turn keys and the activation menu all read
`abilities_for`, so a granted ability answers to each of them through the same path a printed one
does. The factory's `Ability` needs a `key` whenever its card could already hold one, since the
two are told apart the way any two abilities on one card are.

## What narrows a target list

A handler's `targets` output is not final. `legal_targets` in `legality.py` narrows it by the Rules
of Location before the ability is offered, so a card's own predicate answers what the card says and
the central rule answers where the card may reach.

Write the predicate for the card's text and let the rule do the rest. A handler that tries to
reimplement the Rules of Location will drift from them.

## An Interrupt

A Strategy printing an Interrupt is not an `Ability`. It has no target and no effects of its own,
since what it does is decided against the effect it interrupts, and no round offers it. It is
registered with `register_interrupt` as an {class}`~.Interrupt`, whose `answers` names the effect
type it may be played against and whose `interrupt` maps the pending effect to an
{class}`~.Interruption`: the effect that resolves in its place and whatever else happens.

The Interrupt step is step D of the Action Sequence, and it is a round of its own. When an action
hands its effects to {func}`~yasuki_core.engine.rules.triggers.resolve_action_effects`, they are
held on the stack as a `HeldAction` and, when any seat holds an Interrupt to take, an `ActionRound`
of kind `INTERRUPT` is pushed over the round the action was taken in, the active player first (CR,
Action Sequence step D; ShE datasheet, Interrupt). Inside it `legal_actions` offers each seat a
{class}`~.PlayInterrupt` per card whose Interrupt answers the forecast and a
{class}`~.DiscardToInterrupt` per card a rulebook Interrupt could discard, plus a `Pass`. A seat
holding none is skipped, as is a seat with no unit at the battlefield while a battle is being
fought (CR, Actions in Battle: the Rule of Presence applies to Interrupts), a seat that took an
Interrupt is offered again when the opportunity comes round, and consecutive passes close the
step and resolve the held action. What the action is about
to do is the {func}`~yasuki_core.engine.rules.interrupts.forecast`: the effects in order, a
`Then`'s contents, an ability's built effects behind the
{class}`~yasuki_core.engine.rules.abilities.activation.ResolveAbility` that targets them, and an
attack's outcome when the attack reaches on the board as it stands. An Interrupt taken is stored
as a modification bound to the effect it answered and applied when that effect comes up to
resolve, which is the CR's "delayed until those effects occur": Okura's destroy waits on the Fear
it modifies, and a Courage discard adjusts the Fear as it resolves. A card that reads "negate"
returns {class}`~.Negated` around the effect it answers, which resolves as nothing where the
effect would have, and the forecast then shows nothing behind it. When the forecast holds several
effects a card could answer, {class}`~.ChooseInterruptEffect` asks which, and a card that answers
the action as a whole, "negate the action's effects", sets `answers_every` and binds to all of
them at once. Any of the action's own effects can be answered, and only those: the step is over
what step E hands to `resolve_action_effects`, never a cost, a trait's effects or a rulebook
procedure's, and what a choice resolver produces later is not foreseeable and is not offered.

An Interrupt is an action on the tape, so "the action" it modifies stays the one held beneath the
step: the action record is not reset by an Interrupt, and backing out of any question an Interrupt
asks unwinds the Interrupt alone. During an action whose ability sets `unstoppable`, the modifier
printed ahead of its designator, no other seat is entitled in the step (ShE datasheet,
Unstoppable). The rulebook Interrupts' once-per-action limit is `GameState.interrupts_taken`,
cleared with the action.

A Personality or attachment prints an Interrupt too, taken from play rather than from hand, and an
Event face up in a Province may as well. Its `located_at` names the battlefield or the Province,
and it is offered under the gates an activated ability in play answers to: unbowed, within the
Rules of Location, and unused this turn. `cost` is what the card
gives up to take it, so "destroy this Item to negate" and "reshuffle Aitso to negate" are both
costs, and a card that cannot pay is not offered. `applies` narrows the offer beyond the effect's
type, so Doji Yuten answers a bowing of his controller's other Personality and not his own.

An attack's outcome, the `Bow` behind a Fear or the `Destroy` behind a Ranged Attack, follows the
comparison through the cascade as an effect of its own and is in the forecast when the attack
reaches, so an Interrupt answering `Bow` or `Destroy` is offered against what an attack would do.

An Interrupt that reads "Target your X" sets `targets`, and the step asks for the target with a
{class}`~.ChooseInterruptTarget` once the card is named, passing the chosen card to `interrupt` as
a fourth argument. A card whose `targets` finds nothing is not offered.

The action's targeting is itself the first effect in the window. Once a seat has chosen an
ability's target, {func}`~.apply_ability_target` resolves a single
{class}`~yasuki_core.engine.rules.abilities.activation.ResolveAbility` effect: performing it
records the target as the action's and produces the ability's effects against that target as its
follow-on. That is where "the action targets him instead of another card, if legal" lives.
{card}`Final Sacrifice` answers `ResolveAbility` and replaces it with one naming the Yojimbo, so the
ability is built against him and nothing has to be redirected. "If legal" is
{func}`~yasuki_core.engine.rules.interrupts.legal_substitutes`: of the cards the Interrupt names,
those the ability could target other than the one chosen.
