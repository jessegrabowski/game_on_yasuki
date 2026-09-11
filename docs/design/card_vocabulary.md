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
   AskDistribution
   AskOption
   AttachCard
   Banish
   AttackEffect
   BanishTopFate
   Bow
   Choose
   CounterOnAttachedProvince
   CreateToken
   DelayStraighten
   DelayedEffect
   Destroy
   DestroyProvince
   Discard
   DiscardFavor
   DrawCard
   Effect
   Fear
   GainGold
   GainHonor
   LoseGame
   WinGame
   MeleeAttack
   GrantPriority
   GrantKeyword
   GrantMinimum
   GrantLobbyBonus
   GrantProvinceStrength
   GrantModifier
   IgnoreHonorRequirements
   InterruptingEffect
   Move
   MoveToDeck
   MoveToHand
   PayFavorCost
   PayGold
   PlaceInProvince
   PutIntoPlay
   RangedAttack
   RecruitCard
   RefillProvince
   RevealProvinces
   Show
   ShuffleDeck
   SpendOncePerTurn
   Straighten
   TakeFavor
   Then
   Unpayable
```

## Events

An event records a state change that has already been committed. A trigger subscribes to one event
type and one card's `printed_id`. The cascade drains the events raised by its effects until no
further events are produced. `ProducingGold` is the exception to "already committed": it opens the
window *before* a producer's yield is read, so a trait firing there still counts toward the
production it interrupts, and `ProducedGold` announces the result once the Gold has landed.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.vocabulary.game_events

.. autosummary::

   CardDiscarded
   CounterGained
   Destroyed
   EnteredPlay
   ProducedGold
   ProducingGold
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
.. currentmodule:: yasuki_core.engine.rules.vocabulary.decisions

.. autosummary::

   AssignUnits
   ChooseBattlefield
   BanishForLegacy
   ChooseAbilityTarget
   ChooseAmount
   ChooseCards
   ChooseDistribution
   ChooseEquipTarget
   ChooseFortificationProvince
   ChooseInheritanceTarget
   ChooseInvestAmount
   ChooseOption
   LeaveBowed
   ChooseLegacyCard
   ChooseLobbyTarget
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
.. currentmodule:: yasuki_core.engine.rules.vocabulary.work

.. autosummary::

   ApplyAbilityEffects
   ApplyEffects
   CompleteProduction
   ContinuePayment
   DiscardPlayed
   FightNextBattle
   FinishRecruit
   ResolveEquip
   ResolveRecruit
   ResolveStrategy
   ResumeCascade
   SelectAbilityTarget
```

## Stats, durations, and counters

A modifier adjusts one `Stat` for one `Duration`. A counter is named scalar state held on a card, and
each counter declares the per-count stat it grants, so a card's wealth tokens raise its Gold
Production without a modifier being recorded.

There are five ongoing types rather than one because they rest on different things. `Modifier` is
the general case and adjusts a stat on a card. A Province is a slot rather than a card, so
`ProvinceModifier` records a change to its strength. A Lobby Bonus rests on a player, so
`LobbyModifier` records that, and the datasheet says an adjustment to Family Honor through one is
neither an Honor gain nor an Honor loss. `KeywordGrant` gives a keyword instead of a number.
`Minimum` floors a stat rather than adding to it, and is applied after the bonuses and penalties
total rather than among them, so a minimum of 1 Chi cannot be summed away.

`Duration` has three values. `UNTIL_END_OF_TURN` is the default for an action or ability effect.
`WHILE_SOURCE_IN_PLAY` expires when the card the effect came from leaves the battlefield, which is
how counters, attachments and continuous auras are held. `PERMANENT` outlives its source leaving play, and still ends when its *target* leaves the table,
because a card that leaves play ceases to exist.

```{eval-rst}
.. currentmodule:: yasuki_core.engine.rules.vocabulary.modifiers

.. autosummary::

   Stat
   Duration
   KeywordGrant
   LobbyModifier
   Minimum
   Modifier
   ProvinceModifier
```

```{eval-rst}
.. currentmodule:: yasuki_core.game_pieces.counters

.. autosummary::

   Counter
```
