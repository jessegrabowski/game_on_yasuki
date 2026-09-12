# Adding a card

Read the card's text, find the shape, and go to the page for that shape. This page is the index and
the mechanics that apply to every card, not a tutorial.

If you have never written one, read [What a card is](what_a_card_is.md) and
[The card data](the_card_data.md) first, then come back here with a card in hand.

## Which hook?

| The card says | Hook | Example |
|---|---|---|
| Produces a variable amount of gold | `@gold_handler(id)` | {card}`Jade Works` |
| Costs less to bring into play, conditionally | `@recruit_discount(id)` | {card}`Colonial Farm` |
| "After X happens..." | `@on(Event, id)` | {card}`Rice Farm` |
| An activated ability with a cost | `register_ability(id, Ability(...))` | {card}`Millet Farm` |
| "Response: after X..." | `register_ability(id, Ability(timings=(ActionTiming.RESPONSE,), ...))` | {card}`Caravansary` |
| Buy an extra effect while recruiting | `register_invest(id, InvestAbility(...))` | {card}`Rebuilt Harbor` |
| Carries a keyword only sometimes | `@keyword_grant(id)` | {card}`Fortified Farmlands` |
| Gives the Personality it hangs on a stat | `@attachment_grant(id)` | {card}`Haramaki-do` |
| Limits what it will attach to | `@attach_restriction(id)` | {card}`Brothers in Arms` |
| Buys its Invest cheaper, conditionally | `@invest_discount(id)` | {card}`Moto Ikarichi, Bloodseeker` |
| Changes the strength of an attack | `@attack_strength_against(id)` | {card}`Aseth's Legion` |
| Changes a Province's strength | `@province_strength_grant(id)` | {card}`Defensive Memorial` |
| Puts itself into play as an Edict | `register_edict(id)` | {card}`Act With Authority` |
| An Event played from the Province it sits in | `register_event_entry(id)` | {card}`Shadow of the Dark God` |
| Raises its own Gold Production as it bows | `register_self_grant(id, n)`, or `@self_grant(id)` when the grant has a condition | {card}`Jade Mine`, {card}`Slave Pits` |
| Enters play unbowed where the rule says bowed | `register_enters_unbowed(id)` | {card}`Poorly Placed Garden` |
| "May remain bowed" | `register_may_remain_bowed(id)` | {card}`Culling Grounds` |
| Waives the bow cost of the Personality it hangs on | `register_bow_waiver(id)` | {card}`Shadowlands Ambassador` |
| Pays somebody's Imperial Favor cost | `@favor_payer(id)` | {card}`Manjodh` |
| "You have a +N Lobby Bonus" | `@lobby_bonus_grant(id)` | {card}`Shigekawa's Court` |
| Stops a player Lobbying at all | `@lobby_bar(id)` | {card}`Wasp Sensei` |
| "May not Lobby" | `register_may_not_lobby(id)` | {card}`Moto Chen` |

The `id` is the card's database id, the same string as in the set YAML. A pre-commit hook rejects an
id no card has and tells you the nearest real one.
[Registration and the audit](../design/systems/registration-and-the-audit.md) is why that hook
exists.

These are the events a trigger can answer: `EnteredPlay`, `Destroyed`, `Straightened`,
`CardDiscarded`, `CounterGained`, `Revealed`, `TurnStarted`, `ProducingGold` and `ProducedGold`. A
card whose moment is not one of them needs a new event, which is a core change.

## Which page?

Work down this list. Each rung costs more than the one above, so stop at the first that can say
what the card does.

1. **A number.** The card produces gold, or costs less, or has a stat it did not print. Answer with
   a number and write no effects at all. [Holdings and gold](holdings_and_gold.md) and
   [Stats and costs](stats_and_costs.md).
2. **A reaction.** "After X happens, do Y." Return a list of effects from a trigger.
   [Reacting to an event](reacting_to_events.md).
3. **An ability.** The card does something on purpose, for a cost.
   [Writing an ability](an_ability.md), then
   [A card that prints two abilities](several_abilities.md) when it prints more than one.
4. **A question.** The card says "choose" or "may", so a seat has to answer before it can finish.
   [Asking the player a question](asking_a_question.md).

Then by what the card is:

- Hangs on a Personality: [Cards that attach](attachments.md)
- Fights, or changes a fight: [Cards that act in a battle](battle_cards.md)
- Makes a card: [Cards that create cards](creating_cards.md)
- Acts from hand or a Province, or stays in play:
  [Cards that act from outside play](cards_outside_play.md)
- Touches the Imperial Favor or Lobby: [The Favor and the court](the_favor_and_the_court.md)

## Where the code goes

A reprinted card is implemented once, in the set that printed it first, and
`test_every_card_is_implemented_in_its_first_printing_module` enforces that. Find that set, open
the module of the same name as its YAML file, and add the card in id order under a header:

```python
# --- Rice Farm ---
```

Everything the card does goes in that one block: its triggers, its target predicates, its effects
helper, its registration. A pre-commit hook asserts the ordering, the one-header-per-card rule, and
that the header names the card the block registers, on the modules your commit touches.

Name every function in the block for the card and the job it does, as `_<card id>_<role>`, where the
role is one of `cost`, `targets`, `effects`, an entry point of a registry (`gold`, `invest`,
`keywords`, `recruit_discount`, `invest_discount`, `attachment_grant`, `attach_restriction`,
`attack_strength`, `province_strength`, `lobby_bonus`, `lobby_bar`, `favor_payer`), or the event a
trigger answers (`entered_play`, `destroyed`, `straightened`, `turn_started`, `counter_gained`,
`card_discarded`, `producing_gold`, `produced_gold`, `entered_play_or_destroyed`). A card printing
several abilities qualifies the role with that ability's key, as in
`_incendiary_archers_fear_effects`, since one name per role would collide between them, and the key
has to be one the module really registers. A choice resolver is named for the choice instead,
`_resolve_<the string it is registered under>`. Helpers the block calls but never registers only
need the card's id in front.

The point is grep. A card's whole implementation answers a search for its id, and every handler of a
kind answers a search for its role. A test enforces it, and `ROLES` in `hooks/card_layout.py` is
where a genuinely new role gets added.

A brand new set module needs a line in `cards/__init__.py`. A test will tell you if you forget.

## Checking your work

```bash
pixi run test          # the suite
pre-commit run --all   # includes the card-id check
```

Write the test with the card. The suite is how a mass refactor knows it did not drop your
registration. Every implemented card is covered, and that is not an accident.

The bots are separate. A new ability is invisible to them until someone writes a hint for it, and
[Bots and policies](../design/systems/bots-and-policies.md) covers why that is the safe default.
