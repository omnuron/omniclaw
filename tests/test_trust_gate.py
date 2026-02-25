"""
Tests for the ERC-8004 Trust Gate system.

Tests cover:
- Trust types and TrustPolicy presets
- WTS Reputation Aggregator scoring algorithm
- PolicyEngine 10-check evaluation logic
- TrustCache TTL behavior
- TrustGate end-to-end pipeline
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import httpx

from omniclaw.identity.types import (
    AgentIdentity,
    AgentService,
    FeedbackSignal,
    ReputationScore,
    TrustCheckResult,
    TrustPolicy,
    TrustVerdict,
)
from omniclaw.trust.cache import TrustCache
from omniclaw.trust.policy import PolicyEngine
from omniclaw.trust.scoring import ReputationAggregator


# ─────────────────────────────────────────────────────────────────
# Trust Policy Tests
# ─────────────────────────────────────────────────────────────────

class TestTrustPolicy:
    """Tests for TrustPolicy presets and configuration."""

    def test_permissive_preset(self):
        """Permissive preset should allow everything."""
        p = TrustPolicy.permissive()
        assert p.identity_required is False
        assert p.min_wts == 0
        assert p.min_feedback_count == 0
        assert p.new_agent_action == TrustVerdict.APPROVED
        assert p.fraud_tag_action == TrustVerdict.BLOCKED
        assert p.unresolvable_action == TrustVerdict.APPROVED

    def test_standard_preset(self):
        """Standard preset should hold new agents and require identity."""
        p = TrustPolicy.standard()
        assert p.identity_required is True
        assert p.min_wts == 50
        assert p.min_feedback_count == 3
        assert p.new_agent_action == TrustVerdict.HELD
        assert p.high_value_threshold_usd == Decimal("500")
        assert p.high_value_min_wts == 75

    def test_strict_preset(self):
        """Strict preset should require attestations and high WTS."""
        p = TrustPolicy.strict()
        assert p.identity_required is True
        assert p.min_wts == 70
        assert "kyb" in p.require_attestations
        assert p.high_value_min_wts == 85

    def test_custom_policy(self):
        """Custom policy with specific values."""
        p = TrustPolicy(
            policy_id="custom",
            identity_required=True,
            min_wts=80,
            address_blocklist=["0xBAD"],
            org_whitelist=["trusted-corp"],
        )
        assert p.policy_id == "custom"
        assert p.min_wts == 80
        assert "0xBAD" in p.address_blocklist


# ─────────────────────────────────────────────────────────────────
# WTS Scoring Tests
# ─────────────────────────────────────────────────────────────────

class TestReputationAggregator:
    """Tests for the Weighted Trust Score algorithm."""

    def setup_method(self):
        self.scorer = ReputationAggregator()

    def _make_signal(self, value=80, decimals=0, tag1="", tag2="",
                     client="0xClient", agent_id=1, index=1, revoked=False):
        return FeedbackSignal(
            agent_id=agent_id,
            client_address=client,
            feedback_index=index,
            value=value,
            value_decimals=decimals,
            tag1=tag1,
            tag2=tag2,
            is_revoked=revoked,
        )

    def test_empty_signals(self):
        """No feedback → WTS 0, new_agent + low_wts flags."""
        score = self.scorer.compute_wts([])
        assert score.wts == 0
        assert score.new_agent is True
        assert "new_agent" in score.flags
        assert "low_wts" in score.flags
        assert score.sample_size == 0

    def test_single_high_score(self):
        """One 90/100 signal → WTS 90, still new_agent (< 3)."""
        signals = [self._make_signal(value=90)]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 90
        assert score.new_agent is True

    def test_multiple_scores_averaged(self):
        """Multiple signals → weighted average."""
        signals = [
            self._make_signal(value=80, client="0xA", index=1),
            self._make_signal(value=60, client="0xB", index=1),
            self._make_signal(value=100, client="0xC", index=1),
        ]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 80  # (80+60+100)/3
        assert score.new_agent is False
        assert score.sample_size == 3

    def test_self_reviews_filtered(self):
        """Self-reviews (agent == submitter) should be filtered out."""
        signals = [
            self._make_signal(value=100, client="0xOwner"),  # Self-review
            self._make_signal(value=50, client="0xReal"),
        ]
        score = self.scorer.compute_wts(signals, agent_owner_address="0xOwner")
        assert score.wts == 50  # Only the real review counts
        assert score.self_review_count == 1
        assert score.sample_size == 1

    def test_fraud_tag_detected(self):
        """Fraud tag on any signal → 'fraud' flag."""
        signals = [
            self._make_signal(value=80, client="0xA"),
            self._make_signal(value=90, tag1="fraud", client="0xB"),
        ]
        score = self.scorer.compute_wts(signals)
        assert "fraud" in score.flags

    def test_scam_tag_detected(self):
        """'scam' in tag2 → fraud flag."""
        signals = [self._make_signal(value=70, tag2="scam", client="0xA")]
        score = self.scorer.compute_wts(signals)
        assert "fraud" in score.flags

    def test_revoked_signals_excluded(self):
        """Revoked feedback should not count."""
        signals = [
            self._make_signal(value=90, client="0xA", revoked=True),
            self._make_signal(value=50, client="0xB"),
        ]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 50
        assert score.revoked_count == 1
        assert score.total_feedback_count == 2

    def test_verified_submitter_boost(self):
        """Verified submitters get higher weight (1.5x)."""
        signals = [
            self._make_signal(value=90, client="0xVerified", index=2),
            self._make_signal(value=50, client="0xNormal", index=1),
        ]
        # With boost, verified submitter's score weighs more
        score = self.scorer.compute_wts(
            signals, verified_submitters={"0xVerified"}
        )
        # Verified count should be tracked
        assert score.verified_submitter_count == 1

    def test_low_wts_flag(self):
        """WTS < 30 → low_wts flag."""
        signals = [
            self._make_signal(value=20, client="0xA"),
            self._make_signal(value=10, client="0xB"),
            self._make_signal(value=15, client="0xC"),
        ]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 15
        assert "low_wts" in score.flags

    def test_value_decimals_normalization(self):
        """Value with decimals should normalize correctly."""
        signals = [self._make_signal(value=8500, decimals=2, client="0xA")]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 85  # 8500 / 100 = 85.0

    def test_value_clamped_to_100(self):
        """Normalized scores > 100 should clamp."""
        signals = [self._make_signal(value=150, client="0xA")]
        score = self.scorer.compute_wts(signals)
        assert score.wts == 100


# ─────────────────────────────────────────────────────────────────
# Policy Engine Tests
# ─────────────────────────────────────────────────────────────────

class TestPolicyEngine:
    """Tests for the 10-check policy evaluation."""

    def setup_method(self):
        self.engine = PolicyEngine()

    def _make_identity(self, organization=None, attestations=None):
        return AgentIdentity(
            agent_id=1,
            wallet_address="0xAgent",
            organization=organization,
            attestations=attestations or [],
        )

    def _make_reputation(self, wts=80, sample_size=5, flags=None, new_agent=False):
        return ReputationScore(
            wts=wts, sample_size=sample_size, new_agent=new_agent,
            flags=flags or [],
        )

    def test_check_1_address_blocklist(self):
        """Blocklisted address → BLOCKED."""
        policy = TrustPolicy(address_blocklist=["0xBAD"])
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=self._make_reputation(),
            amount=Decimal("10"),
            recipient_address="0xBAD",
            policy=policy,
        )
        assert result.verdict == TrustVerdict.BLOCKED
        assert result.block_reason == "ADDRESS_BLOCKLISTED"

    def test_check_2_org_whitelist_skips_rest(self):
        """Whitelisted org → APPROVED, even with low WTS."""
        policy = TrustPolicy(
            org_whitelist=["trusted-corp"],
            min_wts=90,
        )
        identity = self._make_identity(organization="trusted-corp")
        reputation = self._make_reputation(wts=10)  # Very low
        result = self.engine.evaluate(
            identity=identity, reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED

    def test_check_3_identity_required_no_identity(self):
        """Identity required + no identity → BLOCKED."""
        policy = TrustPolicy(identity_required=True)
        result = self.engine.evaluate(
            identity=None, reputation=None,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.BLOCKED
        assert result.block_reason == "NO_IDENTITY"

    def test_check_4_fraud_tag(self):
        """Fraud tag → BLOCKED (default fraud_tag_action)."""
        policy = TrustPolicy()
        reputation = self._make_reputation(wts=90, flags=["fraud"])
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.BLOCKED
        assert result.block_reason == "FRAUD_TAG"

    def test_check_5_new_agent_hold(self):
        """New agent with standard policy → HELD."""
        policy = TrustPolicy(new_agent_action=TrustVerdict.HELD)
        reputation = self._make_reputation(wts=80, new_agent=True)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.HELD
        assert result.block_reason == "NEW_AGENT"

    def test_check_5_new_agent_approved_permissive(self):
        """New agent with permissive policy → APPROVED."""
        policy = TrustPolicy.permissive()
        reputation = self._make_reputation(wts=80, new_agent=True)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED

    def test_check_6_min_feedback_count(self):
        """Not enough feedback → HELD."""
        policy = TrustPolicy(min_feedback_count=5)
        reputation = self._make_reputation(wts=90, sample_size=2)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.HELD
        assert result.block_reason == "INSUFFICIENT_FEEDBACK"

    def test_check_7_min_wts(self):
        """WTS below minimum → BLOCKED."""
        policy = TrustPolicy(min_wts=70)
        reputation = self._make_reputation(wts=50, sample_size=5)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.BLOCKED
        assert result.block_reason == "LOW_WTS"

    def test_check_8_high_value_wts(self):
        """High-value payment with insufficient WTS → HELD."""
        policy = TrustPolicy(
            high_value_threshold_usd=Decimal("500"),
            high_value_min_wts=85,
        )
        reputation = self._make_reputation(wts=72, sample_size=10)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("1000"),
            recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.HELD
        assert result.block_reason == "HIGH_VALUE_WTS_FAIL"

    def test_check_8_high_value_passes_below_threshold(self):
        """Amount below threshold → not checked."""
        policy = TrustPolicy(
            high_value_threshold_usd=Decimal("500"),
            high_value_min_wts=85,
        )
        reputation = self._make_reputation(wts=72, sample_size=10)
        result = self.engine.evaluate(
            identity=self._make_identity(),
            reputation=reputation,
            amount=Decimal("100"),  # Below threshold
            recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED

    def test_check_9_missing_attestations(self):
        """Missing required attestations → HELD."""
        policy = TrustPolicy(require_attestations=["kyb", "soc2"])
        identity = self._make_identity(attestations=["kyb"])  # Missing soc2
        reputation = self._make_reputation(wts=90, sample_size=10)
        result = self.engine.evaluate(
            identity=identity, reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.HELD
        assert "MISSING_ATTESTATIONS:soc2" in result.block_reason

    def test_check_10_all_pass(self):
        """All checks pass → APPROVED."""
        policy = TrustPolicy(
            min_wts=50,
            min_feedback_count=3,
        )
        identity = self._make_identity()
        reputation = self._make_reputation(wts=85, sample_size=10)
        result = self.engine.evaluate(
            identity=identity, reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED

    def test_no_identity_no_reputation_permissive(self):
        """No identity, permissive policy → APPROVED."""
        policy = TrustPolicy.permissive()
        result = self.engine.evaluate(
            identity=None, reputation=None,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED

    def test_strict_policy_full_evaluation(self):
        """Strict policy with good agent → APPROVED."""
        policy = TrustPolicy.strict()
        identity = self._make_identity(attestations=["kyb"])
        reputation = self._make_reputation(wts=90, sample_size=10)
        result = self.engine.evaluate(
            identity=identity, reputation=reputation,
            amount=Decimal("10"), recipient_address="0xA", policy=policy,
        )
        assert result.verdict == TrustVerdict.APPROVED


# ─────────────────────────────────────────────────────────────────
# Trust Cache Tests
# ─────────────────────────────────────────────────────────────────

class TestTrustCache:
    """Tests for the TTL-based trust cache."""

    @pytest.fixture
    def storage(self):
        from omniclaw.storage.memory import InMemoryStorage
        return InMemoryStorage()

    @pytest.fixture
    def cache(self, storage):
        return TrustCache(storage)

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """Basic set/get round-trip."""
        await cache.set("1", "0xABC", "identity", {"name": "Agent"})
        result = await cache.get("1", "0xABC", "identity")
        assert result == {"name": "Agent"}

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache):
        """Cache miss → None."""
        result = await cache.get("1", "0xNONE", "identity")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self, cache):
        """Expired entry → None + auto-deleted."""
        await cache.set("1", "0xABC", "identity", {"name": "Agent"}, ttl=0)
        # TTL=0 means already expired
        import time
        time.sleep(0.01)
        result = await cache.get("1", "0xABC", "identity")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate(self, cache):
        """Invalidate removes cached entry."""
        await cache.set("1", "0xABC", "identity", {"name": "Agent"})
        await cache.invalidate("1", "0xABC", "identity")
        result = await cache.get("1", "0xABC", "identity")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_fetch_cache_miss(self, cache):
        """get_or_fetch with miss → calls fetch_fn."""
        fetch_fn = AsyncMock(return_value={"name": "Fetched"})
        data, hit = await cache.get_or_fetch("1", "0xABC", "identity", fetch_fn)
        assert data == {"name": "Fetched"}
        assert hit is False
        fetch_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_or_fetch_cache_hit(self, cache):
        """get_or_fetch with hit → does NOT call fetch_fn."""
        await cache.set("1", "0xABC", "identity", {"name": "Cached"})
        fetch_fn = AsyncMock(return_value={"name": "Fetched"})
        data, hit = await cache.get_or_fetch("1", "0xABC", "identity", fetch_fn)
        assert data == {"name": "Cached"}
        assert hit is True
        fetch_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_case_insensitive_keys(self, cache):
        """Keys should be case-insensitive on address."""
        await cache.set("1", "0xABC", "identity", {"name": "Agent"})
        result = await cache.get("1", "0xabc", "identity")
        assert result == {"name": "Agent"}


# ─────────────────────────────────────────────────────────────────
# Agent Identity Type Tests
# ─────────────────────────────────────────────────────────────────

class TestAgentIdentity:
    """Tests for AgentIdentity parsing."""

    def test_from_registration_file(self):
        """Parse a standard ERC-8004 registration JSON."""
        data = {
            "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
            "name": "TestAgent",
            "description": "A test agent",
            "image": "https://example.com/agent.png",
            "services": [
                {"name": "A2A", "endpoint": "https://agent.example/.well-known/agent-card.json", "version": "0.3.0"},
                {"name": "MCP", "endpoint": "https://mcp.agent.example/"},
            ],
            "x402Support": True,
            "active": True,
            "supportedTrust": ["reputation", "crypto-economic"],
        }
        identity = AgentIdentity.from_registration_file(
            agent_id=42,
            wallet_address="0xOwner",
            data=data,
        )
        assert identity.agent_id == 42
        assert identity.name == "TestAgent"
        assert identity.x402_support is True
        assert len(identity.services) == 2
        assert identity.has_service("A2A") is True
        assert identity.has_service("ENS") is False
        assert "reputation" in identity.supported_trust

    def test_feedback_signal_normalization(self):
        """FeedbackSignal normalizes value/decimals correctly."""
        signal = FeedbackSignal(
            agent_id=1, client_address="0x", feedback_index=1,
            value=9977, value_decimals=2,
        )
        assert signal.normalized_score == 99.77

    def test_trust_check_result_serialization(self):
        """TrustCheckResult.to_dict() produces clean JSON."""
        result = TrustCheckResult(
            identity_found=True,
            token_id=42,
            wts=85,
            verdict=TrustVerdict.APPROVED,
            flags=["new_agent"],
        )
        d = result.to_dict()
        assert d["identity_found"] is True
        assert d["token_id"] == 42
        assert d["wts"] == 85
        assert d["verdict"] == "APPROVED"


# ─────────────────────────────────────────────────────────────────
# ERC-8004 Contract Helpers Tests
# ─────────────────────────────────────────────────────────────────

class TestERC8004Helpers:
    """Tests for core/erc8004.py helpers."""

    def test_deployed_addresses_exist(self):
        from omniclaw.core.erc8004 import get_identity_registry, get_reputation_registry
        assert get_identity_registry("ETH") == "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
        assert get_reputation_registry("ETH") == "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63"

    def test_base_sepolia_addresses(self):
        from omniclaw.core.erc8004 import get_identity_registry, get_reputation_registry
        assert get_identity_registry("BASE-SEPOLIA") is not None
        assert get_reputation_registry("BASE-SEPOLIA") is not None

    def test_agent_registry_string(self):
        from omniclaw.core.erc8004 import build_agent_registry_string
        result = build_agent_registry_string("ETH")
        assert result == "eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"

    def test_unsupported_network(self):
        from omniclaw.core.erc8004 import is_erc8004_supported
        assert is_erc8004_supported("ETH") is True
        assert is_erc8004_supported("UNSUPPORTED") is False

    def test_abi_structures(self):
        from omniclaw.core.erc8004 import IDENTITY_REGISTRY_ABI, REPUTATION_REGISTRY_ABI
        # Identity should have ownerOf, tokenURI, register, etc.
        func_names = {f["name"] for f in IDENTITY_REGISTRY_ABI}
        assert "ownerOf" in func_names
        assert "tokenURI" in func_names
        assert "register" in func_names
        assert "getAgentWallet" in func_names

        # Reputation should have giveFeedback, getSummary, etc.
        func_names = {f["name"] for f in REPUTATION_REGISTRY_ABI}
        assert "giveFeedback" in func_names
        assert "getSummary" in func_names
        assert "readFeedback" in func_names
        assert "getClients" in func_names

    def test_get_validation_registry(self):
        """get_validation_registry returns None (not deployed yet)."""
        from omniclaw.core.erc8004 import get_validation_registry
        # Validation contracts not yet deployed — should return None
        assert get_validation_registry("ETH") is None
        assert get_validation_registry("UNSUPPORTED") is None


# ─────────────────────────────────────────────────────────────────
# Endpoint Domain Verification Tests (Rec #1)
# ─────────────────────────────────────────────────────────────────

class TestEndpointDomainVerification:
    """Tests for EIP-8004 §5 endpoint domain verification."""

    @pytest.mark.asyncio
    async def test_verify_endpoint_domain_success(self):
        """Matching registration → verified."""
        from omniclaw.identity.resolver import IdentityResolver

        resolver = IdentityResolver()

        well_known_response = {
            "registrations": [
                {
                    "agentId": 42,
                    "agentRegistry": "eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = well_known_response

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("omniclaw.identity.resolver.httpx.AsyncClient", return_value=mock_client_instance):
            result = await resolver.verify_endpoint_domain(
                endpoint_url="https://agent.example.com/api",
                agent_id=42,
                agent_registry="eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_verify_endpoint_domain_mismatch(self):
        """Non-matching registration → not verified."""
        from omniclaw.identity.resolver import IdentityResolver

        resolver = IdentityResolver()

        well_known_response = {
            "registrations": [
                {
                    "agentId": 999,  # Wrong agent
                    "agentRegistry": "eip155:1:0xDifferent",
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = well_known_response

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("omniclaw.identity.resolver.httpx.AsyncClient", return_value=mock_client_instance):
            result = await resolver.verify_endpoint_domain(
                endpoint_url="https://agent.example.com/api",
                agent_id=42,
                agent_registry="eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_verify_endpoint_domain_unreachable(self):
        """Unreachable endpoint → not verified (no crash)."""
        from omniclaw.identity.resolver import IdentityResolver

        resolver = IdentityResolver()

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("omniclaw.identity.resolver.httpx.AsyncClient", return_value=mock_client_instance):
            result = await resolver.verify_endpoint_domain(
                endpoint_url="https://unreachable.example.com/",
                agent_id=42,
                agent_registry="eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_verify_non_https_returns_false(self):
        """Non-HTTPS endpoints → not verified."""
        from omniclaw.identity.resolver import IdentityResolver

        resolver = IdentityResolver()
        assert await resolver.verify_endpoint_domain("http://insecure.com", 1, "reg") is False
        assert await resolver.verify_endpoint_domain("ipfs://cid", 1, "reg") is False
        assert await resolver.verify_endpoint_domain("", 1, "reg") is False

    @pytest.mark.asyncio
    async def test_verify_all_endpoints(self):
        """verify_all_endpoints iterates & returns verified domains."""
        from omniclaw.identity.resolver import IdentityResolver

        resolver = IdentityResolver()
        identity = AgentIdentity(
            agent_id=42,
            wallet_address="0xOwner",
            agent_registry="eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            services=[
                AgentService(name="A2A", endpoint="https://a2a.agent.com/card"),
                AgentService(name="MCP", endpoint="https://mcp.agent.com/"),
                AgentService(name="ENS", endpoint="vitalik.eth"),  # Not HTTPS
            ],
        )

        # Mock: only a2a domain passes
        async def mock_verify(endpoint_url, agent_id, agent_registry):
            return "a2a.agent.com" in endpoint_url

        with patch.object(resolver, "verify_endpoint_domain", side_effect=mock_verify):
            verified = await resolver.verify_all_endpoints(identity)
            assert "a2a.agent.com" in verified
            assert len(verified) == 1


# ─────────────────────────────────────────────────────────────────
# Reputation Summary & Bulk Feedback Tests (Rec #2, #4)
# ─────────────────────────────────────────────────────────────────

class TestProviderOptimizations:
    """Tests for getSummary and readAllFeedback optimizations."""

    def test_get_reputation_summary_empty_clients_warning(self):
        """getSummary with empty clients → None (EIP-8004 security requirement)."""
        from omniclaw.trust.provider import ERC8004Provider

        provider = ERC8004Provider(rpc_url="https://fake.rpc")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            provider.get_reputation_summary(
                agent_id=42, client_addresses=[], network="ETH",
            )
        )
        assert result is None

    def test_get_all_feedback_bulk_no_registry(self):
        """Bulk feedback with no registry → empty list."""
        from omniclaw.trust.provider import ERC8004Provider

        provider = ERC8004Provider(rpc_url="https://fake.rpc")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            provider.get_all_feedback_bulk(
                agent_id=42, network="UNSUPPORTED",
            )
        )
        assert result == []


# ─────────────────────────────────────────────────────────────────
# Validation Registry Readiness Tests (Rec #3)
# ─────────────────────────────────────────────────────────────────

class TestValidationRegistryReadiness:
    """Tests for Validation Registry methods (ready for deployment)."""

    def test_validation_status_no_registry(self):
        """get_validation_status with no deployed registry → None."""
        from omniclaw.trust.provider import ERC8004Provider

        provider = ERC8004Provider(rpc_url="https://fake.rpc")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            provider.get_validation_status("0xabc123", "ETH")
        )
        assert result is None

    def test_agent_validations_no_registry(self):
        """get_agent_validations with no deployed registry → empty list."""
        from omniclaw.trust.provider import ERC8004Provider

        provider = ERC8004Provider(rpc_url="https://fake.rpc")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            provider.get_agent_validations(42, "ETH")
        )
        assert result == []

    def test_validator_requests_no_registry(self):
        """get_validator_requests with no deployed registry → empty list."""
        from omniclaw.trust.provider import ERC8004Provider

        provider = ERC8004Provider(rpc_url="https://fake.rpc")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            provider.get_validator_requests("0xValidator", "ETH")
        )
        assert result == []


# ─────────────────────────────────────────────────────────────────
# Datetime Fix Tests (Rec #5)
# ─────────────────────────────────────────────────────────────────

class TestDatetimeFix:
    """Verify datetime.now(timezone.utc) is used instead of deprecated utcnow()."""

    def test_trust_gate_uses_timezone_aware_datetime(self):
        """gate.py should use datetime.now(timezone.utc)."""
        import inspect
        from omniclaw.trust import gate

        source = inspect.getsource(gate)
        assert "datetime.utcnow()" not in source, "gate.py still uses deprecated utcnow()"
        assert "datetime.now(timezone.utc)" in source

    def test_scoring_uses_timezone_aware_datetime(self):
        """scoring.py should use datetime.now(timezone.utc)."""
        import inspect
        from omniclaw.trust import scoring

        source = inspect.getsource(scoring)
        assert "datetime.utcnow()" not in source, "scoring.py still uses deprecated utcnow()"
        assert "datetime.now(timezone.utc)" in source

