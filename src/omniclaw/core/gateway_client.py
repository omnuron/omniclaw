"""
Circle Gateway API client for gasless transfers.

This module provides a client for Circle's Gateway API which enables
off-chain signing of burn intents for gasless USDC transfers.
"""

from __future__ import annotations

import secrets
import struct
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.logging import get_logger
from omniclaw.core.types import Network

if TYPE_CHECKING:
    import httpx


# Gateway domain IDs for supported chains
GATEWAY_DOMAINS = {
    # Mainnet
    Network.ETH: 0,
    Network.AVAX: 1,
    Network.BASE: 6,
    # Testnets
    Network.ETH_SEPOLIA: 0,
    Network.AVAX_FUJI: 1,
    Network.BASE_SEPOLIA: 6,
}

# Reverse mapping for domain -> Network
DOMAIN_TO_NETWORK = {
    0: Network.ETH,
    1: Network.AVAX,
    6: Network.BASE,
}


@dataclass
class TransferSpec:
    """Specification for a Gateway transfer (EIP-712 compatible)."""

    version: int = 1
    source_domain: int = 0
    destination_domain: int = 0
    source_contract: str = ""
    destination_contract: str = ""
    source_token: str = ""
    destination_token: str = ""
    source_depositor: str = ""
    destination_recipient: str = ""
    source_signer: str = ""
    destination_caller: str = ""
    value: int = 0
    salt: str = ""
    hook_data: str = "0x"

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to Gateway API format."""
        return {
            "version": self.version,
            "sourceDomain": self.source_domain,
            "destinationDomain": self.destination_domain,
            "sourceContract": self.source_contract,
            "destinationContract": self.destination_contract,
            "sourceToken": self.source_token,
            "destinationToken": self.destination_token,
            "sourceDepositor": self.source_depositor,
            "destinationRecipient": self.destination_recipient,
            "sourceSigner": self.source_signer,
            "destinationCaller": self.destination_caller,
            "value": str(self.value),
            "salt": self.salt,
            "hookData": self.hook_data,
        }


@dataclass
class BurnIntent:
    """A burn intent for gasless transfer via Gateway."""

    spec: TransferSpec
    max_block_height: int = 2**64 - 1  # Very far in the future
    max_fee: int = 10**18  # 1 USDC max fee (6 decimals, but stored as wei-like)

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to Gateway API format for /transfer endpoint."""
        return {
            "maxBlockHeight": str(self.max_block_height),
            "maxFee": str(self.max_fee),
            "spec": self.spec.to_api_dict(),
        }


