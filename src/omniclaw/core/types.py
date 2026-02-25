"""
Type definitions for OmniClaw SDK.

This module contains all the enums, data classes, and type definitions
used throughout the SDK.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    TypeAlias,  # For older python compatibility
)

# Type alias for flexible amount input
AmountType: TypeAlias = Decimal | int | float | str


class Network(str, Enum):
    """Supported blockchain networks for Circle Developer-Controlled Wallets."""

    # Ethereum
    ETH = "ETH"
    ETH_SEPOLIA = "ETH-SEPOLIA"

    # Avalanche
    AVAX = "AVAX"
    AVAX_FUJI = "AVAX-FUJI"

    # Polygon
    MATIC = "MATIC"
    MATIC_AMOY = "MATIC-AMOY"

    # Solana
    SOL = "SOL"
    SOL_DEVNET = "SOL-DEVNET"

    # Arbitrum
    ARB = "ARB"
    ARB_SEPOLIA = "ARB-SEPOLIA"

    # Base
    BASE = "BASE"
    BASE_SEPOLIA = "BASE-SEPOLIA"

    # Optimism
    OP = "OP"
    OP_SEPOLIA = "OP-SEPOLIA"

    # Near
    NEAR = "NEAR"
    NEAR_TESTNET = "NEAR-TESTNET"

    # Aptos
    APTOS = "APTOS"
    APTOS_TESTNET = "APTOS-TESTNET"

    # Unichain
    UNI = "UNI"
    UNI_SEPOLIA = "UNI-SEPOLIA"

    # Monad
    MONAD = "MONAD"
    MONAD_TESTNET = "MONAD-TESTNET"

    # Arc
    ARC_TESTNET = "ARC-TESTNET"

    # Multi-chain
    EVM = "EVM"
    EVM_TESTNET = "EVM-TESTNET"

    @classmethod
    def from_string(cls, value: str) -> "Network":
        value_upper = value.upper().replace("_", "-")
        for member in cls:
            if member.value == value_upper:
                return member
        raise ValueError(f"Unknown network: {value}. Supported: {[n.value for n in cls]}")

    def is_testnet(self) -> bool:
        testnet_suffix = ("-SEPOLIA", "-TESTNET", "-FUJI", "-DEVNET", "-AMOY")
        return self.value.endswith(testnet_suffix) or self == Network.ARC_TESTNET

    def is_evm(self) -> bool:
        non_evm = (
            Network.SOL,
            Network.SOL_DEVNET,
            Network.NEAR,
            Network.NEAR_TESTNET,
            Network.APTOS,
            Network.APTOS_TESTNET,
        )
        return self not in non_evm

    def is_solana(self) -> bool:
        return self in (Network.SOL, Network.SOL_DEVNET)


def normalize_network(network: Network | str | None) -> Network | None:
    """
    Normalize a network value to a Network enum.
    
    Handles:
    - None -> None
    - Network enum -> Network enum (unchanged)
    - str -> Network enum (converted)
    
    Args:
        network: Network enum, string, or None
        
    Returns:
        Network enum or None
        
    Raises:
        ValueError: If string cannot be converted to Network
    """
    if network is None:
        return None
    if isinstance(network, Network):
        return network
    return Network.from_string(str(network))


class PaymentStrategy(str, Enum):
    """Strategy for handling payment execution reliability."""

    FAIL_FAST = "fail_fast"  # If network down, raise immediately
    RETRY_THEN_FAIL = "retry_then_fail"  # Retry transient errors, then raise
    QUEUE_BACKGROUND = "queue_background"  # If down/busy, queue for later (return PENDING)


class PaymentMethod(str, Enum):
    """Payment method types."""

    X402 = "x402"  # HTTP 402 protocol payment
    TRANSFER = "transfer"  # Direct wallet-to-wallet transfer
    CROSSCHAIN = "crosschain"  # Cross-chain transfer (Gateway/CCTP/Bridge Kit)


class PaymentStatus(str, Enum):
    """Payment transaction status."""

    PENDING = "pending"  # Payment initiated but not yet processing
    PROCESSING = "processing"  # Payment is being processed on-chain
    COMPLETED = "completed"  # Payment successfully completed
    FAILED = "failed"  # Payment failed
    CANCELLED = "cancelled"  # Payment was cancelled
    BLOCKED = "blocked"  # Payment was blocked by a guard


class PaymentIntentStatus(str, Enum):
    """Status of a PaymentIntent."""

    REQUIRES_CONFIRMATION = "requires_confirmation"  # Created, ready to confirm
    PROCESSING = "processing"  # Executive in progress
    SUCCEEDED = "succeeded"  # Completed successfully
    CANCELED = "canceled"  # Canceled by user/agent
    FAILED = "failed"  # Execution failed


class WalletState(str, Enum):
    """Wallet lifecycle state from Circle API."""

    LIVE = "LIVE"
    FROZEN = "FROZEN"


class AccountType(str, Enum):
    """Wallet account type."""

    SCA = "SCA"  # Smart Contract Account (EVM chains)
    EOA = "EOA"  # Externally Owned Account (native signing)


class CustodyType(str, Enum):
    """Wallet custody type."""

    DEVELOPER = "DEVELOPER"  # Developer-controlled wallet
    ENDUSER = "ENDUSER"  # User-controlled wallet


class TransactionState(str, Enum):
    """Transaction state from Circle API."""

    INITIATED = "INITIATED"
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CLEARED = "CLEARED"


class FeeLevel(str, Enum):
    """Fee level for transactions."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class TokenInfo:
    """Token information from Circle API."""

    id: str
    blockchain: str
    symbol: str
    name: str
    decimals: int
    is_native: bool
    token_address: str | None = None
    standard: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "TokenInfo":
        return cls(
            id=data["id"],
            blockchain=data["blockchain"],
            symbol=data["symbol"],
            name=data["name"],
            decimals=data["decimals"],
            is_native=data.get("isNative", False),
            token_address=data.get("tokenAddress"),
            standard=data.get("standard"),
        )


