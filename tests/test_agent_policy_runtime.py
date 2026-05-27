from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from omniclaw.agent.auth import AuthenticatedAgent
from omniclaw.agent.models import CanPayResponse, CreateIntentRequest, PayRequest, SimulateRequest
from omniclaw.agent.policy import PolicyManager, RuntimeWalletState, WalletManager
from omniclaw.agent.routes import can_pay, confirm_intent, create_intent, get_address, pay, simulate
from omniclaw.core.types import Network, PaymentMethod


def _write_policy(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


class _FakeClient:
    def __init__(self, *, circle_transfer: bool = True, eoa_address: str = "0x" + "2" * 40):
        self.config = SimpleNamespace(
            enable_circle_transfer=circle_transfer,
            enable_gateway=False,
            enable_x402_exact=True,
            network=Network.BASE_SEPOLIA,
        )
        self._config = self.config
        self._nano_adapter = SimpleNamespace(address=eoa_address)
        self._guard_manager = SimpleNamespace(clear_wallet_guards=AsyncMock())
        self.create_agent_wallet = AsyncMock(
            return_value=SimpleNamespace(
                id="circle-wallet-1",
                address="0x" + "1" * 40,
            )
        )
        self.get_wallet = AsyncMock(
            return_value=SimpleNamespace(
                id="circle-wallet-1",
                address="0x" + "1" * 40,
                blockchain=Network.BASE_SEPOLIA.value,
            )
        )
        self.add_budget_guard = AsyncMock()
        self.add_single_tx_guard = AsyncMock()
        self.add_rate_limit_guard = AsyncMock()
        self.add_recipient_guard = AsyncMock()
        self.add_confirm_guard = AsyncMock()


@pytest.mark.asyncio
async def test_wallet_initialization_writes_runtime_state_not_policy(tmp_path):
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "wallet-state.json"
    _write_policy(
        policy_path,
        {
            "version": "2.0",
            "tokens": {
                "active-token": {"wallet_alias": "primary", "active": True},
                "inactive-token": {"wallet_alias": "primary", "active": False},
            },
            "wallets": {
                "primary": {
                    "name": "Primary",
                    "limits": {"per_tx_max": "10.00"},
                    "recipients": {"mode": "allow_all"},
                    "rails": {
                        "circle_transfer": True,
                        "x402": True,
                    },
                }
            },
        },
    )

    manager = PolicyManager(str(policy_path))
    await manager.load()
    state = RuntimeWalletState(path=str(state_path), policy_path=str(policy_path))
    wallet_manager = WalletManager(manager, _FakeClient(), runtime_state=state)

    result = await wallet_manager.initialize_wallets()

    assert result == {"active-token": "circle-wallet-1"}
    policy_after = json.loads(policy_path.read_text())
    assert "wallet_id" not in policy_after["wallets"]["primary"]
    assert "address" not in policy_after["wallets"]["primary"]

    state_after = json.loads(state_path.read_text())
    assert state_after["wallets"]["primary"]["circle_wallet_id"] == "circle-wallet-1"
    assert state_after["wallets"]["primary"]["gateway_eoa_address"] == "0x" + "2" * 40
    assert manager.get_wallet_id_for_token("inactive-token") is None


@pytest.mark.asyncio
async def test_x402_only_wallet_initialization_does_not_require_circle_wallet(tmp_path):
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "wallet-state.json"
    _write_policy(
        policy_path,
        {
            "version": "2.0",
            "tokens": {"agent-token": {"wallet_alias": "primary", "active": True}},
            "wallets": {
                "primary": {
                    "name": "Primary",
                    "rails": {
                        "circle_transfer": False,
                        "x402": True,
                    },
                }
            },
        },
    )

    manager = PolicyManager(str(policy_path))
    await manager.load()
    client = _FakeClient(circle_transfer=False, eoa_address="0x" + "3" * 40)
    wallet_manager = WalletManager(
        manager,
        client,
        runtime_state=RuntimeWalletState(path=str(state_path), policy_path=str(policy_path)),
    )

    result = await wallet_manager.initialize_wallets()

    assert result == {"agent-token": "x402:primary"}
    client.create_agent_wallet.assert_not_called()
    state_after = json.loads(state_path.read_text())
    assert state_after["wallets"]["primary"]["wallet_id"] == "x402:primary"
    assert state_after["wallets"]["primary"]["circle_wallet_id"] is None
    assert state_after["wallets"]["primary"]["circle_wallet_address"] is None
    assert state_after["wallets"]["primary"]["gateway_eoa_address"] == "0x" + "3" * 40


@pytest.mark.asyncio
async def test_old_gateway_and_exact_policy_rails_are_rejected(tmp_path):
    policy_path = tmp_path / "policy.json"
    _write_policy(
        policy_path,
        {
            "version": "2.0",
            "tokens": {"agent-token": {"wallet_alias": "primary", "active": True}},
            "wallets": {
                "primary": {
                    "name": "Primary",
                    "rails": {
                        "circle_transfer": True,
                        "gateway": False,
                        "x402_exact": True,
                    },
                }
            },
        },
    )

    manager = PolicyManager(str(policy_path))
    with pytest.raises(ValueError, match="Invalid policy.json"):
        await manager.load()


@pytest.mark.asyncio
async def test_policy_domain_whitelist_uses_hostname_boundaries(tmp_path):
    policy_path = tmp_path / "policy.json"
    _write_policy(
        policy_path,
        {
            "version": "2.0",
            "tokens": {"agent-token": {"wallet_alias": "primary", "active": True}},
            "wallets": {"primary": {"name": "Primary"}},
            "recipients": {
                "mode": "whitelist",
                "domains": ["api.service.com"],
            },
        },
    )

    manager = PolicyManager(str(policy_path))
    await manager.load()

    assert manager.is_valid_recipient("https://api.service.com/pay")
    assert manager.is_valid_recipient("https://paid.api.service.com/pay")
    assert not manager.is_valid_recipient("https://api.service.com.evil/pay")


@pytest.mark.asyncio
async def test_empty_recipient_whitelist_blocks_all(tmp_path):
    policy_path = tmp_path / "policy.json"
    _write_policy(
        policy_path,
        {
            "version": "2.0",
            "tokens": {"agent-token": {"wallet_alias": "primary", "active": True}},
            "wallets": {"primary": {"name": "Primary"}},
            "recipients": {"mode": "whitelist"},
        },
    )

    manager = PolicyManager(str(policy_path))
    await manager.load()

    assert not manager.is_valid_recipient("https://api.service.com/pay")
    assert not manager.is_valid_recipient("0x" + "4" * 40)


@pytest.mark.asyncio
async def test_missing_policy_requires_agent_token_for_default_creation(tmp_path):
    policy_path = tmp_path / "missing.json"
    manager = PolicyManager(str(policy_path))

    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="AGENT_TOKEN"):
        await manager.load()


