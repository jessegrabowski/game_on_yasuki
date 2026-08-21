# Card Vocabulary

A card's behavior is expressed entirely in a closed set of data types. Cards do not mutate the board;
they return *effects*, which a single boundary applies. The listings below name every member of each
category, and a test fails when the engine gains one this page does not list — so a type missing
here is a bug in the page rather than a type you may not use.

The runtime relationships between these types (the trigger cascade, decision handling, and the turn
machine) are described in [the engine design](engine.md).

## Effects

An effect is a frozen dataclass describing one change to game state, and it carries its own
behavior. `perform` commits the change and returns the events it raises; `is_payable` reports
whether an ability can pay the effect as a cost; `describe` names the effect in one line, for
reading a cascade back. Triggers and activated abilities return lists of effects, and the cascade
commits each in turn, draining the events they raise until no further events are produced.

An `InterruptingEffect` pauses the cascade rather than committing. The walker records the decision
its `request` returns, stashes the remainder of the cascade, and resumes once the seat answers. An
effect cannot declare itself interrupting without supplying that decision, because `request` is
abstract on the category.

`Then` is the counterpart for sequencing. An effect placed inline runs before the events already
queued behind it, so a step that must follow another card's reaction to what just happened is
deferred through `Then` instead.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.effects

.. autosummary::

   AdjustCounter
   Ask
   AskAmount
   AttachCard
   Banish
   BanishTopFate
   Bow
   Choose
   CreateToken
   Destroy
   DestroyProvince
   Discard
   DrawCard
   Effect
   GainGold
   GainHonor
   GrantModifier
   IgnoreHonorRequirements
   InterruptingEffect
   MoveToDeck
   MoveToHand
   PayGold
   PlaceInProvince
   RecruitCard
   RefillProvince
   RevealProvinces
   Show
   ShuffleDeck
   Straighten
   Then
   Unpayable
```

## Events

An event records a state change that has already been committed. A trigger subscribes to one event
type and one card's `printed_id`. The cascade drains the events raised by its effects until no
further events are produced.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.events

.. autosummary::

   CardDiscarded
   CounterGained
   Destroyed
   EnteredPlay
   Revealed
   Straightened
   TurnStarted
```

## Decisions

A decision request is a question the engine puts to a single seat. The engine runs until it requires
input, records the request, and returns control; the seat replies with a `DecisionResponse`, and
execution resumes. The `accepts` method verifies that a response is structurally well formed.
Legality with respect to game state is checked separately.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.decisions

.. autosummary::

   BanishForLegacy
   ChooseAbilityTarget
   ChooseAmount
   ChooseCards
   ChooseEquipTarget
   ChooseInvestAmount
   ChooseLegacyCard
   ChoosePayment
   Confirm
   DecisionRequest
   DecisionResponse
   DiscardToHandSize
   PlaceLegacy
```

## Deferred work

A work item is a unit of engine work held on `GameState.stack` and run once the current decision
clears. An action pushes its remaining steps onto the stack when an earlier step pauses, so that an
interrupting trait resolves first, and a `Then` effect queues its sub-sequence the same way. The
stack is last in, first out. Work items are ephemeral: replay reconstructs the stack by re-running
the action rather than by deserializing it.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.work

.. autosummary::

   ApplyAbilityEffects
   ApplyEffects
   FinishRecruit
   ResolveEquip
   ResolveRecruit
   ResumeCascade
   SelectAbilityTarget
```

## Stats, durations, and counters

A modifier adjusts one `Stat` for one `Duration`. A counter is named scalar state held on a card, and
each counter declares the per-count stat it grants, so a card's wealth tokens raise its Gold
Production without a modifier being recorded.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.modifiers

.. autosummary::

   Stat
   Duration
   Modifier
```

```{eval-rst}
.. currentmodule:: yasuki_core.game_pieces.counters

.. autosummary::

   Counter
```
