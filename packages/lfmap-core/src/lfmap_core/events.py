"""EventBus Protocol, the Event model and the in-process bus (ADR-006, ADR-021; docs/specs/events.md)."""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from lfmap_core.errors import ToolError
from lfmap_core.events_payload import decode_payload, encode_payload
from lfmap_core.events_retry import after_failure, backoff_seconds, describe_error
from lfmap_core.topics import topic_matches, validate_pattern, validate_topic

_SOURCE = re.compile(r"[a-z][a-z0-9-]{0,63}", re.ASCII)
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    topic: str
    source: str
    payload: dict[str, Any]
    created_at: AwareDatetime
    correlation_id: str
    causation_id: str | None = None
    attempt: int = Field(default=1, ge=1)


class DeadLetter(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: Event
    subscription: str
    attempts: int
    error: str


Handler = Callable[[Event], None]


@runtime_checkable
class EventBus(Protocol):
    def publish(
        self, topic: str, payload: dict[str, Any] | None = None, *, source: str, causation: Event | None = None
    ) -> Event: ...

    def subscribe(self, name: str, pattern: str, handler: Handler) -> None: ...

    def unsubscribe(self, name: str) -> None: ...

    def drain(self, *, max_events: int = 1000) -> int: ...

    def dead_letters(self, subscription: str | None = None) -> list[DeadLetter]: ...

    def retry(self, event_id: str, subscription: str) -> None: ...

    def close(self) -> None: ...


def new_event(
    topic: str, payload: dict[str, Any] | None, source: str, causation: Event | None, now: float
) -> tuple[Event, str]:
    """A checked Event and its encoded payload, shared by every implementation."""
    validate_topic(topic)
    if not (isinstance(source, str) and (source == "core" or _SOURCE.fullmatch(source))):
        raise ToolError("invalid_input", "Invalid event source", {"source": repr(source)})
    text = encode_payload({} if payload is None else payload)
    event_id = uuid.uuid4().hex
    event = Event(
        id=event_id,
        topic=topic,
        source=source,
        payload=decode_payload(text),
        created_at=datetime.fromtimestamp(now, UTC),
        correlation_id=causation.correlation_id if causation else event_id,
        causation_id=causation.id if causation else None,
    )
    return event, text


def check_subscription(name: str, pattern: str) -> None:
    if not (isinstance(name, str) and _NAME.fullmatch(name)):
        raise ToolError("invalid_input", "Invalid subscription name", {"name": repr(name)})
    validate_pattern(pattern)


def check_max_attempts(max_attempts: int) -> None:
    if type(max_attempts) is not int or max_attempts < 1:
        raise ToolError("invalid_input", "max_attempts must be an int >= 1", {"max_attempts": repr(max_attempts)})


def check_max_events(max_events: int) -> None:
    if type(max_events) is not int or max_events < 1:
        raise ToolError("invalid_input", "max_events must be an int >= 1", {"max_events": repr(max_events)})


@dataclass
class _Delivery:
    event: Event
    subscription: str
    attempts: int = 0
    available_at: float = 0.0
    dead: bool = False
    error: str = ""


class InProcessBus:
    """Events live in memory and run in the process that drains them; lost when the process ends."""

    def __init__(self, *, clock: Callable[[], float] = time.time, max_attempts: int = 5) -> None:
        check_max_attempts(max_attempts)
        self._clock = clock
        self._max_attempts = max_attempts
        self._subscriptions: dict[str, tuple[str, Handler]] = {}
        self._deliveries: list[_Delivery] = []
        self._closed = False

    def _open(self) -> None:
        if self._closed:
            raise ToolError("backend_unavailable", "The event bus is closed")

    def publish(
        self, topic: str, payload: dict[str, Any] | None = None, *, source: str, causation: Event | None = None
    ) -> Event:
        self._open()
        now = self._clock()
        event, _ = new_event(topic, payload, source, causation, now)
        for name, (pattern, _handler) in self._subscriptions.items():
            if topic_matches(pattern, topic):
                self._deliveries.append(_Delivery(event, name, available_at=now))
        return event

    def subscribe(self, name: str, pattern: str, handler: Handler) -> None:
        self._open()
        check_subscription(name, pattern)
        current = self._subscriptions.get(name)
        if current and current[0] != pattern:
            raise ToolError("invalid_input", "Subscription exists with another pattern", {"name": name})
        self._subscriptions[name] = (pattern, handler)

    def unsubscribe(self, name: str) -> None:
        self._open()
        if self._subscriptions.pop(name, None) is None:
            raise ToolError("not_found", "Unknown subscription", {"name": name})
        self._deliveries = [d for d in self._deliveries if d.subscription != name]

    def _next(self) -> _Delivery | None:
        now = self._clock()
        return next((d for d in self._deliveries if not d.dead and d.available_at <= now), None)

    def drain(self, *, max_events: int = 1000) -> int:
        self._open()
        check_max_events(max_events)
        count = 0
        while count < max_events and (delivery := self._next()) is not None:
            delivery.attempts += 1
            count += 1
            handler = self._subscriptions[delivery.subscription][1]
            try:
                handler(delivery.event.model_copy(update={"attempt": delivery.attempts}))
            except Exception as error:  # noqa: BLE001 - a handler failure never stops the drain
                if after_failure(error, delivery.attempts, self._max_attempts) == "dead":
                    delivery.dead, delivery.error = True, describe_error(error)
                else:
                    delivery.available_at = self._clock() + backoff_seconds(delivery.attempts)
                continue
            if delivery in self._deliveries:  # the handler may have unsubscribed
                self._deliveries.remove(delivery)
        return count

    def dead_letters(self, subscription: str | None = None) -> list[DeadLetter]:
        return [
            DeadLetter(event=d.event, subscription=d.subscription, attempts=d.attempts, error=d.error)
            for d in self._deliveries
            if d.dead and subscription in (None, d.subscription)
        ]

    def retry(self, event_id: str, subscription: str) -> None:
        self._open()
        for delivery in self._deliveries:
            if delivery.dead and delivery.event.id == event_id and delivery.subscription == subscription:
                delivery.dead, delivery.attempts, delivery.error = False, 0, ""
                delivery.available_at = self._clock()
                return
        raise ToolError("not_found", "No such dead letter", {"event": event_id, "subscription": subscription})

    def close(self) -> None:
        self._closed = True
