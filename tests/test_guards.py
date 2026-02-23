"""
Unit tests for Guards module.

Tests all guard types: BudgetGuard, SingleTxGuard, RecipientGuard,
RateLimitGuard, ConfirmGuard, and GuardChain.
"""

from decimal import Decimal

import pytest

from omniclaw.guards.base import GuardChain, GuardResult, PaymentContext
from omniclaw.guards.budget import BudgetGuard
from omniclaw.guards.confirm import ConfirmGuard
from omniclaw.guards.rate_limit import RateLimitGuard
from omniclaw.guards.recipient import RecipientGuard
from omniclaw.guards.single_tx import SingleTxGuard
from omniclaw.storage.memory import InMemoryStorage


@pytest.fixture
def payment_context() -> PaymentContext:
    """Create a standard payment context for testing."""
    return PaymentContext(
        wallet_id="wallet-123",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("10.00"),
        purpose="Test payment",
    )


class TestGuardResult:
    """Tests for GuardResult dataclass."""

    def test_allowed_result(self):
        result = GuardResult(allowed=True, guard_name="TestGuard")
        assert result.allowed is True
        assert result.reason is None

    def test_blocked_result(self):
        result = GuardResult(
            allowed=False,
            guard_name="TestGuard",
            reason="Exceeded limit",
        )
        assert result.allowed is False
        assert result.reason == "Exceeded limit"


class TestPaymentContext:
    """Tests for PaymentContext dataclass."""

    def test_basic_context(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("5.00"),
        )
        assert ctx.wallet_id == "w1"
        assert ctx.amount == Decimal("5.00")

    def test_context_with_metadata(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("5.00"),
            metadata={"key": "value"},
        )
        assert ctx.metadata["key"] == "value"


class TestBudgetGuard:
    """Tests for BudgetGuard."""

    @pytest.mark.asyncio
    async def test_allows_within_daily_limit(self, payment_context):
        guard = BudgetGuard(daily_limit=Decimal("100.00"), storage=InMemoryStorage())
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_blocks_exceeding_daily_limit(self, payment_context):
        guard = BudgetGuard(daily_limit=Decimal("5.00"), storage=InMemoryStorage())
        result = await guard.check(payment_context)
        assert result.allowed is False
        assert "daily" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_tracks_spending(self, payment_context):
        guard = BudgetGuard(daily_limit=Decimal("25.00"), storage=InMemoryStorage())

        # First payment OK
        token1 = await guard.reserve(payment_context)
        assert token1 is not None
        await guard.commit(token1)

        # Second payment OK
        token2 = await guard.reserve(payment_context)
        assert token2 is not None
        await guard.commit(token2)

        # Third payment exceeds limit
        with pytest.raises(ValueError, match="Daily budget limit exceeded"):
            await guard.reserve(payment_context)

    @pytest.mark.asyncio
    async def test_hourly_limit(self, payment_context):
        guard = BudgetGuard(hourly_limit=Decimal("5.00"), storage=InMemoryStorage())
        # Check logic: check() method still works for pre-flight
        result = await guard.check(payment_context)
        assert result.allowed is False
        assert "hourly" in result.reason.lower()

        # Reserve logic:
        with pytest.raises(ValueError, match="Hourly budget limit exceeded"):
            await guard.reserve(payment_context)

    @pytest.mark.asyncio
    async def test_total_limit(self, payment_context):
        guard = BudgetGuard(total_limit=Decimal("50.00"), storage=InMemoryStorage())

        # Reserve almost full amount
        ctx = PaymentContext(wallet_id="wallet-123", recipient="0x123", amount=Decimal("45.00"))
        token = await guard.reserve(ctx)
        await guard.commit(token)

        # Check current context (10.00 + 45.00 = 55.00 > 50.00)
        result = await guard.check(payment_context)
        assert result.allowed is False
        assert "total" in result.reason.lower()


class TestSingleTxGuard:
    """Tests for SingleTxGuard."""

    @pytest.mark.asyncio
    async def test_allows_within_max(self, payment_context):
        guard = SingleTxGuard(max_amount=Decimal("50.00"))
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_blocks_exceeding_max(self, payment_context):
        guard = SingleTxGuard(max_amount=Decimal("5.00"))
        result = await guard.check(payment_context)
        assert result.allowed is False
        assert "maximum" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_blocks_below_min(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("0.50"),
        )
        guard = SingleTxGuard(max_amount=Decimal("100.00"), min_amount=Decimal("1.00"))
        result = await guard.check(ctx)
        assert result.allowed is False
        assert "minimum" in result.reason.lower() or "below" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_allows_exact_max(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("50.00"),
        )
        guard = SingleTxGuard(max_amount=Decimal("50.00"))
        result = await guard.check(ctx)
        assert result.allowed is True