@pytest.mark.asyncio
async def test_x402_only_address_uses_private_key_signer(monkeypatch):
    private_key = "0x" + "1" * 64
    client = SimpleNamespace(
        _nano_adapter=None,
        config=SimpleNamespace(nanopayments_private_key=private_key),
    )
    policy = SimpleNamespace(
        get_wallet_config=lambda wallet_id: {"alias": "primary", "gateway_eoa_address": None}
    )
    wallet_mgr = SimpleNamespace(get_wallet_address=AsyncMock(return_value=None))
    agent = AuthenticatedAgent(token="agent-token", wallet_id="eoa:primary")

    response = await get_address(
        agent=agent,
        policy_mgr=policy,
        wallet_mgr=wallet_mgr,
        client=client,
    )

    assert response.wallet_id == "eoa:primary"
    assert response.eoa_address is not None
    assert response.address == response.eoa_address


@pytest.mark.asyncio
async def test_direct_pay_rejects_when_circle_transfer_disabled_by_server():
    request = PayRequest(
        recipient="0x" + "4" * 40,
        amount="1.00",
    )
    agent = AuthenticatedAgent(token="agent-token", wallet_id="wallet-1")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: True,
        check_limits=lambda amount, wallet_id: (True, None),
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=False, enable_gateway=False, enable_x402_exact=True
        ),
        pay=AsyncMock(),
    )

    with pytest.raises(HTTPException, match="Circle transfer rail is disabled by server config"):
        await pay(
            request=request,
            agent=agent,
            wallet_mgr=SimpleNamespace(),
            policy_mgr=policy,
            client=client,
        )
    client.pay.assert_not_called()


@pytest.mark.asyncio
async def test_can_pay_rejects_direct_recipient_when_circle_transfer_disabled():
    agent = AuthenticatedAgent(token="agent-token", wallet_id="wallet-1")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: rail != "circle_transfer",
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=True, enable_gateway=False, enable_x402_exact=True
        )
    )

    result = await can_pay(
        recipient="0x" + "4" * 40,
        agent=agent,
        policy_mgr=policy,
        client=client,
    )

    assert isinstance(result, CanPayResponse)
    assert result.can_pay is False
    assert result.reason == "Circle transfer rail is disabled by policy"