@dataclass
class SignedBurnIntent:
    """A signed burn intent ready for Gateway API submission."""

    burn_intent: BurnIntent
    signature: str

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to Gateway API format."""
        return {
            "burnIntent": self.burn_intent.to_api_dict(),
            "signature": self.signature,
        }


@dataclass
class TransferAttestation:
    """Response from Gateway API transfer endpoint."""

    transfer_id: str
    attestation: str
    signature: str
    total_fee: Decimal
    expiration_block: int
    per_intent_fees: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GatewayInfo:
    """Gateway API info response."""

    domains: list[dict[str, Any]]
    supported_chains: list[str] = field(default_factory=list)


@dataclass
class GatewayBalance:
    """Balance for a depositor on a specific domain."""

    domain: int
    balance: Decimal
    chain_name: str = ""


class GatewayAPIClient:
    """
    Client for Circle Gateway API.

    Enables gasless USDC transfers by:
    1. Signing burn intents off-chain (no gas)
    2. Submitting to Gateway API for attestation
    3. Using attestation to mint on destination chain

    Example:
        >>> client = GatewayAPIClient()
        >>> info = await client.info()
        >>> balances = await client.balances("USDC", "0x123...")
    """

    TESTNET_BASE_URL = "https://gateway-api-testnet.circle.com/v1"
    MAINNET_BASE_URL = "https://gateway-api.circle.com/v1"

    # Chain names by domain ID
    CHAIN_NAMES = {
        0: "Ethereum",
        1: "Avalanche",
        6: "Base",
    }

    def __init__(
        self,
        base_url: str | None = None,
        is_testnet: bool = True,
        timeout: float = 30.0,
    ) -> None:
        """
        Initialize Gateway API client.

        Args:
            base_url: Override base URL (uses testnet/mainnet defaults if None)
            is_testnet: Use testnet URL if base_url not provided
            timeout: Request timeout in seconds
        """
        self._base_url = base_url or (
            self.TESTNET_BASE_URL if is_testnet else self.MAINNET_BASE_URL
        )
        self._timeout = timeout
        self._logger = get_logger("gateway_api")
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=self._timeout)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _get(self, path: str) -> dict[str, Any]:
        """Make GET request to Gateway API."""
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        self._logger.debug(f"GET {url}")
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, body: Any) -> dict[str, Any]:
        """Make POST request to Gateway API."""
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        self._logger.debug(f"POST {url}")
        response = await client.post(url, json=body)
        response.raise_for_status()
        return response.json()

    async def info(self) -> GatewayInfo:
        """
        Get Gateway API info.

        Returns supported chains and contract addresses.
        """
        data = await self._get("/info")
        domains = data.get("domains", [])
        chains = [d.get("chain", "") for d in domains]
        return GatewayInfo(domains=domains, supported_chains=chains)

    async def balances(
        self,
        token: str,
        depositor: str,
        domains: list[int] | None = None,
    ) -> list[GatewayBalance]:
        """
        Get unified token balances for a depositor.

        Args:
            token: Token symbol (e.g. "USDC")
            depositor: Depositor address (checksummed)
            domains: Optional list of domain IDs to check

        Returns:
            List of balances per domain
        """
        if domains is None:
            domains = list(self.CHAIN_NAMES.keys())

        body = {
            "token": token,
            "sources": [{"depositor": depositor, "domain": d} for d in domains],
        }
        data = await self._post("/balances", body)

        result = []
        for bal in data.get("balances", []):
            domain = bal.get("domain", 0)
            result.append(
                GatewayBalance(
                    domain=domain,
                    balance=Decimal(bal.get("balance", "0")),
                    chain_name=self.CHAIN_NAMES.get(domain, "Unknown"),
                )
            )
        return result

    async def transfer(
        self,
        signed_intents: list[SignedBurnIntent],
    ) -> TransferAttestation:
        """
        Submit signed burn intents to get transfer attestation.

        This is the core gasless transfer operation:
        1. You sign burn intents off-chain (no gas!)
        2. Submit them here
        3. Receive attestation to use with minter contract

        Args:
            signed_intents: List of signed burn intents

        Returns:
            Transfer attestation for minting
        """
        body = [intent.to_api_dict() for intent in signed_intents]
        data = await self._post("/transfer", body)

        fees = data.get("fees", {})
        return TransferAttestation(
            transfer_id=data.get("transferId", ""),
            attestation=data.get("attestation", ""),
            signature=data.get("signature", ""),
            total_fee=Decimal(fees.get("total", "0")),
            expiration_block=int(data.get("expirationBlock", "0")),
            per_intent_fees=fees.get("perIntent", []),
        )

    async def estimate_transfer(
        self,
        source_domain: int,
        destination_domain: int,
        amount: int,
    ) -> dict[str, Any]:
        """
        Estimate fees for a transfer.

        Args:
            source_domain: Source chain domain ID
            destination_domain: Destination chain domain ID
            amount: Amount in smallest units

        Returns:
            Fee estimation with expiration info
        """
        body = {
            "sourceDomain": source_domain,
            "destinationDomain": destination_domain,
            "value": str(amount),
        }
        return await self._post("/estimate", body)


def generate_salt() -> str:
    """Generate a random 32-byte salt for burn intent."""
    return "0x" + secrets.token_hex(32)


def usdc_to_units(amount: Decimal) -> int:
    """Convert USDC decimal amount to smallest units (6 decimals)."""
    return int(amount * Decimal("1000000"))


def address_to_bytes32(address: str) -> str:
    """Convert EVM address to 32-byte hex string for Gateway API."""
    # Remove 0x prefix, pad to 64 chars (32 bytes)
    addr = address.lower().replace("0x", "")
    return "0x" + addr.zfill(64)


def get_domain_for_network(network: Network) -> int | None:
    """Get Gateway domain ID for a network."""
    return GATEWAY_DOMAINS.get(network)


def is_gateway_supported(network: Network) -> bool:
    """Check if network is supported by Gateway."""
    return network in GATEWAY_DOMAINS