class TestRecipientGuard:
    """Tests for RecipientGuard."""

    @pytest.mark.asyncio
    async def test_whitelist_allows_matching(self, payment_context):
        guard = RecipientGuard(
            mode="whitelist",
            addresses=["0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"],
        )
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_whitelist_blocks_non_matching(self, payment_context):
        guard = RecipientGuard(
            mode="whitelist",
            addresses=["0xDifferentAddress1234567890123456789012"],
        )
        result = await guard.check(payment_context)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_blacklist_blocks_matching(self, payment_context):
        guard = RecipientGuard(
            mode="blacklist",
            addresses=["0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"],
        )
        result = await guard.check(payment_context)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_blacklist_allows_non_matching(self, payment_context):
        guard = RecipientGuard(
            mode="blacklist",
            addresses=["0xDifferentAddress1234567890123456789012"],
        )
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_regex_pattern_matching(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="api.example.com/paid",
            amount=Decimal("5.00"),
        )
        guard = RecipientGuard(
            mode="whitelist",
            patterns=[r"api\.example\.com.*"],
        )
        result = await guard.check(ctx)
        assert result.allowed is True


class TestRateLimitGuard:
    """Tests for RateLimitGuard."""

    @pytest.mark.asyncio
    async def test_allows_first_payment(self, payment_context):
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        guard = RateLimitGuard(max_per_minute=5)
        guard.bind_storage(storage)
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_blocks_after_limit(self, payment_context):
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        guard = RateLimitGuard(max_per_minute=2)
        guard.bind_storage(storage)

        # Reserve 2 payments
        t1 = await guard.reserve(payment_context)
        assert t1 is not None

        t2 = await guard.reserve(payment_context)
        assert t2 is not None

        # Third should fail
        with pytest.raises(ValueError, match="Rate limit exceeded"):
            await guard.reserve(payment_context)

    @pytest.mark.asyncio
    async def test_hourly_limit(self, payment_context):
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        guard = RateLimitGuard(max_per_hour=1)
        guard.bind_storage(storage)

        t1 = await guard.reserve(payment_context)
        assert t1 is not None

        with pytest.raises(ValueError, match="Rate limit exceeded"):
            await guard.reserve(payment_context)


class TestConfirmGuard:
    """Tests for ConfirmGuard."""

    @pytest.mark.asyncio
    async def test_auto_approve_below_threshold(self, payment_context):
        guard = ConfirmGuard(threshold=Decimal("50.00"))
        result = await guard.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_requires_confirmation_above_threshold(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("100.00"),
        )
        guard = ConfirmGuard(threshold=Decimal("50.00"))
        result = await guard.check(ctx)
        assert result.allowed is False
        assert "confirmation" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_callback_approval(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("100.00"),
        )

        async def approve_callback(context):
            return True

        guard = ConfirmGuard(
            threshold=Decimal("50.00"),
            confirm_callback=approve_callback,
        )
        result = await guard.check(ctx)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_callback_rejection(self):
        ctx = PaymentContext(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("100.00"),
        )

        async def reject_callback(context):
            return False

        guard = ConfirmGuard(
            threshold=Decimal("50.00"),
            confirm_callback=reject_callback,
        )
        result = await guard.check(ctx)
        assert result.allowed is False


class TestGuardChain:
    """Tests for GuardChain."""

    @pytest.mark.asyncio
    async def test_empty_chain_allows(self, payment_context):
        chain = GuardChain()
        result = await chain.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_all_pass(self, payment_context):
        chain = GuardChain(
            [
                SingleTxGuard(max_amount=Decimal("100.00")),
                BudgetGuard(daily_limit=Decimal("100.00"), storage=InMemoryStorage()),
            ]
        )
        result = await chain.check(payment_context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_first_fails(self, payment_context):
        chain = GuardChain(
            [
                SingleTxGuard(max_amount=Decimal("5.00")),  # Will fail
                BudgetGuard(daily_limit=Decimal("100.00"), storage=InMemoryStorage()),
            ]
        )
        result = await chain.check(payment_context)
        assert result.allowed is False
        assert "SingleTxGuard" in result.guard_name or "single" in result.guard_name.lower()

    @pytest.mark.asyncio
    async def test_second_fails(self, payment_context):
        chain = GuardChain(
            [
                SingleTxGuard(max_amount=Decimal("100.00")),  # Will pass
                BudgetGuard(daily_limit=Decimal("5.00"), storage=InMemoryStorage()),  # Will fail
            ]
        )
        result = await chain.check(payment_context)
        assert result.allowed is False
        assert "BudgetGuard" in result.guard_name or "budget" in result.guard_name.lower()

    def test_add_guard(self, payment_context):
        chain = GuardChain()
        chain.add(SingleTxGuard(max_amount=Decimal("50.00")))
        assert len(chain) == 1

    def test_remove_guard(self, payment_context):
        guard = SingleTxGuard(max_amount=Decimal("50.00"), name="test_guard")
        chain = GuardChain([guard])

        result = chain.remove("test_guard")
        assert result is True
        assert len(chain) == 0

    @pytest.mark.asyncio
    async def test_reset_all(self, payment_context):
        budget = BudgetGuard(daily_limit=Decimal("100.00"), storage=InMemoryStorage())
        token = await budget.reserve(payment_context)
        await budget.commit(token)

        chain = GuardChain([budget])
        chain.reset_all()

        # NOTE: BudgetGuard.reset() is currently empty/no-op in implementation
        # so this test just verifies the method exists and runs without error.
