# Registration and the audit

Every per-card handler is keyed by printed id, and nothing else binds a card to its code. A typo
therefore produces a card that registers happily and never fires.

## The registry

`engine/registrar.py` builds them, and a registry knows how to complain about itself:

```python
class HandlerRegistry[T](Mapping[str, T]):
    """The per-card handlers a rule consults, keyed by printed id.

    Parameters
    ----------
    label : str
        How validation names this registry when it reports an unknown card id.
    complaint : str
        What a repeated registration says after the id, worded for the card author who reads it in
        pre-commit output.
    """
```

`label` and `complaint` exist for the author reading pre-commit output, which is the only place
either one appears. A new registry passes both and needs nothing else.

Registering the same id twice raises. That is deliberate, since two handlers for one card is
always a mistake and the second would otherwise replace the first in import order.

## The audit

Every registry built through `registrar` appends itself to `CARD_REGISTRIES`, so the audit finds a
new one without being told:

```python
derived = {registry.label: frozenset(registry) for registry in CARD_REGISTRIES}
return {
    **derived,
    "abilities": frozenset(registry._ABILITIES),
    "invest abilities": frozenset(registry._INVEST),
    "triggers": frozenset(
        card_id for by_card in triggers._TRIGGERS.values() for card_id in by_card
    ),
}
```

Three are listed by hand because they are not built that way. Two keep bespoke registration rules,
and triggers are keyed by event before card.

One registry is left out on purpose:

```text
``CHOICE_RESOLVERS`` is absent by design. It keys on the *kind* of a pending choice rather than
on a card — ``modest_farm_straighten`` and ``sincerity_seed`` name steps in a sequence, not
cards — so validating it against the card index would report failures that are not defects.
```

## Where it runs

`registration-audit` is a pre-commit hook. It needs the project environment, which the CI
pre-commit job does not have, so `tests/yasuki_core/install/test_registration_audit.py` is what
guards it in CI. Both check the same thing, and a card id that matches no real card fails.

The hook reports the registry, the id, and the nearest real id, which is usually enough to see the
typo without opening the card data.

## Where a card plugs in

A card plugs in the moment its id matches a real one.
[Adding a card](../../contributing/adding_a_card.md) is where to start, and
[The card data](../../contributing/the_card_data.md) covers how an id is derived from a printed
title.
