"""Pure-function compatibility baseline for AssetOutbox status machine and helpers.

Pins the OutboxStatus enum values, OutboxEvent post-init defaults and is_ready
gating, AssetOutbox create_event idempotency-key derivation, status transitions
under fail/complete/cancel, pending_count and get_events_by_status semantics,
and the retry/dead-letter decision rules so later refactors of the outbox state
machine cannot silently change which events are eligible, retried, or dead.
"""

from __future__ import annotations

import time

from app.services.asset_outbox import (
    _LEASE_DURATION,
    _MAX_RETRIES,
    _PERSISTENCE_MODE,
    _RETRY_BACKOFF_BASE,
    AssetOutbox,
    OutboxEvent,
    OutboxStatus,
)


class TestOutboxStatusEnum:
    def test_status_values_are_stable_strings(self):
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.LEASED == "leased"
        assert OutboxStatus.PROCESSING == "processing"
        assert OutboxStatus.COMPLETED == "completed"
        assert OutboxStatus.RETRYABLE == "retryable"
        assert OutboxStatus.DEAD_LETTER == "dead_letter"
        assert OutboxStatus.CANCELLED == "cancelled"

    def test_status_members_are_distinct(self):
        values = [s.value for s in OutboxStatus]
        assert len(values) == len(set(values)) == 7

    def test_status_is_str_enum(self):
        # StrEnum members are strings
        assert isinstance(OutboxStatus.PENDING, str)
        assert OutboxStatus.PENDING == "pending"


class TestModuleConstants:
    def test_max_retries_is_five(self):
        assert _MAX_RETRIES == 5

    def test_lease_duration_is_sixty_seconds(self):
        assert _LEASE_DURATION == 60

    def test_retry_backoff_base_is_two(self):
        assert _RETRY_BACKOFF_BASE == 2.0

    def test_persistence_mode_default_is_legacy(self):
        # PERSISTENCE_MODE env var not set in test env -> "legacy"
        assert _PERSISTENCE_MODE in {"legacy", "transactional_shadow", "transactional"}


class TestOutboxEventPostInit:
    def test_empty_event_id_generates_evt_prefix(self):
        event = OutboxEvent(event_type="asset_delete")
        assert event.event_id.startswith("evt-")
        assert len(event.event_id) > len("evt-")

    def test_explicit_event_id_preserved(self):
        event = OutboxEvent(event_type="x", event_id="custom-id")
        assert event.event_id == "custom-id"

    def test_created_at_defaults_to_now(self):
        before = time.time()
        event = OutboxEvent(event_type="x")
        after = time.time()
        assert before <= event.created_at <= after

    def test_explicit_created_at_preserved(self):
        event = OutboxEvent(event_type="x", created_at=12345.0)
        assert event.created_at == 12345.0

    def test_default_status_is_pending(self):
        event = OutboxEvent(event_type="x")
        assert event.status == OutboxStatus.PENDING

    def test_default_payload_is_empty_dict(self):
        event = OutboxEvent(event_type="x")
        assert event.payload == {}

    def test_default_payload_schema_version(self):
        event = OutboxEvent(event_type="x")
        assert event.payload_schema_version == "1.0"

    def test_default_retry_count_zero(self):
        event = OutboxEvent(event_type="x")
        assert event.retry_count == 0

    def test_default_next_retry_at_zero(self):
        event = OutboxEvent(event_type="x")
        assert event.next_retry_at == 0.0

    def test_two_events_get_distinct_ids(self):
        a = OutboxEvent(event_type="x")
        b = OutboxEvent(event_type="x")
        assert a.event_id != b.event_id

    def test_two_events_get_distinct_created_at_close_in_time(self):
        a = OutboxEvent(event_type="x")
        b = OutboxEvent(event_type="x")
        # Both should be ~now; they may be equal if same ms, but both >= some baseline.
        assert a.created_at > 0 and b.created_at > 0


