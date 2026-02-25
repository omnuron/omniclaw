"""Identity module — ERC-8004 Agent Identity & Trust."""

from omniclaw.identity.resolver import IdentityResolver
from omniclaw.identity.types import (
    AgentIdentity,
    AgentService,
    FeedbackSignal,
    ReputationScore,
    TrustCheckResult,
    TrustErrorCode,
    TrustPolicy,
    TrustVerdict,
)

__all__ = [
    "IdentityResolver",
    "AgentIdentity",
    "AgentService",
    "FeedbackSignal",
    "ReputationScore",
    "TrustCheckResult",
    "TrustErrorCode",
    "TrustPolicy",
    "TrustVerdict",
]
