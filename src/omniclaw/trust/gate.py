"""
Trust Gate — ERC-8004 Trust Evaluation Orchestrator.

The central component that sits between the PaymentRouter and the Guard Chain.
Orchestrates: cache → identity resolve → metadata fetch → reputation aggregate
→ policy evaluate → audit emit.

On-chain reads are performed via ERC8004Provider (JSON-RPC eth_call), which
connects to ETH mainnet, Base Sepolia, etc. via configurable RPC URLs.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.logging import get_logger
from omniclaw.identity.resolver import IdentityResolver
from omniclaw.identity.types import (
    AgentIdentity,
    FeedbackSignal,
    ReputationScore,
    TrustCheckResult,
    TrustPolicy,
    TrustVerdict,
)
from omniclaw.trust.cache import TrustCache
from omniclaw.trust.policy import PolicyEngine
from omniclaw.trust.provider import ERC8004Provider
from omniclaw.trust.scoring import ReputationAggregator

if TYPE_CHECKING:
    from omniclaw.core.types import Network
    from omniclaw.storage.base import StorageBackend
    from omniclaw.wallet.service import WalletService

logger = get_logger("trust.gate")


class TrustGate:
    """
    Trust Gate — Orchestrates ERC-8004 trust evaluation.

    Called by client.pay() before the guard chain. Evaluates the recipient
    against the operator's TrustPolicy, using cached on-chain identity
    and reputation data.

    On-chain connectivity:
    - Uses ERC8004Provider for lightweight JSON-RPC reads (eth_call)
    - Configurable RPC URLs via env vars or constructor
    - Defaults: ETH mainnet via llamarpc.com, Base Sepolia via sepolia.base.org
    """

    def __init__(
        self,
        storage: StorageBackend,
        wallet_service: WalletService | None = None,
        network: Network | None = None,
        default_policy: TrustPolicy | None = None,
        rpc_url: str | None = None,
        provider: ERC8004Provider | None = None,
    ) -> None:
        """
        Initialize the Trust Gate.

        Args:
            storage: Storage backend for caching
            wallet_service: For Circle SDK fallback (deprecated for reads)
            network: Default network for ERC-8004 lookups
            default_policy: Default trust policy if none is set per-wallet
            rpc_url: RPC endpoint URL (or set OMNICLAW_RPC_URL env var).
                     Supports comma-separated for fallback.
            provider: Pre-configured ERC8004Provider (overrides rpc_url)
        """
        # Initialize the on-chain provider
        self._provider = provider or ERC8004Provider(rpc_url=rpc_url)

        self._resolver = IdentityResolver(
            provider=self._provider,
            wallet_service=wallet_service,
        )
        self._cache = TrustCache(storage)
        self._policy_engine = PolicyEngine()
        self._scoring = ReputationAggregator()
        self._network = network
        self._default_policy = default_policy or TrustPolicy.permissive()
        self._wallet_policies: dict[str, TrustPolicy] = {}
        self._storage = storage

    # ─── Public API ──────────────────────────────────────────────────

    async def evaluate(
        self,
        recipient_address: str,
        amount: Decimal,
        wallet_id: str | None = None,
        network: Network | None = None,
        policy: TrustPolicy | None = None,
    ) -> TrustCheckResult:
        """
        Run the full trust evaluation pipeline.

        Steps (from spec §2.3):
        1. Check trust cache
        2. Resolve identity from ERC-8004 Identity Registry (via eth_call)
        3. Fetch agent metadata from agentURI (HTTPS/IPFS/data)
        4. Aggregate reputation from ERC-8004 Reputation Registry
        5. Evaluate policy
        6. Emit audit event

        Args:
            recipient_address: Recipient wallet address
            amount: Payment amount
            wallet_id: Sender's wallet ID (for per-wallet policies)
            network: Network to query (defaults to configured network)
            policy: Override policy (otherwise uses wallet or default)

        Returns:
            TrustCheckResult with verdict, scores, and metadata
        """
        start_time = time.monotonic()
        network = network or self._network
        policy = policy or self._get_policy(wallet_id)
        chain_id = self._network_to_key(network)

        identity: AgentIdentity | None = None
        reputation: ReputationScore | None = None
        cache_hit = False

        try:
            # Step 1+2+3: Resolve identity (with caching)
            identity, cache_hit = await self._resolve_with_cache(
                recipient_address, chain_id, network,
            )

            # Step 4: Aggregate reputation (if identity found)
            if identity:
                reputation = await self._aggregate_reputation(
                    identity, chain_id, network,
                )

        except Exception as e:
            logger.error(f"Trust Gate error during lookup: {e}")
            # Apply unresolvable_action from policy
            elapsed = int((time.monotonic() - start_time) * 1000)
            return TrustCheckResult(
                identity_found=False,
                policy_id=policy.policy_id,
                verdict=policy.unresolvable_action,
                block_reason=f"REGISTRY_ERROR:{e}",
                flags=["registry_error"],
                check_latency_ms=elapsed,
                checked_at=datetime.now(timezone.utc),
            )

        # Step 5: Evaluate policy
        result = self._policy_engine.evaluate(
            identity=identity,
            reputation=reputation,
            amount=amount,
            recipient_address=recipient_address,
            policy=policy,
        )

        # Step 6: Finalize result metadata
        elapsed = int((time.monotonic() - start_time) * 1000)
        result.check_latency_ms = elapsed
        result.cache_hit = cache_hit
        result.checked_at = datetime.now(timezone.utc)

        logger.info(
            f"Trust Gate: {result.verdict.value} for {recipient_address} "
            f"(WTS: {result.wts}, latency: {elapsed}ms, cache: {cache_hit})"
        )

        return result

    async def lookup(
        self,
        address: str,
        network: Network | None = None,
    ) -> TrustCheckResult:
        """
        Standalone trust lookup (without paying).

        Equivalent to client.trust.lookup(address) in the SDK.
        """
        return await self.evaluate(
            recipient_address=address,
            amount=Decimal("0"),
            network=network,
            policy=self._default_policy,
        )

    def set_policy(self, wallet_id: str, policy: TrustPolicy) -> None:
        """Set a trust policy for a specific wallet."""
        self._wallet_policies[wallet_id] = policy

    def get_policy(self, wallet_id: str | None = None) -> TrustPolicy:
        """Get the active policy for a wallet."""
        return self._get_policy(wallet_id)

    async def close(self) -> None:
        """Clean up resources (HTTP clients, etc.)."""
        await self._resolver.close()
        await self._provider.close()

    # ─── Internal Pipeline ───────────────────────────────────────────

    async def _resolve_with_cache(
        self,
        address: str,
        chain_id: str,
        network: Network | None,
    ) -> tuple[AgentIdentity | None, bool]:
        """Resolve identity with cache layer."""

        # Check cache
        cached_data, cache_hit = await self._cache.get_or_fetch(
            chain_id=chain_id,
            address=address,
            data_type="identity",
            fetch_fn=lambda: self._fetch_identity(address, network),
        )

        if cache_hit and cached_data:
            # Reconstruct AgentIdentity from cached dict
            identity = self._deserialize_identity(cached_data)
            return identity, True

        if cached_data:
            identity = self._deserialize_identity(cached_data)
            return identity, False

        return None, False

    async def _fetch_identity(
        self,
        address: str,
        network: Network | None,
    ) -> dict[str, Any] | None:
        """Fetch identity from chain and serialize for caching."""
        if not network:
            return None

        identity = await self._resolver.resolve_by_address(address, network)
        if identity is None:
            return None

        return self._serialize_identity(identity)

    async def _aggregate_reputation(
        self,
        identity: AgentIdentity,
        chain_id: str,
        network: Network | None,
    ) -> ReputationScore:
        """Aggregate reputation with caching."""
        # Check cache for reputation data
        cached_rep, _ = await self._cache.get_or_fetch(
            chain_id=chain_id,
            address=identity.wallet_address,
            data_type="reputation",
            fetch_fn=lambda: self._fetch_reputation_signals(identity, network),
        )

        signals: list[FeedbackSignal] = []
        if cached_rep and "signals" in cached_rep:
            for s in cached_rep["signals"]:
                signals.append(FeedbackSignal(
                    agent_id=s["agent_id"],
                    client_address=s["client_address"],
                    feedback_index=s["feedback_index"],
                    value=s["value"],
                    value_decimals=s["value_decimals"],
                    tag1=s.get("tag1", ""),
                    tag2=s.get("tag2", ""),
                    is_revoked=s.get("is_revoked", False),
                ))

        return self._scoring.compute_wts(
            signals=signals,
            agent_owner_address=identity.wallet_address,
        )

    async def _fetch_reputation_signals(
        self,
        identity: AgentIdentity,
        network: Network | None,
    ) -> dict[str, Any] | None:
        """Fetch reputation signals from chain via ERC8004Provider."""
        if not network:
            return {"signals": []}

        network_key = self._network_to_key(network)

        try:
            # Use the provider to fetch real on-chain feedback
            raw_signals = await self._provider.get_all_feedback(
                identity.agent_id, network_key,
            )
            return {
                "signals": [
                    {
                        "agent_id": s.agent_id,
                        "client_address": s.client_address,
                        "feedback_index": s.feedback_index,
                        "value": s.value,
                        "value_decimals": s.value_decimals,
                        "tag1": s.tag1,
                        "tag2": s.tag2,
                        "is_revoked": s.is_revoked,
                    }
                    for s in raw_signals
                ]
            }
        except Exception as e:
            logger.warning(f"Failed to fetch reputation for agent {identity.agent_id}: {e}")
            return {"signals": []}

    # ─── Serialization ───────────────────────────────────────────────

    @staticmethod
    def _serialize_identity(identity: AgentIdentity) -> dict[str, Any]:
        """Serialize AgentIdentity for cache storage."""
        return {
            "agent_id": identity.agent_id,
            "wallet_address": identity.wallet_address,
            "agent_wallet": identity.agent_wallet,
            "agent_registry": identity.agent_registry,
            "registration_type": identity.registration_type,
            "name": identity.name,
            "description": identity.description,
            "organization": identity.organization,
            "services": [
                {"name": s.name, "endpoint": s.endpoint, "version": s.version}
                for s in identity.services
            ],
            "x402_support": identity.x402_support,
            "active": identity.active,
            "supported_trust": identity.supported_trust,
            "attestations": identity.attestations,
        }

    @staticmethod
    def _deserialize_identity(data: dict[str, Any]) -> AgentIdentity:
        """Deserialize AgentIdentity from cache."""
        from omniclaw.identity.types import AgentService

        return AgentIdentity(
            agent_id=data["agent_id"],
            wallet_address=data["wallet_address"],
            agent_wallet=data.get("agent_wallet"),
            agent_registry=data.get("agent_registry"),
            registration_type=data.get("registration_type"),
            name=data.get("name"),
            description=data.get("description"),
            organization=data.get("organization"),
            services=[
                AgentService(
                    name=s["name"],
                    endpoint=s["endpoint"],
                    version=s.get("version"),
                )
                for s in data.get("services", [])
            ],
            x402_support=data.get("x402_support", False),
            active=data.get("active", True),
            supported_trust=data.get("supported_trust", []),
            attestations=data.get("attestations", []),
        )

    @staticmethod
    def _network_to_key(network: Any) -> str:
        """Convert network to string key."""
        if network is None:
            return "unknown"
        if hasattr(network, "value"):
            return str(network.value)
        return str(network).upper()

    def _get_policy(self, wallet_id: str | None = None) -> TrustPolicy:
        """Get the appropriate policy for a wallet."""
        if wallet_id and wallet_id in self._wallet_policies:
            return self._wallet_policies[wallet_id]
        return self._default_policy


__all__ = ["TrustGate"]
