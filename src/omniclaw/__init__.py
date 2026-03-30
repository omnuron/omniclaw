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

import warnings

# Suppress noisy deprecation warnings from downstream dependencies (e.g. web3, circle-sdk)
# We do this at the very top of the package to ensure it catches warnings during imports.
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")

from omniclaw.client import OmniClaw
from omniclaw.core.config import Config
from omniclaw.core.exceptions import (
    ConfigurationError,
    CrosschainError,
    GuardError,
    IdempotencyError,
    InsufficientBalanceError,
    NetworkError,
    OmniClawError,
    PaymentError,
    ProtocolError,
    TransactionTimeoutError,
    ValidationError,
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

# ERC-8004 Trust Layer
from omniclaw.identity.types import (
    AgentIdentity,
    ReputationScore,
    TrustCheckResult,
    TrustPolicy,
    TrustVerdict,
)
from omniclaw.onboarding import (
    doctor,
    ensure_setup,
    find_recovery_file,
    generate_entity_secret,
    get_config_dir,
    print_doctor_status,
    print_setup_status,
    quick_setup,
    store_managed_credentials,
    verify_setup,
)

# Nanopayments (EIP-3009 Circle Gateway)
from omniclaw.protocols.nanopayments import (
    # Exceptions
    AuthorizationExpiredError,
    AuthorizationNotYetValidError,
    DepositError,
    # Types
    DepositResult,
    DuplicateKeyAliasError,
    ERC20ApprovalError,
    GatewayAPIError,
    GatewayBalance,
    # Middleware
    GatewayMiddleware,
    # Wallet
    GatewayWalletManager,
    InvalidPriceError,
    InvalidPrivateKeyError,
    InvalidSignatureError,
    KeyNotFoundError,
    MiddlewareError,
    NanoKeyStore,
    # Vault & Keys
    NanoKeyVault,
    # Adapter
    NanopaymentAdapter,
    # Client
    NanopaymentClient,
    NanopaymentError,
    NanopaymentHTTPClient,
    NanopaymentNotInitializedError,
    NanopaymentProtocolAdapter,
    NanopaymentResult,
    NoDefaultKeyError,
    NonceReusedError,
    PaymentPayload,
    PaymentRequiredError,
    PaymentRequiredHTTPError,
    PaymentRequirements,
    SettlementError,
    SignatureVerificationError,
    SigningError,
    SupportedKind,
    UnsupportedNetworkError,
    UnsupportedSchemeError,
    VerificationError,
    VerifyResponse,
    WithdrawError,
    WithdrawResult,
    parse_price,
)
from omniclaw.trust.gate import TrustGate

__version__ = "0.1.0"
__all__ = [
    # Main Client
    "OmniClaw",
    # Setup utilities
    "quick_setup",
    "ensure_setup",
    "doctor",
    "generate_entity_secret",
    "verify_setup",
    "print_doctor_status",
    "print_setup_status",
    "find_recovery_file",
    "get_config_dir",
    "store_managed_credentials",
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
    "CrosschainError",
    "IdempotencyError",
    "TransactionTimeoutError",
    "ValidationError",
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
    # Nanopayments (EIP-3009 Circle Gateway)
    # Client
    "NanopaymentClient",
    "NanopaymentHTTPClient",
    # Vault & Keys
    "NanoKeyVault",
    "NanoKeyStore",
    # Adapter
    "NanopaymentAdapter",
    "NanopaymentProtocolAdapter",
    # Wallet
    "GatewayWalletManager",
    # Middleware
    "GatewayMiddleware",
    "PaymentRequiredHTTPError",
    "parse_price",
    # Types
    "DepositResult",
    "GatewayBalance",
    "NanopaymentResult",
    "PaymentPayload",
    "PaymentRequirements",
    "SupportedKind",
    "VerifyResponse",
    "WithdrawResult",
    # Exceptions
    "NanopaymentError",
    "NanopaymentNotInitializedError",
    "AuthorizationExpiredError",
    "AuthorizationNotYetValidError",
    "DepositError",
    "DuplicateKeyAliasError",
    "ERC20ApprovalError",
    "GatewayAPIError",
    "InsufficientBalanceError",
    "InvalidPriceError",
    "InvalidPrivateKeyError",
    "InvalidSignatureError",
    "KeyNotFoundError",
    "MiddlewareError",
    "NoDefaultKeyError",
    "NonceReusedError",
    "PaymentRequiredError",
    "SettlementError",
    "SignatureVerificationError",
    "SigningError",
    "UnsupportedNetworkError",
    "UnsupportedSchemeError",
    "VerificationError",
    "WithdrawError",
]
