"""
Tests for SDK module event instrumentation.

Verifies that each instrumented SDK module emits the correct events
via event_emitter.emit_background() when its methods are called.

All tests mock the event_emitter so no Redis is required.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_emitter():
    from types import SimpleNamespace

    with patch("omniclaw.events.ProxyEventEmitter.emit_background") as mock_method:
        yield SimpleNamespace(emit_background=mock_method)


# ─── Guard Event Tests ─────────────────────────────────────────────────


class TestBudgetGuardEvents:
    """Verify BudgetGuard emits budget-related events."""

    async def test_check_pass_emits_guard_evaluated(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.budget import BudgetGuard

        storage = AsyncMock()
        storage.get.return_value = None
        guard = BudgetGuard(daily_limit=Decimal("1000"), storage=storage)

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True
        calls = [
            c
            for c in mock_emitter.emit_background.call_args_list
            if c[0][0] == "payment.guard_evaluated"
        ]
        assert len(calls) >= 1
        assert calls[-1][1]["payload"]["result"] == "PASS"

    async def test_check_exceed_emits_budget_exceeded(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.budget import BudgetGuard
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        guard = BudgetGuard(daily_limit=Decimal("1000"), storage=storage)
        spent_context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("990"), purpose="seed"
        )
        token = await guard.reserve(spent_context)
        await guard.commit(token)

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("50"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is False

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "guard.budget_exceeded" in event_types
        assert "payment.guard_evaluated" in event_types

    async def test_check_approaching_emits_warning(self, mock_emitter):
        """Budget > 80% but still allowed should emit approaching warning."""
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.budget import BudgetGuard
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        guard = BudgetGuard(daily_limit=Decimal("1000"), storage=storage)
        spent_context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("850"), purpose="seed"
        )
        token = await guard.reserve(spent_context)
        await guard.commit(token)

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "guard.budget_limit_approaching" in event_types


class TestRateLimitGuardEvents:
    """Verify RateLimitGuard emits rate limit events."""

    async def test_check_pass_emits_evaluated(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.rate_limit import RateLimitGuard

        storage = AsyncMock()
        storage.get.return_value = None

        guard = RateLimitGuard(max_per_minute=10)
        guard.bind_storage(storage)

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "payment.guard_evaluated" in event_types

    async def test_check_exceeded_emits_hit(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.rate_limit import RateLimitGuard

        storage = AsyncMock()
        # Count at the limit
        storage.get.return_value = {"value": "10"}

        guard = RateLimitGuard(max_per_minute=10)
        guard.bind_storage(storage)

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is False
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "guard.rate_limit_hit" in event_types
        assert "payment.guard_evaluated" in event_types


class TestRecipientGuardEvents:
    """Verify RecipientGuard emits recipient events."""

    async def test_whitelist_blocked_emits_recipient_blocked(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.recipient import RecipientGuard

        guard = RecipientGuard(mode="whitelist", addresses=["0xAllowed1", "0xAllowed2"])

        context = PaymentContext(
            wallet_id="w-1", recipient="0xBlocked", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is False
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "guard.recipient_blocked" in event_types

    async def test_whitelist_pass_emits_evaluated(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.recipient import RecipientGuard

        guard = RecipientGuard(mode="whitelist", addresses=["0xAllowed1"])

        context = PaymentContext(
            wallet_id="w-1", recipient="0xAllowed1", amount=Decimal("10"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "payment.guard_evaluated" in event_types


class TestSingleTxGuardEvents:
    """Verify SingleTxGuard emits guard evaluated events."""

    async def test_check_pass_emits_evaluated(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.single_tx import SingleTxGuard

        guard = SingleTxGuard(max_amount=Decimal("100"))

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("50"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "payment.guard_evaluated" in event_types

    async def test_check_exceed_emits_fail(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.single_tx import SingleTxGuard

        guard = SingleTxGuard(max_amount=Decimal("100"))

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("200"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is False
        calls = [
            c
            for c in mock_emitter.emit_background.call_args_list
            if c[0][0] == "payment.guard_evaluated"
        ]
        assert calls[-1][1]["payload"]["result"] == "FAIL"


class TestConfirmGuardEvents:
    """Verify ConfirmGuard emits confirm events."""

    async def test_no_confirmation_needed_emits_pass(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.confirm import ConfirmGuard

        guard = ConfirmGuard(threshold=Decimal("100"))

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("50"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is True
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "payment.guard_evaluated" in event_types

    async def test_confirmation_needed_emits_required(self, mock_emitter):
        from omniclaw.guards.base import PaymentContext
        from omniclaw.guards.confirm import ConfirmGuard

        guard = ConfirmGuard(threshold=Decimal("100"))

        context = PaymentContext(
            wallet_id="w-1", recipient="0xabc", amount=Decimal("200"), purpose="test"
        )
        result = await guard.check(context)

        assert result.allowed is False
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "guard.confirm_required" in event_types
        assert "payment.guard_evaluated" in event_types


# ─── Intent Service Event Tests ────────────────────────────────────────


class TestIntentServiceEvents:
    """Verify PaymentIntentService emits intent lifecycle events."""

    async def test_create_emits_intent_created(self, mock_emitter):
        from omniclaw.intents.service import PaymentIntentService

        storage = AsyncMock()
        service = PaymentIntentService(storage)

        await service.create(wallet_id="w-1", recipient="0xabc", amount=Decimal("50"))

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "intent.created" in event_types

        # Check wallet_id is passed correctly
        create_call = [
            c for c in mock_emitter.emit_background.call_args_list if c[0][0] == "intent.created"
        ][0]
        assert create_call[0][1] == "w-1"

    async def test_cancel_emits_intent_canceled(self, mock_emitter):
        from omniclaw.intents.service import PaymentIntentService

        storage = AsyncMock()
        service = PaymentIntentService(storage)

        # Create an intent first
        intent = await service.create(wallet_id="w-1", recipient="0xabc", amount=Decimal("50"))

        # Mock _load to return the save data as a proper dict
        # The cancel() method calls get() which calls _load()
        storage.get.return_value = intent.to_dict()

        await service.cancel(intent.id, reason="test cancellation")

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "intent.canceled" in event_types


# ─── Circuit Breaker Event Tests ───────────────────────────────────────


class TestCircuitBreakerEvents:
    """Verify CircuitBreaker emits circuit state change events."""

    async def test_trip_emits_circuit_opened(self, mock_emitter):
        from omniclaw.resilience.circuit import CircuitBreaker

        storage = AsyncMock()
        storage.get.return_value = None
        cb = CircuitBreaker("test-service", storage)

        await cb.trip()

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "circuit.opened" in event_types

        trip_call = [
            c for c in mock_emitter.emit_background.call_args_list if c[0][0] == "circuit.opened"
        ][0]
        assert trip_call[1]["severity"] == "critical"

    async def test_close_emits_circuit_closed(self, mock_emitter):
        from omniclaw.resilience.circuit import CircuitBreaker

        storage = AsyncMock()
        storage.get.return_value = None
        cb = CircuitBreaker("test-service", storage)

        await cb.close()

        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "circuit.closed" in event_types


# ─── Fund Lock Event Tests ─────────────────────────────────────────────


class TestFundLockEvents:
    """Verify FundLockService emits lock events."""

    async def test_acquire_success_emits_fund_locked(self, mock_emitter):
        from omniclaw.ledger.lock import FundLockService

        storage = AsyncMock()
        storage.acquire_lock.return_value = "lock-token-abc12345678901234567890"

        lock_service = FundLockService(storage)
        token = await lock_service.acquire("w-1", Decimal("100"))

        assert token is not None
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "payment.fund_locked" in event_types

    async def test_acquire_timeout_emits_lock_timeout(self, mock_emitter):
        from omniclaw.ledger.lock import FundLockService

        storage = AsyncMock()
        storage.acquire_lock.return_value = None

        lock_service = FundLockService(storage)
        token = await lock_service.acquire("w-1", Decimal("100"), retry_count=0)

        assert token is None
        event_types = [c[0][0] for c in mock_emitter.emit_background.call_args_list]
        assert "system.lock_timeout" in event_types

        timeout_call = [
            c
            for c in mock_emitter.emit_background.call_args_list
            if c[0][0] == "system.lock_timeout"
        ][0]
        assert timeout_call[1]["severity"] == "error"
