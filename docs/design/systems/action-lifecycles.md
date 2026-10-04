# Action lifecycles

Most actions do not resolve in one step. A Recruit is announced, paused for payment, resumed, and
only then does a card reach the table. Each multi-step action lives in its own module under
`rulebook/`, and they all share the shape below.

## Announce, pause, resume

An action that costs something splits into three parts.

Announcing queues the work and builds the question the seat has to answer. An ability's cost
effects do it for an activated ability, including the rulebook Recruit on a Province card and the
Kharmic abilities on the card they spend.

The pause is a pending decision on `GameState`. Nothing further happens until a seat answers,
which is what lets a human, a bot and a replayed tape all drive the same machine.

Resuming runs the queued work. {func}`~.run_stack` drains the deferred items one at a time and
stops again the moment one of them pauses for another decision:

```{literalinclude} ../../../src/yasuki_core/engine/rules/turn/sequence.py
:pyobject: run_stack
:language: python
```

## The work stack

An item on `GameState.stack` is a frozen dataclass that implements one Protocol:

```{literalinclude} ../../../src/yasuki_core/engine/rules/vocabulary/work.py
:pyobject: WorkItem
:language: python
```

There is no central switch. Each item lives in the module of the procedure it continues and
answers `resume` by calling that procedure, so adding a step to a procedure means declaring the
item beside it, giving it a `resume`, and pushing it. No other file changes. A continuation may
end in a question of its own: `SelectAbilityTarget` resumes by setting `pending`, and
`ContinuePayment` asks for more producers when the pool is still short.

What is on the stack, and what each continues:

- `SelectEquipTarget` in `rulebook/equip.py`: an Equip's target choice, deferred behind its
  payment. A Recruit needs no step of its own: it is an ability whose effects are the
  {class}`~.effects.Recruit` effect, whose arrival is followed by its Sincerity tokens removed, a
  Proclaim's gain and the refill. An Invest needs no step of its own: it raises the card's Gold Cost before the payment,
  and {func}`~.resolve_invest` answers the card's entry.
- `ResolveStrategy` and `DiscardPlayed` in `abilities/strategy.py`: a played Strategy's ability,
  then its discard. `SelectAbilityTarget` and `ApplyAbilityEffects` in `abilities/activation.py`:
  an ability's targeting or its untargeted effects, deferred behind its cost.
- `RequestPayment`, `ContinuePayment` in `gold/payment.py` and `CompleteProduction` in
  `gold/production.py`: the question a Strategy or an Equip asks for its cost once the board its
  announcement left has settled, the payment loop, and the bow that follows a producer's window.
- `FightNextBattle` in `battle/resolution.py`: the next battlefield, or the end of the Fight
  Segment.
- `ResumeCascade` in `triggers.py`: the remainder of a walk an interrupting effect paused.
  `AnnounceEvent` there is an event announced once the settling queued above it has run, as a
  card's entry into play is.
- `ApplyEffects` in `effects.py`: effects held until the work above them has run, which the rulebook
  procedures and an Interrupt's effects behind its payment push.
- `AccrueSincerity`, `EnforceMaximumHandSize`, `BeginNextTurn`, `OpenNextTurn`, `OpenFirstTurn` and
  `OpenRound` in `turn/sequence.py`: the turn boundary. The end of the turn resolves the effects held
  for it, accrues Sincerity and announces the turn's end, then the rulebook's draw resolves as an
  ordinary `DrawCard` and the hand-size check waits behind whatever it fulfilled. The next turn
  waits behind the end-of-turn discard and what dropping the expiring modifiers fulfilled, and a
  turn's opening is three instants queued in order, straighten, reveal and the turn's beginning,
  with the round opening last so that a question asked while opening resolves into the previous
  round.

The stack is last in, first out. A procedure that needs two steps in order pushes the later one
first. A cascade that pauses pushes its stash on top of whatever was already queued, which is why
`BeginNextTurn` goes on before the discard is announced: the answer to a discard trigger's
question has to resume that cascade before the next turn begins.

Work items never reach the tape. Replay rebuilds the stack by re-running the procedures that push
them, and [The replay log](the-replay-log.md) is why that is enough.

## How a card Recruits

A card whose text Recruits another card returns {func}`~.recruit_card`: the card's Gold Cost paid
for it, then the same {class}`~.effects.Recruit` effect the rulebook Recruit resolves (CR,
Recruit). The Recruit is part of the card's own action, so it passes through that action's
Interrupt step, and the enter-play triggers happen the way they would otherwise.

## The modules

`rulebook/recruit.py` is the longest and the one to read first. It registers the rulebook Recruit
as three abilities every face-up Province card carries, plain, Proclaimed and Invested, paid by
{func}`~.recruit_gold` and resolved by {func}`~.recruit_effects`. {func}`~.bring_into_play` and
{func}`~.effects_after_entering_play` are what the {class}`~.effects.Recruit` effect does. A card
that Recruits calls {func}`~.recruit_card`.

`rulebook/equip.py` carries the attachment rules, including {func}`~.may_attach`,
{func}`~.equip_targets` and {func}`~.creation_targets`, which judges a token template rather than
a card because a created attachment has no card to ask about yet.

One module per action covers the rest: `lobby.py` and the three Favor modules. `kharmic.py` is
different in kind: the two Kharmic abilities are registered through
{func}`~.register_keyword_ability` as abilities the Kharmic keyword confers on every card carrying
it, one activated from the hand and one from a Province, each spending the card it is used on. From
there they are announced, paid and interrupted as any card's ability is, and a card that grants
Kharmic grants the abilities with it. `dynasty_discard.py` has the same shape without a keyword:
{func}`~.register_location_ability` confers Dynasty Discard on every card in a Province, and the
ability discards the card it sits on and refills the Province behind the reactions to the discard.

A player ability with no card to sit on has a second home. `rulebook/proxies.py` deals a proxy card
into each seat's rulebook zone as the game begins, for every proxy the active
{class}`~yasuki_core.ruleset.Ruleset` names in `rulebook_proxies`, and abilities registered on the
proxy are activated from there. Cycle is the first: `cycle.py` registers it on the Cycle proxy with
`from_rulebook` set, as every rulebook ability is, and {func}`~.is_cycle` recognizes the action by
its key. `legacy.py` registers Legacy on its own proxy the same way, and {func}`~.is_legacy`
recognizes it. Its banish is the cost, so the seat can still back out at that pick. The search is an
`Evaluate` effect, which looks through the deck and face-down Provinces only once the Interrupt step
has closed. `inheritance.py` does the same for Inheritance, whose cost spends the seat's
once-per-game use and turns its Stronghold over, and {func}`~.is_inheritance` recognizes it. Lobby
follows them, with one proxy per arc family because the arcs word it differently: Onyx Edition names
a proxy carrying the Open Lobby, which Shattered Empire inherits, and the pre-Gold ruleset names one
carrying its Limited Lobby. {func}`~.is_lobby` recognizes either by the key they share. The Tk
client never draws the zone. It lists the proxies' abilities on the board menu, except Inheritance,
which it offers on the Stronghold the ability turns over. The zone is not a card zone: nothing in
play sees what it holds, and the sandbox refuses to move anything into or out of it.

The Favor's rulebook abilities sit on a proxy of their own, one per arc family, which [The Imperial
Favor](the-imperial-favor.md) describes. The Tk client lists them on the Favor card in the holder's
hand instead of the board menu.

## Where a card plugs in

Through the effect vocabulary, not these modules. A card that recruits returns
{func}`~.recruit_card`. A card that equips returns the equip effect.
[Abilities and costs](abilities-and-costs.md) covers what a card declares.
