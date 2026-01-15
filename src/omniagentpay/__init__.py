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

from omniagentpay.core.types import (
    Network,
    FeeLevel,
    PaymentMethod,
    PaymentStatus,
    WalletInfo,
    WalletSetInfo,
    Balance,
    TokenInfo,
    PaymentRequest,
    PaymentResult,
    SimulationResult,
    TransactionInfo,
)
from omniagentpay.core.config import Config
from omniagentpay.core.exceptions import (
    OmniAgentPayError,
    ConfigurationError,
    WalletError,
    PaymentError,
    GuardError,
    ProtocolError,
    InsufficientBalanceError,
    NetworkError,
    X402Error,
)
from omniagentpay.onboarding import (
    quick_setup,
    ensure_setup,
    generate_entity_secret,
    verify_setup,
    print_setup_status,
)
from omniagentpay.client import OmniAgentPay

# Import guards for convenience
from omniagentpay.guards import (
    Guard,
    GuardChain,
    GuardResult,
    PaymentContext,
    BudgetGuard,
    SingleTxGuard,
    RecipientGuard,
    RateLimitGuard,
    ConfirmGuard,
)

__version__ = "0.1.0"
__all__ = [
    # Main Client
    "OmniAgentPay",
    
    # Setup utilities
    "quick_setup",
    "ensure_setup",
    "generate_entity_secret",
    "verify_setup",
    "print_setup_status",
    
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