@dataclass
class Balance:
    """Wallet token balance."""

    amount: Decimal
    token: TokenInfo

    @property
    def currency(self) -> str:
        return self.token.symbol

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Balance":
        return cls(
            amount=Decimal(data["amount"]),
            token=TokenInfo.from_api_response(data["token"]),
        )


@dataclass
class WalletSetInfo:
    """Wallet set information from Circle API."""

    id: str
    name: str | None
    custody_type: CustodyType
    create_date: datetime
    update_date: datetime

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "WalletSetInfo":
        def parse_dt(val: str | datetime | None) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            return None

        return cls(
            id=data["id"],
            name=data.get("name"),
            custody_type=CustodyType(data["custodyType"]),
            create_date=parse_dt(data.get("createDate")),
            update_date=parse_dt(data.get("updateDate")),
        )


@dataclass
class WalletInfo:
    """Wallet information from Circle API."""

    id: str
    address: str
    blockchain: str
    state: WalletState
    wallet_set_id: str
    custody_type: CustodyType
    account_type: AccountType
    name: str | None = None
    create_date: datetime | None = None
    update_date: datetime | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "WalletInfo":
        def parse_dt(val: str | datetime | None) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            return None

        return cls(
            id=data["id"],
            address=data["address"],
            blockchain=data["blockchain"],
            state=WalletState(data["state"]),
            wallet_set_id=data["walletSetId"],
            custody_type=CustodyType(data["custodyType"]),
            account_type=AccountType(data["accountType"]),
            name=data.get("name"),
            create_date=parse_dt(data.get("createDate")),
            update_date=parse_dt(data.get("updateDate")),
        )


