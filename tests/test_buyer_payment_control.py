from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.exceptions import PaymentOutcomeUnknownError, ValidationError
from omniclaw.core.types import (
    Network,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    SimulationResult,
)
from omniclaw.ledger.ledger import LedgerEntryStatus


@pytest.fixture
def client() -> OmniClaw:
    c = OmniClaw(
        network=Network.ARC_TESTNET,
        circle_api_key="mock_key",
        entity_secret="mock_secret",
    )
    c._wallet_service = MagicMock()
    c._wallet_service.get_usdc_balance_amount.return_value = Decimal("500.00")
    c._wallet_service.get_wallet.return_value = MagicMock(blockchain="ETH-SEPOLIA")

    async def mock_simulate(*args, **kwargs):
        return SimulationResult(would_succeed=True, route=PaymentMethod.TRANSFER)

    async def mock_pay(*args, **kwargs):
        return PaymentResult(
            success=True,
            transaction_id="tx-ok",
            blockchain_tx="0xok",
            amount=kwargs["amount"],
            recipient=kwargs["recipient"],
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.COMPLETED,
        )

    c._router.simulate = mock_simulate
    c._router.pay = mock_pay
    return c


@pytest.mark.asyncio
async def test_intent_authorization_binding_rejects_amount_tampering(client):
    intent = await client.intent.create(
        wallet_id="wallet-bind",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="25.00",
        purpose="bound execution",
    )

    assert intent.metadata["authorization_digest"]
    assert intent.metadata["authorization_snapshot"]["amount"] == "25"

    await client._storage.update(
        client._intent_service.COLLECTION,
        f"intent:{intent.id}",
        {"amount": "26.00"},
    )

    with pytest.raises(ValidationError, match="authorization binding mismatch"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_intent_authorization_binding_rejects_execution_parameter_tampering(client):
    intent = await client.intent.create(
        wallet_id="wallet-param-bind",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="12.00",
        purpose="bound route",
        preferred_url_route="transfer",
    )

    tampered_metadata = dict(intent.metadata)
    tampered_metadata["execution_params"] = {"preferred_url_route": "x402"}
    await client._storage.update(
        client._intent_service.COLLECTION,
        f"intent:{intent.id}",
        {"metadata": tampered_metadata},
    )

    with pytest.raises(ValidationError, match="authorization binding mismatch"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_intent_confirmation_rejects_changed_policy_snapshot(client):
    intent = await client.intent.create(
        wallet_id="wallet-policy-bind",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="12.00",
        purpose="policy bound",
    )

    await client._storage.save(
        "guard_registrations",
        "wallet:wallet-policy-bind",
        {"guards": [{"name": "daily_budget", "limit": "25.00"}]},
    )

    with pytest.raises(ValidationError, match="policy snapshot changed"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_outcome_unknown_marks_intent_for_settlement_check_and_blocks_replay(client):
    async def unknown_pay(*args, **kwargs):
        raise PaymentOutcomeUnknownError(
            "payment submitted but final outcome is unknown",
            transaction_id="tx-unknown",
            blockchain_tx="0xmaybe",
            recipient=kwargs["recipient"],
            amount=kwargs["amount"],
        )

    client._router.pay = unknown_pay

    intent = await client.intent.create(
        wallet_id="wallet-unknown",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="10.00",
    )

    result = await client.intent.confirm(intent.id)

    assert result.status == PaymentStatus.OUTCOME_UNKNOWN
    updated = await client.intent.get(intent.id)
    assert updated.status == PaymentIntentStatus.REQUIRES_SETTLEMENT_CHECK

    reserved = await client._reservation.get_reserved_total("wallet-unknown")
    assert reserved == Decimal("10.00")

    with pytest.raises(ValidationError, match="cannot be confirmed"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_finalize_pending_settlement_resolves_linked_intent_and_reservation(client):
    async def unknown_pay(*args, **kwargs):
        raise PaymentOutcomeUnknownError(
            "payment submitted but final outcome is unknown",
            transaction_id="tx-finalize",
            blockchain_tx="0xmaybe",
            recipient=kwargs["recipient"],
            amount=kwargs["amount"],
        )

    client._router.pay = unknown_pay

    intent = await client.intent.create(
        wallet_id="wallet-finalize",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="10.00",
    )

    result = await client.intent.confirm(intent.id)
    assert result.status == PaymentStatus.OUTCOME_UNKNOWN

    [pending_entry] = await client.list_pending_settlements(wallet_id="wallet-finalize")
    finalized = await client.finalize_pending_settlement(
        pending_entry.id,
        settled=True,
        settlement_tx_hash="0xsettled",
    )

    assert finalized.status == LedgerEntryStatus.COMPLETED
    assert finalized.metadata["settlement_final"] is True

    updated = await client.intent.get(intent.id)
    assert updated.status == PaymentIntentStatus.SUCCEEDED

    reserved = await client._reservation.get_reserved_total("wallet-finalize")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_buyer_audit_trace_reconstructs_intent_authorization_chain(client):
    intent = await client.intent.create(
        wallet_id="wallet-audit",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="7.50",
        purpose="audit reconstruction",
        idempotency_key="audit-job-1",
    )

    await client.intent.confirm(intent.id)

    trace = await client.audit.trace(intent_id=intent.id)
    event_types = [event.event_type for event in trace]

    assert "intent.authorized" in event_types
    assert "intent.execution_started" in event_types
    assert "payment.requested" in event_types
    assert "execution.attempted" in event_types
    assert "payment.outcome_recorded" in event_types

    authorized = next(event for event in trace if event.event_type == "intent.authorized")
    assert authorized.payload["authorization_digest"] == intent.metadata["authorization_digest"]


@pytest.mark.asyncio
async def test_buyer_audit_trace_requires_selector_by_default(client):
    await client.intent.create(
        wallet_id="wallet-audit-guard",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="2.00",
        purpose="audit guard",
    )

    with pytest.raises(ValueError, match="selector is required"):
        await client.audit.trace()

    assert await client.audit.trace(allow_unfiltered=True)
