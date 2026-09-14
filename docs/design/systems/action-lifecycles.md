# Action lifecycles

Most actions do not resolve in one step. A Recruit is announced, paused for payment, resumed, and
only then does a card reach the table. Each multi-step action lives in its own module under
`rulebook/`, and they all share the shape below.

## Announce, pause, resume

An action that costs something splits into three parts.

Announcing queues the work and builds the question the seat has to answer.
{func}`~.announce_recruit` does this for a Recruit, and `announce_rulebook_cost` does it for the
rulebook actions that charge gold.

The pause is a pending decision on `GameState`. Nothing further happens until a seat answers,
which is what lets a human, a bot and a replayed tape all drive the same machine.

Resuming runs the queued work. {func}`~.run_stack` drains the deferred items one at a time and
stops again the moment one of them pauses for another decision.

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

One module per action covers the rest: `cycle.py`, `kharmic.py`, `legacy.py`, `inheritance.py`,
`lobby.py`, `dynasty_discard.py`, and the three Favor modules. `costs.py` is the exception, a
shared helper, not an action.

## Where a card plugs in

Through the effect vocabulary, not these modules. A card that recruits returns
`RecruitCard`. A card that equips returns the equip effect.
[Abilities and costs](abilities-and-costs.md) covers what a card declares.