@dataclass
class TransactionInfo:
    """Transaction information from Circle API."""

    id: str
    state: TransactionState
    blockchain: str | None = None
    tx_hash: str | None = None
    wallet_id: str | None = None
    source_address: str | None = None
    destination_address: str | None = None
    token_id: str | None = None
    amounts: list[str] = field(default_factory=list)
    fee_level: FeeLevel | None = None
    create_date: datetime | None = None
    update_date: datetime | None = None
    error_reason: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "TransactionInfo":
        def parse_dt(val: str | datetime | None) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            return None

        return cls(
            id=data["id"],
            state=TransactionState(data["state"]),
            blockchain=data.get("blockchain"),
            tx_hash=data.get("txHash"),
            wallet_id=data.get("walletId"),
            source_address=data.get("sourceAddress"),
            destination_address=data.get("destinationAddress"),
            token_id=data.get("tokenId"),
            amounts=data.get("amounts", []),
            fee_level=FeeLevel(data["feeLevel"]) if data.get("feeLevel") else None,
            create_date=parse_dt(data.get("createDate")),
            update_date=parse_dt(data.get("updateDate")),
            error_reason=data.get("errorReason"),
        )

    def is_terminal(self) -> bool:
        return self.state in (
            TransactionState.COMPLETE,
            TransactionState.FAILED,
            TransactionState.CANCELLED,
            TransactionState.CLEARED,
        )

    def is_successful(self) -> bool:
        return self.state in (TransactionState.COMPLETE, TransactionState.CLEARED)


@dataclass
class PaymentRequest:
    """Payment request to be processed by the SDK."""

    wallet_id: str
    recipient: str
    amount: Decimal
    purpose: str | None = None
    idempotency_key: str | None = None
    destination_chain: Network | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("Amount must be positive")
        if not self.recipient:
            raise ValueError("Recipient is required")
        if not self.wallet_id:
            raise ValueError("Wallet ID is required")


@dataclass
class PaymentIntent:
    """A payment intent represents a planned payment."""

    id: str
    wallet_id: str
    recipient: str
    amount: Decimal
    currency: str
    status: PaymentIntentStatus
    created_at: datetime
    expires_at: datetime | None = None
    purpose: str | None = None
    cancel_reason: str | None = None
    reserved_amount: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    client_secret: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "wallet_id": self.wallet_id,
            "recipient": self.recipient,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "purpose": self.purpose,
            "cancel_reason": self.cancel_reason,
            "reserved_amount": str(self.reserved_amount) if self.reserved_amount is not None else None,
            "metadata": self.metadata,
            "client_secret": self.client_secret,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaymentIntent":
        return cls(
            id=data["id"],
            wallet_id=data["wallet_id"],
            recipient=data["recipient"],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            status=PaymentIntentStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            purpose=data.get("purpose"),
            cancel_reason=data.get("cancel_reason"),
            reserved_amount=Decimal(data["reserved_amount"]) if data.get("reserved_amount") else None,
            metadata=data.get("metadata", {}),
            client_secret=data.get("client_secret"),
        )


@dataclass
class PaymentResult:
    """Result of a payment operation."""

    success: bool
    transaction_id: str | None
    blockchain_tx: str | None
    amount: Decimal
    recipient: str
    method: PaymentMethod
    status: PaymentStatus
    guards_passed: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    resource_data: Any = None


@dataclass
class SimulationResult:
    """Result of a payment simulation."""

    would_succeed: bool
    route: PaymentMethod
    recipient_type: str | None = None
    guards_that_would_pass: list[str] = field(default_factory=list)
    guards_that_would_fail: list[str] = field(default_factory=list)
    estimated_fee: Decimal | None = None
    reason: str | None = None

    @property
    def estimated_gas(self) -> Decimal | None:
        """Alias for estimated_fee for API compatibility."""
        return self.estimated_fee

    @property
    def guards_that_pass(self) -> list[str]:
        """Alias for API compatibility with vision document."""
        return self.guards_that_would_pass


@dataclass
class BatchPaymentResult:
    """Result of a batch payment operation."""

    total_count: int
    success_count: int
    failed_count: int
    results: list[PaymentResult]
    transaction_ids: list[str] = field(default_factory=list)


# Token IDs for USDC on different networks (from Circle)
USDC_TOKEN_IDS: dict[Network, str] = {
    # These are Circle's internal token IDs for USDC
    # They need to be obtained from GET /wallets/{id}/balances
    Network.ETH_SEPOLIA: "",
    Network.ETH: "",
    Network.ARB_SEPOLIA: "",
    Network.ARB: "",
    Network.MATIC_AMOY: "",
    Network.MATIC: "",
    Network.SOL_DEVNET: "",
    Network.SOL: "",
}
