"""Trust module — ERC-8004 Trust Gate for OmniClaw."""

from omniclaw.trust.cache import TrustCache
from omniclaw.trust.gate import TrustGate
from omniclaw.trust.policy import PolicyEngine
from omniclaw.trust.provider import ERC8004Provider
from omniclaw.trust.scoring import ReputationAggregator

__all__ = [
    "TrustGate",
    "TrustCache",
    "PolicyEngine",
    "ReputationAggregator",
    "ERC8004Provider",
]

