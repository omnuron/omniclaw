"""
ERC-8004 Trust Layer types and data structures.

Based on the EIP-8004 specification (Trustless Agents) and the OmniClaw
Trust Gate system design.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger("omniclaw.identity.types")

# The official registration type URI from EIP-8004
_ERC8004_REGISTRATION_TYPE = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TrustVerdict(str, Enum):
    """Outcome of a Trust Gate evaluation."""

    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    HELD = "HELD"


class TrustErrorCode(str, Enum):
    """Machine-readable error codes from the Trust Gate."""

    TRUST_BLOCKED = "TRUST_BLOCKED"
    TRUST_HELD = "TRUST_HELD"
    TRUST_NO_IDENTITY = "TRUST_NO_IDENTITY"
    TRUST_REGISTRY_ERROR = "TRUST_REGISTRY_ERROR"
    TRUST_METADATA_ERROR = "TRUST_METADATA_ERROR"
    TRUST_POLICY_NOT_FOUND = "TRUST_POLICY_NOT_FOUND"


# ---------------------------------------------------------------------------
# Agent Identity (from ERC-8004 Identity Registry)
# ---------------------------------------------------------------------------

@dataclass
class AgentService:
    """A service endpoint advertised in the agent registration file."""

    name: str                # e.g. "A2A", "MCP", "web", "ENS", "email"
    endpoint: str            # URL / ENS name / email
    version: str | None = None


@dataclass
class AgentIdentity:
    """
    Parsed identity from the ERC-8004 Identity Registry.

    Maps to the on-chain ERC-721 token + the off-chain agent registration file
    fetched from agentURI (§3 of EIP-8004).
    """

    # On-chain fields
    agent_id: int                          # ERC-721 tokenId
    wallet_address: str                    # Owner address of the NFT
    agent_wallet: str | None = None        # Payment address (agentWallet metadata)
    agent_registry: str | None = None      # e.g. "eip155:1:0x8004A1..."

    # Off-chain registration file fields (from agentURI → JSON)
    registration_type: str | None = None   # MUST: "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    name: str | None = None
    description: str | None = None
    image: str | None = None
    organization: str | None = None        # Derived from name/description heuristic
    services: list[AgentService] = field(default_factory=list)
    x402_support: bool = False
    active: bool = True
    supported_trust: list[str] = field(default_factory=list)
    attestations: list[str] = field(default_factory=list)

    # Internal
    created_at: datetime | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def has_service(self, name: str) -> bool:
        """Check if agent has a specific service type."""
        return any(s.name.lower() == name.lower() for s in self.services)

    @classmethod
    def from_registration_file(
        cls,
        agent_id: int,
        wallet_address: str,
        data: dict[str, Any],
    ) -> AgentIdentity:
        """
        Parse an ERC-8004 agent registration JSON file.

        The EIP-8004 spec says the registration file MUST have:
        - type: "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
        - name, description, services[], registrations[]

        We validate "type" but don't hard-fail on it — agents may use
        older drafts or custom registration files.
        """
        # Validate the registration type (EIP-8004 MUST field)
        reg_type = data.get("type")
        if not reg_type:
            logger.warning(
                "Agent %d registration file missing 'type' field "
                "(expected '%s')",
                agent_id,
                _ERC8004_REGISTRATION_TYPE,
            )
        elif reg_type != _ERC8004_REGISTRATION_TYPE:
            logger.warning(
                "Agent %d registration file has unexpected type '%s' "
                "(expected '%s')",
                agent_id,
                reg_type,
                _ERC8004_REGISTRATION_TYPE,
            )

        services = [
            AgentService(
                name=s.get("name", ""),
                endpoint=s.get("endpoint", ""),
                version=s.get("version"),
            )
            for s in data.get("services", [])
        ]

        # Extract agentRegistry from registrations array (EIP-8004 §3)
        agent_registry = None
        registrations = data.get("registrations", [])
        if registrations:
            # Find the matching registration or use the first one
            for reg in registrations:
                if reg.get("agentId") == agent_id:
                    agent_registry = reg.get("agentRegistry")
                    break
            if not agent_registry and registrations:
                agent_registry = registrations[0].get("agentRegistry")

        return cls(
            agent_id=agent_id,
            wallet_address=wallet_address,
            agent_registry=agent_registry,
            registration_type=reg_type,
            name=data.get("name"),
            description=data.get("description"),
            image=data.get("image"),
            services=services,
            x402_support=data.get("x402Support", False),
            active=data.get("active", True),
            supported_trust=data.get("supportedTrust", []),
            raw_metadata=data,
        )


# ---------------------------------------------------------------------------
# Reputation (from ERC-8004 Reputation Registry)
# ---------------------------------------------------------------------------

@dataclass
class FeedbackSignal:
    """Single feedback entry from the Reputation Registry."""

    agent_id: int
    client_address: str
    feedback_index: int
    value: int              # Raw int128 value
    value_decimals: int     # uint8, 0-18
    tag1: str = ""
    tag2: str = ""
    is_revoked: bool = False

    @property
    def normalized_score(self) -> float:
        """Normalize value using value_decimals to a float."""
        if self.value_decimals == 0:
            return float(self.value)
        return float(self.value) / (10 ** self.value_decimals)


@dataclass
class ReputationScore:
    """
    Weighted Trust Score (WTS) computed by the Reputation Aggregator.

    Algorithm from §3.3 of the system design spec.
    """

    wts: int                        # 0-100 weighted trust score
    sample_size: int                # Number of feedback signals used
    new_agent: bool                 # True if < 3 feedback entries
    flags: list[str] = field(default_factory=list)
    raw_signals: list[FeedbackSignal] = field(default_factory=list)

    # Breakdown
    total_feedback_count: int = 0
    revoked_count: int = 0
    self_review_count: int = 0
    verified_submitter_count: int = 0


# ---------------------------------------------------------------------------
# Trust Check Result (returned to SDK users)
# ---------------------------------------------------------------------------

@dataclass
class TrustCheckResult:
    """
    Full result of a Trust Gate evaluation.

    Attached to every PaymentResult and SimulationResult when
    a trust policy is active. (§6.2 of the system design spec)
    """

    # Identity
    identity_found: bool
    token_id: int | None = None
    organization: str | None = None

    # Reputation
    wts: int | None = None
    sample_size: int = 0
    new_agent: bool = False
    flags: list[str] = field(default_factory=list)
    attestations: list[str] = field(default_factory=list)

    # Policy
    policy_id: str | None = None
    verdict: TrustVerdict = TrustVerdict.APPROVED
    block_reason: str | None = None

    # Performance
    check_latency_ms: int = 0
    cache_hit: bool = False
    checked_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "identity_found": self.identity_found,
            "token_id": self.token_id,
            "organization": self.organization,
            "wts": self.wts,
            "sample_size": self.sample_size,
            "new_agent": self.new_agent,
            "flags": self.flags,
            "attestations": self.attestations,
            "policy_id": self.policy_id,
            "verdict": self.verdict.value,
            "block_reason": self.block_reason,
            "check_latency_ms": self.check_latency_ms,
            "cache_hit": self.cache_hit,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


# ---------------------------------------------------------------------------
# Trust Policy
# ---------------------------------------------------------------------------

@dataclass
class TrustPolicy:
    """
    Operator-configured trust policy applied per-wallet.

    Evaluation order (§4.3 of the system design spec):
    1. Address blocklist
    2. Org whitelist (skip remaining if matched)
    3. Identity required check
    4. Fraud tag check
    5. New agent check
    6. Min feedback count
    7. Min WTS check
    8. High-value WTS check
    9. Attestation check
    10. All pass → APPROVED
    """

    policy_id: str = "default"
    name: str = "Default Policy"

    # Identity
    identity_required: bool = False

    # Reputation thresholds
    min_wts: int = 0                       # 0-100
    min_feedback_count: int = 0

    # Attestations
    require_attestations: list[str] = field(default_factory=list)

    # Allow/block lists
    org_whitelist: list[str] = field(default_factory=list)
    address_blocklist: list[str] = field(default_factory=list)

    # Actions for edge cases
    new_agent_action: TrustVerdict = TrustVerdict.APPROVED
    fraud_tag_action: TrustVerdict = TrustVerdict.BLOCKED
    unresolvable_action: TrustVerdict = TrustVerdict.HELD

    # High-value thresholds
    high_value_threshold_usd: Decimal = Decimal("0")
    high_value_min_wts: int = 0

    # --- Presets -------------------------------------------------------

    @classmethod
    def permissive(cls) -> TrustPolicy:
        """Lenient policy — pass everything, block only known fraud."""
        return cls(
            policy_id="preset_permissive",
            name="Permissive",
            identity_required=False,
            min_wts=0,
            min_feedback_count=0,
            new_agent_action=TrustVerdict.APPROVED,
            fraud_tag_action=TrustVerdict.BLOCKED,
            unresolvable_action=TrustVerdict.APPROVED,
        )

    @classmethod
    def standard(cls) -> TrustPolicy:
        """Balanced policy — hold new/unverified agents."""
        return cls(
            policy_id="preset_standard",
            name="Standard",
            identity_required=True,
            min_wts=50,
            min_feedback_count=3,
            new_agent_action=TrustVerdict.HELD,
            fraud_tag_action=TrustVerdict.BLOCKED,
            unresolvable_action=TrustVerdict.HELD,
            high_value_threshold_usd=Decimal("500"),
            high_value_min_wts=75,
        )

    @classmethod
    def strict(cls) -> TrustPolicy:
        """Enterprise policy — require identity + high reputation."""
        return cls(
            policy_id="preset_strict",
            name="Strict",
            identity_required=True,
            min_wts=70,
            min_feedback_count=3,
            require_attestations=["kyb"],
            new_agent_action=TrustVerdict.HELD,
            fraud_tag_action=TrustVerdict.BLOCKED,
            unresolvable_action=TrustVerdict.HELD,
            high_value_threshold_usd=Decimal("500"),
            high_value_min_wts=85,
        )
