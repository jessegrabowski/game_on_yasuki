# Action lifecycles

Most actions do not resolve in one step. A Recruit is announced, paused for payment, resumed, and
only then does a card reach the table. Each multi-step action lives in its own module under
`rulebook/`, and they all share the shape below.

## Announce, pause, resume

An action that costs something splits into three parts.

Announcing queues the work and builds the question the seat has to answer.
{func}`~.announce_recruit` does this for a Recruit, and an ability's cost effects do it for an
activated ability, including the rulebook Kharmic abilities on the card they spend.

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

- `ResolveRecruit`, `EnterPlay` and `FinishRecruit` in `rulebook/recruit.py`: the three parts of
  a Recruit after its payment, the card's before-entry effects, its entry, and what follows the
  entry. `SelectEquipTarget` in `rulebook/equip.py` is an Equip's target choice, deferred behind
  its payment, and `FinishInvest` its Invest, deferred behind the announcement that it entered
  play.
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
- `ApplyEffects` in `effects.py`: the generic deferral, which {class}`~.Then` and the rulebook
  costs push.
- `DrawAtEndOfTurn`, `EnforceMaximumHandSize`, `BeginNextTurn`, `OpenNextTurn`, `OpenFirstTurn`,
  `AnnounceTurnStart` and `OpenRound` in `turn/sequence.py`: the turn boundary. The draw waits
  behind the delayed effects the end of the turn resolves, the hand-size check behind whatever the
  draw fulfilled, the next turn behind the end-of-turn discard and what dropping the expiring
  modifiers fulfilled, and a turn's
  opening is three instants queued in order, straighten, reveal and announcement, with the round
  opening last so that a question asked while opening resolves into the previous round.

The stack is last in, first out. A procedure that needs two steps in order pushes the later one
first. A cascade that pauses pushes its stash on top of whatever was already queued, which is why
`BeginNextTurn` goes on before the discard is announced: the answer to a discard trigger's
question has to resume that cascade before the next turn begins.

Work items never reach the tape. Replay rebuilds the stack by re-running the procedures that push
them, and [The replay log](the-replay-log.md) is why that is enough.

## Why a card returns `RecruitCard`

A card that brings another card into play does not put it there. It returns an effect, and the
effect enters the same machine an ordinary Recruit does, so the payment, the Invest option and the
enter-play triggers all happen the way they would otherwise.

The effect vocabulary has an entry for each action with a machine behind it, and returning that
effect is how a card borrows the whole sequence.

## The modules

`rulebook/recruit.py` is the longest and the one to read first: {func}`~.recruit`,
{func}`~.announce_recruit`, {func}`~.apply_invest_amount`, {func}`~.resolve_recruit`,
{func}`~.apply_fortification_province` and {func}`~.finish_recruit` are the steps in order.

`rulebook/equip.py` carries the attachment rules, including {func}`~.may_attach`,
{func}`~.equip_targets` and {func}`~.creation_targets`, which judges a token template rather than
a card because a created attachment has no card to ask about yet.

One module per action covers the rest: `cycle.py`, `legacy.py`, `inheritance.py`, `lobby.py`
and the three Favor modules. `kharmic.py` is different in kind: the two Kharmic abilities are
registered through {func}`~.register_keyword_ability` as abilities the Kharmic keyword confers on
every card carrying it, one activated from the hand and one from a Province, each spending the
card it is used on. From there they are announced, paid and interrupted as any card's ability is,
and a card that grants Kharmic grants the abilities with it. `dynasty_discard.py` has the same
shape without a keyword: {func}`~.register_location_ability` confers Dynasty Discard on every card
in a Province, and the ability discards the card it sits on and refills the Province behind the
reactions to the discard.

A player ability with no card to sit on has a second home. `rulebook/proxies.py` deals a proxy
card into each seat's rulebook zone as the game begins, for every proxy the active
{class}`~yasuki_core.ruleset.Ruleset` names in `rulebook_proxies`, and abilities registered on
the proxy are activated from there. No arc names one yet. The zone is not a card zone: nothing in
play sees what it holds, and the sandbox refuses to move anything into or out of it.

## Where a card plugs in

Through the effect vocabulary, not these modules. A card that recruits returns
`RecruitCard`. A card that equips returns the equip effect.
[Abilities and costs](abilities-and-costs.md) covers what a card declares.