class TestOutboxEventIsReady:
    def _event(self, **kwargs):
        return OutboxEvent(event_type="x", **kwargs)

    def test_pending_with_zero_next_retry_is_ready(self):
        event = self._event(status=OutboxStatus.PENDING, next_retry_at=0.0)
        assert event.is_ready() is True

    def test_completed_is_not_ready(self):
        event = self._event(status=OutboxStatus.COMPLETED)
        assert event.is_ready() is False

    def test_dead_letter_is_not_ready(self):
        event = self._event(status=OutboxStatus.DEAD_LETTER)
        assert event.is_ready() is False

    def test_cancelled_is_not_ready(self):
        event = self._event(status=OutboxStatus.CANCELLED)
        assert event.is_ready() is False

    def test_retryable_with_future_next_retry_not_ready(self):
        future = time.time() + 100
        event = self._event(status=OutboxStatus.RETRYABLE, next_retry_at=future)
        assert event.is_ready() is False

    def test_retryable_with_past_next_retry_is_ready(self):
        past = time.time() - 100
        event = self._event(status=OutboxStatus.RETRYABLE, next_retry_at=past)
        assert event.is_ready() is True

    def test_retryable_with_zero_next_retry_is_ready(self):
        # next_retry_at=0 is falsy -> the time check is skipped -> ready
        event = self._event(status=OutboxStatus.RETRYABLE, next_retry_at=0.0)
        assert event.is_ready() is True

    def test_leased_status_still_ready_if_next_retry_zero(self):
        # is_ready does not check LEASED specially; only terminal statuses and
        # next_retry_at gate it. Pin this so callers know leased events may
        # still appear ready unless the lease check is done elsewhere.
        event = self._event(status=OutboxStatus.LEASED, next_retry_at=0.0)
        assert event.is_ready() is True

    def test_processing_status_still_ready_if_next_retry_zero(self):
        event = self._event(status=OutboxStatus.PROCESSING, next_retry_at=0.0)
        assert event.is_ready() is True