@pytest.mark.asyncio
async def test_simulate_url_uses_selected_x402_amount_without_wallet_lookup(monkeypatch):
    selected_kind = SimpleNamespace(
        get_amount_usdc=lambda: Decimal("0.25"),
    )
    x402_adapter = SimpleNamespace(
        simulate=AsyncMock(
            return_value={
                "would_succeed": True,
                "method": PaymentMethod.X402,
                "recipient": "https://seller.example/compute",
                "amount": "0.25",
            }
        )
    )

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": True,
            "selected_kind": selected_kind,
            "selected_route": "x402",
            "x402_adapter": x402_adapter,
        }

    monkeypatch.setattr("omniclaw.agent.routes._inspect_x402_target", fake_inspect_x402_target)
    agent = AuthenticatedAgent(token="agent-token", wallet_id="eoa:primary")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: rail == "x402",
        check_limits=lambda amount, wallet_id: (True, None),
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=False, enable_gateway=False, enable_x402_exact=True
        )
    )

    result = await simulate(
        request=SimulateRequest(recipient="https://seller.example/compute", amount="0.50"),
        agent=agent,
        policy_mgr=policy,
        client=client,
    )

    assert result.would_succeed is True
    assert result.route == "x402"
    x402_adapter.simulate.assert_awaited_once()


@pytest.mark.asyncio
async def test_pay_rejects_nanopayment_when_gateway_execution_disabled(monkeypatch):
    selected_kind = SimpleNamespace(get_amount_usdc=lambda: Decimal("0.25"))

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": True,
            "selected_kind": selected_kind,
            "selected_route": "nanopayment",
        }

    monkeypatch.setattr("omniclaw.agent.routes._inspect_x402_target", fake_inspect_x402_target)
    agent = AuthenticatedAgent(token="agent-token", wallet_id="wallet-1")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: rail == "x402",
        check_limits=lambda amount, wallet_id: (True, None),
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=False, enable_gateway=False, enable_x402_exact=True
        ),
        pay=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await pay(
            request=PayRequest(recipient="https://seller.example/compute", amount="0.50"),
            agent=agent,
            wallet_mgr=SimpleNamespace(),
            policy_mgr=policy,
            client=client,
        )

    assert exc_info.value.status_code == 400
    assert "Gateway nanopayment" in exc_info.value.detail
    client.pay.assert_not_called()


@pytest.mark.asyncio
async def test_can_pay_rejects_unsupported_x402_route(monkeypatch):
    selected_kind = SimpleNamespace(get_amount_usdc=lambda: Decimal("0.25"))

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": True,
            "selected_kind": selected_kind,
            "selected_route": "future-route",
        }

    monkeypatch.setattr("omniclaw.agent.routes._inspect_x402_target", fake_inspect_x402_target)
    agent = AuthenticatedAgent(token="agent-token", wallet_id="wallet-1")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: rail == "x402",
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=False, enable_gateway=True, enable_x402_exact=True
        )
    )

    result = await can_pay(
        recipient="https://seller.example/compute",
        agent=agent,
        policy_mgr=policy,
        client=client,
    )

    assert result.can_pay is False
    assert result.reason == "Seller selected an unsupported x402 payment route"


@pytest.mark.asyncio
async def test_create_intent_rejects_url_when_x402_disabled():
    request = CreateIntentRequest(recipient="https://seller.example/compute", amount="0.25")
    agent = AuthenticatedAgent(token="agent-token", wallet_id="wallet-1")
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        is_rail_enabled=lambda rail, wallet_id: False,
        check_limits=lambda amount, wallet_id: (True, None),
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=True, enable_gateway=True, enable_x402_exact=True
        ),
        create_payment_intent=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_intent(
            request=request,
            agent=agent,
            policy_mgr=policy,
            client=client,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "x402 rail is disabled by policy"
    client.create_payment_intent.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_url_intent_rejects_missing_route_metadata():
    intent = SimpleNamespace(
        id="intent-1",
        wallet_id="eoa:primary",
        recipient="https://seller.example/compute",
        amount=Decimal("0.25"),
        metadata={},
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            enable_circle_transfer=False, enable_gateway=False, enable_x402_exact=True
        ),
        get_payment_intent=AsyncMock(return_value=intent),
        confirm_payment_intent=AsyncMock(),
    )
    policy = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        check_limits=lambda amount, wallet_id: (True, None),
        is_rail_enabled=lambda rail, wallet_id: True,
    )
    agent = AuthenticatedAgent(token="agent-token", wallet_id="eoa:primary")

    with pytest.raises(HTTPException) as exc_info:
        await confirm_intent(
            intent_id="intent-1",
            agent=agent,
            policy_mgr=policy,
            client=client,
        )

    assert exc_info.value.status_code == 400
    assert "authorized route is missing" in exc_info.value.detail
    client.confirm_payment_intent.assert_not_called()
