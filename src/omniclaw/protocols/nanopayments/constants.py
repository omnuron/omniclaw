"""
Constants for Circle Gateway Nanopayments (x402 v2 via Circle Gateway).

API Reference:
    Base URLs:
        Testnet: https://gateway-api-testnet.circle.com
        Mainnet: https://gateway-api.circle.com

    Endpoints (all relative to base URL):
        GET  /v1/x402/supported  — supported networks in CAIP-2 format
        POST /v1/balances        — check Gateway wallet balance
        POST /v1/x402/verify     — verify payment (debug)
        POST /v1/x402/settle     — settle payment (production)
        GET  /v1/info            — Gateway domain info (human-readable names)

    Balance request format:
        POST /v1/balances
        Body: {"token": "USDC", "sources": [{"domain": 26, "depositor": "0x..."}]}
        domain must be a plain integer (Circle domain ID), NOT an object.

    Supported response format:
        GET /v1/x402/supported
        Returns {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "eip155:5042002", ...}]}
        network field is in CAIP-2 format.
"""

from __future__ import annotations

# =============================================================================
# API ENDPOINTS
# =============================================================================

GATEWAY_API_TESTNET: str = "https://gateway-api-testnet.circle.com"
"""Circle Gateway API base URL for testnet."""

GATEWAY_API_MAINNET: str = "https://gateway-api.circle.com"
"""Circle Gateway API base URL for mainnet."""

GATEWAY_X402_VERIFY_PATH: str = "/v1/x402/verify"
"""Path for the x402 verify endpoint (Circle Gateway)."""

GATEWAY_X402_SETTLE_PATH: str = "/v1/x402/settle"
"""Path for the x402 settle endpoint (Circle Gateway)."""

GATEWAY_X402_SUPPORTED_PATH: str = "/v1/x402/supported"
"""Path for the x402 supported networks endpoint. Returns CAIP-2 networks."""

GATEWAY_INFO_PATH: str = "/v1/info"
"""Path for the Gateway info endpoint (returns human-readable domain info)."""

GATEWAY_BALANCES_PATH: str = "/v1/balances"
"""Path for the balances endpoint."""

# =============================================================================
# x402 PROTOCOL CONSTANTS
# =============================================================================

CIRCLE_BATCHING_NAME: str = "GatewayWalletBatched"
"""
The EIP-712 domain name for Circle Gateway batched payments.

CRITICAL: This MUST be "GatewayWalletBatched" for Circle Gateway.
Using "USD Coin" (the standard USDC EIP-712 domain) will produce
signatures that Circle Gateway rejects.

This is the most common bug in EIP-3009 implementations.
"""

CIRCLE_BATCHING_VERSION: str = "1"
"""Version of the Circle batching scheme."""

CIRCLE_BATCHING_SCHEME: str = "exact"
"""x402 payment scheme for fixed-price payments."""

X402_VERSION: int = 2
"""x402 protocol version used by Circle Gateway."""

# =============================================================================
# TIMING CONSTANTS (in seconds)
# =============================================================================

MAX_TIMEOUT_SECONDS: int = 345600  # 4 days
"""
Maximum timeout for payment authorization validity.
Required by Circle Gateway: must be exactly 4 days (345600 seconds).
"""

MIN_VALID_BEFORE_SECONDS: int = 259200  # 3 days
"""
Minimum validity window for EIP-3009 authorization.
Gateway rejects signatures with validity shorter than 3 days.
"""

DEFAULT_VALID_BEFORE_SECONDS: int = 345600  # 4 days
"""
Default validity window for EIP-3009 authorization.
Set to 4 days to provide ample time for batch settlement.
"""

# =============================================================================
# ROUTING THRESHOLDS
# =============================================================================

DEFAULT_MICRO_PAYMENT_THRESHOLD_USDC: str = "1.00"
"""
Payments below this amount (in USDC) are routed through NanopaymentAdapter.
Above this threshold, standard Circle transfers are used.
"""

DEFAULT_GATEWAY_AUTO_TOPUP_THRESHOLD: str = "1.00"
"""Auto-topup triggers when Gateway balance falls below this amount."""

DEFAULT_GATEWAY_AUTO_TOPUP_AMOUNT: str = "10.00"
"""Amount deposited when auto-topup triggers."""

# =============================================================================
# CACHING
# =============================================================================

SUPPORTED_NETWORKS_CACHE_TTL_SECONDS: int = 3600  # 60 minutes
"""
How long to cache /v1/x402/supported response before refetching.
Circle may update contract addresses, so we refresh periodically.
"""

# =============================================================================
# HTTP CLIENT
# =============================================================================

DEFAULT_HTTP_TIMEOUT_SECONDS: float = 30.0
"""Default timeout for Circle Gateway API requests."""

# =============================================================================
# USDC DECIMAL PRECISION
# =============================================================================

USDC_DECIMAL_PLACES: int = 6
"""Number of decimal places in USDC (1 USDC = 10^6 atomic units)."""


# =============================================================================
# CIRCLE DOMAIN ID TO CAIP-2 NETWORK MAPPING
# =============================================================================

CIRCLE_DOMAIN_TO_CAIP2: dict[int, str] = {
    0: "eip155:1",  # Ethereum mainnet
    1: "eip155:43114",  # Avalanche C-Chain
    2: "eip155:10",  # Optimism
    3: "eip155:42161",  # Arbitrum One
    5: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",  # Solana mainnet
    6: "eip155:8453",  # Base mainnet
    7: "eip155:137",  # Polygon PoS
    10: "eip155:130",  # Unichain mainnet
    13: "eip155:146",  # Sonic (formerly Fantom)
    14: "eip155:480",  # World Chain
    16: "eip155:32",  # Sei
    19: "eip155:9649",  # HyperEVM
    26: "eip155:5042002",  # Arc Testnet
}

CAIP2_TO_CIRCLE_DOMAIN: dict[str, int] = {v: k for k, v in CIRCLE_DOMAIN_TO_CAIP2.items()}
"""Reverse mapping from CAIP-2 to Circle domain ID."""

GATEWAY_WALLET_CONTRACT_EVM: str = "0x0077777d7EBA4688BDeF3E311b846F25870A19B9"
"""Circle GatewayWallet contract address used by supported EVM networks."""

GATEWAY_WALLET_CONTRACTS_CAIP2: dict[str, str] = {
    network: GATEWAY_WALLET_CONTRACT_EVM
    for network in CAIP2_TO_CIRCLE_DOMAIN
    if network.startswith("eip155:")
}
"""Default GatewayWallet contract addresses keyed by CAIP-2 network."""
