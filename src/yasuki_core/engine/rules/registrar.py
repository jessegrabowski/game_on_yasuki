from collections.abc import Callable, Iterator, Mapping
from typing import Any

# Every per-card registry built here, in creation order. What validation reads instead of a
# hand-kept list: a registry that exists is a registry that is checked, so a new one cannot escape
# by nobody remembering to add it.
CARD_REGISTRIES: list["FlagRegistry | HandlerRegistry[Any]"] = []


class FlagRegistry:
    """The printed ids a rule applies to, with no handler attached.

    Parameters
    ----------
    label : str
        How validation names this registry when it reports an unknown card id.
    complaint : str
        What a repeated registration says after the id, worded for the card author who reads it in
        pre-commit output.
    """

    def __init__(self, label: str, complaint: str) -> None:
        self.label = label
        self.complaint = complaint
        self._ids: set[str] = set()
        CARD_REGISTRIES.append(self)

    def make_register(self) -> Callable[[str], None]:
        """The function that records a card in this registry, to bind to a ``register_`` name.

        ``may_not_lobby("moto_chen")`` and ``favor_payer("moto_chen")`` are the same
        expression to the eye, but the second needs a function under it and does nothing without
        one. The prefix is what tells a reader which is which.
        """

        def register(printed_id: str) -> None:
            if printed_id in self._ids:
                raise ValueError(f"{printed_id} {self.complaint}")
            self._ids.add(printed_id)

        return register

    def discard(self, printed_id: str) -> None:
        """Forget ``printed_id``, or do nothing when it was never recorded."""
        self._ids.discard(printed_id)

    def __contains__(self, printed_id: object) -> bool:
        return printed_id in self._ids

    def __iter__(self) -> Iterator[str]:
        return iter(self._ids)

    def __len__(self) -> int:
        return len(self._ids)


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

    def __init__(self, label: str, complaint: str) -> None:
        self.label = label
        self.complaint = complaint
        self._handlers: dict[str, T] = {}
        CARD_REGISTRIES.append(self)

    def make_decorator(self) -> Callable[[str], Callable[[T], T]]:
        """The decorator that records a card's handler here, to bind to a bare-noun name.

        A card module then reads ``@gold_handler("jade_works")``. Raise ValueError on a second
        handler for one id: assignment would let it shadow the first with no trace, and by the time
        anything reads the registry only the survivor is there.
        """

        def decorate(printed_id: str) -> Callable[[T], T]:
            def register(handler: T) -> T:
                if printed_id in self._handlers:
                    raise ValueError(f"{printed_id} {self.complaint}")
                self._handlers[printed_id] = handler
                return handler

            return register

        return decorate

    def pop(self, printed_id: str, default: T | None = None) -> T | None:
        """Forget ``printed_id`` and return its handler, or ``default`` when it has none."""
        return self._handlers.pop(printed_id, default)

    def __getitem__(self, printed_id: str) -> T:
        return self._handlers[printed_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)
