"""
OmniAgentPay - The Payment Infrastructure Layer for Autonomous AI Agents

One SDK. Three lines of code. Any agent framework.

Quick Setup:
    >>> from omniagentpay.onboarding import quick_setup
    >>> quick_setup("YOUR_CIRCLE_API_KEY")

Usage:
    >>> from omniagentpay import OmniAgentPay
    >>> from decimal import Decimal
    >>>
    >>> client = OmniAgentPay()
    >>> result = await client.pay(
    ...     recipient="0x...",
    ...     amount=Decimal("10.00"),
    ...     wallet_id="wallet-123",
    ... )
"""

from omniagentpay.client import OmniAgentPay
from omniagentpay.core.config import Config
from omniagentpay.core.exceptions import (
    ConfigurationError,
    GuardError,
    InsufficientBalanceError,
    NetworkError,
    OmniAgentPayError,
    PaymentError,
    ProtocolError,
    WalletError,
    X402Error,
)
from omniagentpay.core.types import (
    Balance,
    FeeLevel,
    Network,
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
from omniagentpay.guards import (
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
from omniagentpay.onboarding import (
    ensure_setup,
    find_recovery_file,
    generate_entity_secret,
    get_config_dir,
    print_setup_status,
    quick_setup,
    verify_setup,
)

__version__ = "0.0.1"
__all__ = [
    # Main Client
    "OmniAgentPay",
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
    # Config
    "Config",
    # Exceptions
    "OmniAgentPayError",
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
]
