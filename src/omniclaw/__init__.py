"""
OmniClaw - The Payment Infrastructure Layer for Autonomous AI Agents

One SDK. Three lines of code. Any agent framework.

Quick Setup:
    >>> from omniclaw.onboarding import quick_setup
    >>> quick_setup("YOUR_CIRCLE_API_KEY")

Usage:
    >>> from omniclaw import OmniClaw
    >>> from decimal import Decimal
    >>>
    >>> client = OmniClaw()
    >>> result = await client.pay(
    ...     recipient="0x...",
    ...     amount=Decimal("10.00"),
    ...     wallet_id="wallet-123",
    ... )
"""

from omniclaw.client import OmniClaw
from omniclaw.core.config import Config
from omniclaw.core.exceptions import (
    ConfigurationError,
    GuardError,
    InsufficientBalanceError,
    NetworkError,
    OmniClawError,
    PaymentError,
    ProtocolError,
    WalletError,
    X402Error,
)
from omniclaw.core.types import (
    Balance,
    FeeLevel,
    Network,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    SimulationResult,
    TokenInfo,
    TransactionInfo,
    WalletInfo,
    WalletSetInfo,
)

# Import guards for convenience
from omniclaw.guards import (
    BudgetGuard,
    ConfirmGuard,
    Guard,
    GuardChain,
    GuardResult,
    PaymentContext,
    RateLimitGuard,
    RecipientGuard,
    SingleTxGuard,
)
from omniclaw.onboarding import (
    ensure_setup,
    find_recovery_file,
    generate_entity_secret,
    get_config_dir,
    print_setup_status,
    quick_setup,
    verify_setup,
)

# ERC-8004 Trust Layer
from omniclaw.identity.types import (
    AgentIdentity,
    ReputationScore,
    TrustCheckResult,
    TrustPolicy,
    TrustVerdict,
)
from omniclaw.trust.gate import TrustGate

__version__ = "0.0.1"
__all__ = [
    # Main Client
    "OmniClaw",
    # Setup utilities
    "quick_setup",
    "ensure_setup",
    "generate_entity_secret",
    "verify_setup",
    "print_setup_status",
    "find_recovery_file",
    "get_config_dir",
    # Types
    "Network",
    "FeeLevel",
    "PaymentMethod",
    "PaymentStatus",
    "WalletInfo",
    "WalletSetInfo",
    "Balance",
    "TokenInfo",
    "PaymentRequest",
    "PaymentResult",
    "SimulationResult",
    "TransactionInfo",
    "PaymentIntent",
    "PaymentIntentStatus",
    # Config
    "Config",
    # Exceptions
    "OmniClawError",
    "ConfigurationError",
    "WalletError",
    "PaymentError",
    "GuardError",
    "ProtocolError",
    "InsufficientBalanceError",
    "NetworkError",
    "X402Error",
    # Guards
    "Guard",
    "GuardChain",
    "GuardResult",
    "PaymentContext",
    "BudgetGuard",
    "SingleTxGuard",
    "RecipientGuard",
    "RateLimitGuard",
    "ConfirmGuard",
    # ERC-8004 Trust Layer
    "TrustGate",
    "TrustPolicy",
    "TrustVerdict",
    "TrustCheckResult",
    "AgentIdentity",
    "ReputationScore",
]