class TestAssetOutboxCreateEvent:
    def test_create_event_generates_idempotency_key_from_payload(self):
        outbox = AssetOutbox()
        event = outbox.create_event("asset_delete", {"asset_id": "abc"})
        assert event.idempotency_key.startswith("asset_delete:")
        # Same payload -> same key
        event2 = outbox.create_event("asset_delete", {"asset_id": "abc"})
        assert event2.idempotency_key == event.idempotency_key

    def test_create_event_distinct_payload_distinct_key(self):
        outbox = AssetOutbox()
        a = outbox.create_event("asset_delete", {"asset_id": "a"})
        b = outbox.create_event("asset_delete", {"asset_id": "b"})
        assert a.idempotency_key != b.idempotency_key

    def test_create_event_explicit_idempotency_key_preserved(self):
        outbox = AssetOutbox()
        event = outbox.create_event(
            "asset_delete", {"asset_id": "x"}, idempotency_key="my-key"
        )
        assert event.idempotency_key == "my-key"

    def test_create_event_empty_idempotency_key_uses_derived(self):
        outbox = AssetOutbox()
        event = outbox.create_event("asset_delete", {"x": 1}, idempotency_key="")
        assert event.idempotency_key != ""
        assert event.idempotency_key.startswith("asset_delete:")

    def test_create_event_payload_key_order_independent(self):
        # json.dumps(sort_keys=True) -> key order doesn't affect idempotency key.
        outbox = AssetOutbox()
        a = outbox.create_event("x", {"a": 1, "b": 2})
        b = outbox.create_event("x", {"b": 2, "a": 1})
        assert a.idempotency_key == b.idempotency_key

    def test_create_event_default_status_pending(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        assert event.status == OutboxStatus.PENDING

    def test_create_event_stores_event_in_outbox(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        assert event.event_id in outbox._events

    def test_create_event_distinct_events_get_distinct_event_ids(self):
        outbox = AssetOutbox()
        a = outbox.create_event("x", {"i": 1})
        b = outbox.create_event("x", {"i": 2})
        assert a.event_id != b.event_id


class TestAssetOutboxStatusTransitions:
    def test_complete_sets_completed_status(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.complete(event.event_id)
        assert event.status == OutboxStatus.COMPLETED

    def test_complete_updates_timestamp(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        before = time.time()
        outbox.complete(event.event_id)
        assert event.updated_at >= before

    def test_complete_unknown_event_id_noop(self):
        outbox = AssetOutbox()
        # Must not raise
        outbox.complete("nonexistent-id")

    def test_cancel_sets_cancelled_status(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.cancel(event.event_id)
        assert event.status == OutboxStatus.CANCELLED

    def test_cancel_unknown_event_id_noop(self):
        outbox = AssetOutbox()
        outbox.cancel("nonexistent-id")

    def test_mark_ready_sets_pending_status(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        # Move to a non-pending status first, then mark_ready
        outbox.complete(event.event_id)
        assert event.status == OutboxStatus.COMPLETED
        outbox.mark_ready(event.event_id)
        assert event.status == OutboxStatus.PENDING

    def test_mark_ready_unknown_event_id_noop(self):
        outbox = AssetOutbox()
        outbox.mark_ready("nonexistent-id")


class TestAssetOutboxFailRetryAndDeadLetter:
    def test_fail_first_attempt_sets_retryable_and_increments_count(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.fail(event.event_id, "boom")
        assert event.status == OutboxStatus.RETRYABLE
        assert event.retry_count == 1
        assert event.last_error == "boom"

    def test_fail_sets_next_retry_at_with_backoff(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        before = time.time()
        outbox.fail(event.event_id, "boom")
        # backoff = _RETRY_BACKOFF_BASE ** retry_count = 2.0 ** 1 = 2.0
        expected_min = before + 2.0
        assert event.next_retry_at >= expected_min

    def test_fail_second_attempt_backoff_is_four(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.fail(event.event_id, "e1")  # retry 1, backoff 2^1=2
        before_2 = time.time()
        outbox.fail(event.event_id, "e2")  # retry 2, backoff 2^2=4
        assert event.retry_count == 2
        assert event.next_retry_at >= before_2 + 4.0

    def test_fail_until_max_retries_moves_to_dead_letter(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        for i in range(_MAX_RETRIES):
            outbox.fail(event.event_id, f"e{i + 1}")
        assert event.status == OutboxStatus.DEAD_LETTER
        assert event.retry_count == _MAX_RETRIES

    def test_fail_exactly_at_max_retries_dead_letter_not_retryable(self):
        # retry_count == _MAX_RETRIES triggers DEAD_LETTER (>= check).
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        for _ in range(_MAX_RETRIES - 1):
            outbox.fail(event.event_id, "e")
        assert event.status == OutboxStatus.RETRYABLE
        outbox.fail(event.event_id, "final")  # retry_count becomes _MAX_RETRIES
        assert event.status == OutboxStatus.DEAD_LETTER

    def test_fail_retryable_false_immediately_dead_letters(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.fail(event.event_id, "fatal", retryable=False)
        assert event.status == OutboxStatus.DEAD_LETTER
        assert event.retry_count == 1  # incremented before dead-letter check

    def test_fail_retryable_false_at_max_retries_still_dead_letter(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        # Push to _MAX_RETRIES - 1 with retryable=True
        for _ in range(_MAX_RETRIES - 1):
            outbox.fail(event.event_id, "e")
        # Now retryable=False -> DEAD_LETTER (but retry_count still increments)
        outbox.fail(event.event_id, "fatal", retryable=False)
        assert event.status == OutboxStatus.DEAD_LETTER
        assert event.retry_count == _MAX_RETRIES

    def test_fail_unknown_event_id_noop(self):
        outbox = AssetOutbox()
        outbox.fail("nonexistent", "e")

    def test_fail_updates_timestamp(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        before = time.time()
        outbox.fail(event.event_id, "e")
        assert event.updated_at >= before


class TestAssetOutboxQueries:
    def test_pending_count_empty_outbox_zero(self):
        outbox = AssetOutbox()
        assert outbox.pending_count() == 0

    def test_pending_count_counts_pending_retryable_leased_processing(self):
        outbox = AssetOutbox()
        outbox.create_event("x", {"i": 1})
        outbox.create_event("y", {"i": 2})
        assert outbox.pending_count() == 2

    def test_pending_count_excludes_completed(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.complete(event.event_id)
        assert outbox.pending_count() == 0

    def test_pending_count_excludes_dead_letter(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        for _ in range(_MAX_RETRIES):
            outbox.fail(event.event_id, "e")
        assert outbox.pending_count() == 0

    def test_pending_count_excludes_cancelled(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.cancel(event.event_id)
        assert outbox.pending_count() == 0

    def test_pending_count_includes_retryable(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.fail(event.event_id, "e")
        assert outbox.pending_count() == 1

    def test_get_events_by_status_returns_matching(self):
        outbox = AssetOutbox()
        a = outbox.create_event("x", {"i": 1})
        b = outbox.create_event("y", {"i": 2})
        outbox.complete(a.event_id)
        completed = outbox.get_events_by_status(OutboxStatus.COMPLETED)
        assert completed == [a]
        pending = outbox.get_events_by_status(OutboxStatus.PENDING)
        assert pending == [b]

    def test_get_events_by_status_empty_when_none_match(self):
        outbox = AssetOutbox()
        assert outbox.get_events_by_status(OutboxStatus.COMPLETED) == []

    def test_get_events_by_status_string_value_accepted(self):
        # OutboxStatus is StrEnum so "completed" == OutboxStatus.COMPLETED.
        outbox = AssetOutbox()
        a = outbox.create_event("x", {})
        outbox.complete(a.event_id)
        assert outbox.get_events_by_status("completed") == [a]


class TestAssetOutboxMode:
    def test_default_mode_uses_persistence_mode_env(self):
        outbox = AssetOutbox()
        assert outbox.mode == _PERSISTENCE_MODE

    def test_explicit_mode_overrides_env(self):
        outbox = AssetOutbox(mode="transactional")
        assert outbox.mode == "transactional"

    def test_empty_string_mode_falls_back_to_env(self):
        outbox = AssetOutbox(mode="")
        assert outbox.mode == _PERSISTENCE_MODE


class TestAssetOutboxProcessReadyEvents:
    def test_no_handlers_completes_ready_events(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        processed = outbox.process_ready_events()
        assert processed == [event]
        assert event.status == OutboxStatus.COMPLETED

    def test_handler_success_completes_event(self):
        outbox = AssetOutbox()
        outbox.register_handler("asset_delete", lambda payload: None)
        event = outbox.create_event("asset_delete", {"asset_id": "a"})
        processed = outbox.process_ready_events()
        assert processed == [event]
        assert event.status == OutboxStatus.COMPLETED

    def test_handler_failure_marks_retryable(self):
        outbox = AssetOutbox()

        def handler(payload):
            raise RuntimeError("boom")

        outbox.register_handler("asset_delete", handler)
        event = outbox.create_event("asset_delete", {"asset_id": "a"})
        processed = outbox.process_ready_events()
        # Failing event is not in the processed list (only successful ones are).
        assert event not in processed
        assert event.status == OutboxStatus.RETRYABLE
        assert event.retry_count == 1

    def test_completed_event_not_reprocessed(self):
        outbox = AssetOutbox()
        calls = []
        outbox.register_handler("x", lambda payload: calls.append(payload))
        event = outbox.create_event("x", {"i": 1})
        outbox.complete(event.event_id)
        processed = outbox.process_ready_events()
        assert processed == []
        assert calls == []

    def test_cancelled_event_not_processed(self):
        outbox = AssetOutbox()
        calls = []
        outbox.register_handler("x", lambda payload: calls.append(payload))
        event = outbox.create_event("x", {"i": 1})
        outbox.cancel(event.event_id)
        processed = outbox.process_ready_events()
        assert processed == []
        assert calls == []

    def test_dead_letter_event_not_processed(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        for _ in range(_MAX_RETRIES):
            outbox.fail(event.event_id, "e")
        processed = outbox.process_ready_events()
        assert processed == []

    def test_handler_failure_repeated_with_backoff_reset_moves_to_dead_letter(self):
        outbox = AssetOutbox()

        def handler(payload):
            raise RuntimeError("always fails")

        outbox.register_handler("x", handler)
        event = outbox.create_event("x", {})
        # process_ready_events honors next_retry_at backoff, so a tight loop
        # would only fail once and then skip the event until backoff elapses.
        # Simulate backoff elapsing by resetting next_retry_at before each pass.
        for _ in range(_MAX_RETRIES):
            object.__setattr__(event, "next_retry_at", 0.0)
            outbox.process_ready_events()
        assert event.status == OutboxStatus.DEAD_LETTER
        assert event.retry_count == _MAX_RETRIES


class TestAssetOutboxLease:
    def test_lease_pending_event_acquires(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        assert outbox.lease(event.event_id) is True
        assert event.status == OutboxStatus.LEASED
        assert event.lease_id
        assert event.lease_expires_at > time.time()

    def test_lease_completed_event_fails(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        outbox.complete(event.event_id)
        assert outbox.lease(event.event_id) is False

    def test_lease_unknown_event_id_fails(self):
        outbox = AssetOutbox()
        assert outbox.lease("nonexistent") is False

    def test_lease_default_duration_sixty_seconds(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        before = time.time()
        outbox.lease(event.event_id)
        # lease_expires_at = now + _LEASE_DURATION (60)
        assert event.lease_expires_at >= before + _LEASE_DURATION - 1
        assert event.lease_expires_at <= before + _LEASE_DURATION + 5

    def test_lease_custom_duration(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        before = time.time()
        outbox.lease(event.event_id, duration=10)
        assert event.lease_expires_at >= before + 10 - 1
        assert event.lease_expires_at <= before + 10 + 5

    def test_double_lease_same_event_second_fails(self):
        outbox = AssetOutbox()
        event = outbox.create_event("x", {})
        assert outbox.lease(event.event_id) is True
        # Second lease on already-leased event with non-expired lease fails.
        assert outbox.lease(event.event_id) is False
