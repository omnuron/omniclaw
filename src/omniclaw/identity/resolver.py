"""
ERC-8004 Identity Resolver.

Resolves on-chain agent identities from the ERC-8004 Identity Registry
and fetches off-chain agent registration files from agentURI.

On-chain reads are performed via ERC8004Provider (JSON-RPC eth_call),
NOT via Circle SDK (which is for wallet management, not registry reads).
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

import httpx

from omniclaw.core.erc8004 import (
    get_identity_registry,
    is_erc8004_supported,
)
from omniclaw.core.logging import get_logger
from omniclaw.identity.types import AgentIdentity, AgentService

if TYPE_CHECKING:
    from omniclaw.core.types import Network
    from omniclaw.trust.provider import ERC8004Provider

logger = get_logger("identity.resolver")


class IdentityResolver:
    """
    Resolves ERC-8004 agent identities.

    Uses ERC8004Provider for on-chain reads (eth_call to Identity/Reputation
    registries on ETH mainnet, Base Sepolia, etc.) and httpx for fetching
    off-chain agent registration files (HTTPS, IPFS, base64 data URIs).
    """

    METADATA_FETCH_TIMEOUT = 3.0  # seconds (spec: 3s timeout for agentURI)
    IPFS_GATEWAYS = [
        "https://ipfs.io/ipfs/",
        "https://dweb.link/ipfs/",
        "https://w3s.link/ipfs/",
    ]

    def __init__(
        self,
        provider: ERC8004Provider | None = None,
        wallet_service: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            provider: ERC8004Provider for on-chain reads (preferred)
            wallet_service: Legacy Circle SDK fallback (deprecated for reads)
            http_client: Shared httpx client for metadata fetches
        """
        self._provider = provider
        self._wallet_service = wallet_service
        self._http_client = http_client
        self._owns_http_client = False

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client for metadata fetches."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.METADATA_FETCH_TIMEOUT)
            self._owns_http_client = True
        return self._http_client

    async def close(self) -> None:
        """Close owned HTTP client."""
        if self._owns_http_client and self._http_client:
            await self._http_client.aclose()

    # ─── On-Chain Lookups ────────────────────────────────────────────

    async def resolve_by_id(
        self,
        agent_id: int,
        network: Network | str,
    ) -> AgentIdentity | None:
        """
        Resolve an agent by its ERC-8004 agent ID (token ID).

        1. Reads ownerOf(agentId) → wallet address
        2. Reads tokenURI(agentId) → agentURI
        3. Reads getAgentWallet(agentId) → payment address
        4. Fetches + parses the off-chain registration file
        """
        network_key = network.value if hasattr(network, "value") else str(network).upper()

        if not is_erc8004_supported(network_key):
            logger.debug(f"ERC-8004 not supported on {network_key}")
            return None

        try:
            # ── On-chain reads via ERC8004Provider ──
            if self._provider:
                owner_address = await self._provider.get_agent_owner(agent_id, network_key)
                if not owner_address:
                    logger.debug(f"Agent {agent_id} not found in Identity Registry on {network_key}")
                    return None

                agent_uri = await self._provider.get_agent_uri(agent_id, network_key)
                agent_wallet = await self._provider.get_agent_wallet(agent_id, network_key)

            # ── Fallback: Circle SDK (legacy, for backwards compatibility) ──
            elif self._wallet_service:
                owner_address = await self._read_contract_legacy(
                    network, get_identity_registry(network_key),
                    "ownerOf(uint256)", [str(agent_id)],
                )
                if not owner_address:
                    return None
                agent_uri = await self._read_contract_legacy(
                    network, get_identity_registry(network_key),
                    "tokenURI(uint256)", [str(agent_id)],
                )
                agent_wallet = await self._read_contract_legacy(
                    network, get_identity_registry(network_key),
                    "getAgentWallet(uint256)", [str(agent_id)],
                )
            else:
                logger.debug("No provider or wallet service — skipping on-chain lookups")
                return None

            # ── Build identity from on-chain data ──
            identity = AgentIdentity(
                agent_id=agent_id,
                wallet_address=owner_address,
                agent_wallet=agent_wallet,
            )

            # ── Fetch off-chain registration file ──
            if agent_uri:
                registration_data = await self.fetch_metadata(agent_uri)
                if registration_data:
                    # Validate registration file type (EIP-8004 §3)
                    reg_type = registration_data.get("type", "")
                    if reg_type and "eip-8004" not in reg_type.lower() and "registration" not in reg_type.lower():
                        logger.warning(
                            f"Agent {agent_id} registration file has unexpected type: {reg_type}"
                        )
                    identity = AgentIdentity.from_registration_file(
                        agent_id=agent_id,
                        wallet_address=owner_address,
                        data=registration_data,
                    )
                    identity.agent_wallet = agent_wallet

            return identity

        except Exception as e:
            logger.error(f"Failed to resolve agent {agent_id}: {e}")
            return None

    async def resolve_by_address(
        self,
        wallet_address: str,
        network: Network | str,
    ) -> AgentIdentity | None:
        """
        Resolve an agent by wallet address.

        Uses ERC-721 balanceOf + tokenOfOwnerByIndex to find the first
        agent NFT owned by this address.
        """
        network_key = network.value if hasattr(network, "value") else str(network).upper()

        if not is_erc8004_supported(network_key):
            return None

        try:
            if self._provider:
                balance = await self._provider.get_balance_of(wallet_address, network_key)
                if balance > 0:
                    token_id = await self._provider.get_token_of_owner(wallet_address, 0, network_key)
                    if token_id is not None:
                        return await self.resolve_by_id(token_id, network)

            elif self._wallet_service:
                # Legacy fallback
                registry_address = get_identity_registry(network_key)
                balance = await self._read_contract_legacy(
                    network, registry_address, "balanceOf(address)", [wallet_address],
                )
                if balance and int(balance) > 0:
                    token_id = await self._read_contract_legacy(
                        network, registry_address,
                        "tokenOfOwnerByIndex(address,uint256)",
                        [wallet_address, "0"],
                    )
                    if token_id:
                        return await self.resolve_by_id(int(token_id), network)

        except Exception as e:
            logger.debug(f"Address lookup failed for {wallet_address}: {e}")

        return None

    # ─── Metadata Fetching ───────────────────────────────────────────

    async def fetch_metadata(self, agent_uri: str) -> dict[str, Any] | None:
        """
        Fetch and parse an agent registration file from agentURI.

        Supports:
        - HTTPS URLs
        - IPFS URIs (via public gateway with fallback)
        - Base64 data URIs (data:application/json;base64,...)
        """
        try:
            if agent_uri.startswith("data:"):
                return self._parse_data_uri(agent_uri)
            elif agent_uri.startswith("ipfs://"):
                return await self._fetch_ipfs(agent_uri)
            elif agent_uri.startswith("http://") or agent_uri.startswith("https://"):
                return await self._fetch_https(agent_uri)
            else:
                logger.warning(f"Unsupported agentURI scheme: {agent_uri[:50]}")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch metadata from {agent_uri[:80]}: {e}")
            return None

    def _parse_data_uri(self, uri: str) -> dict[str, Any] | None:
        """Parse base64-encoded data URI."""
        try:
            # Format: data:application/json;base64,eyJ0eXBlIjoi...
            _, encoded = uri.split(",", 1)
            decoded = base64.b64decode(encoded)
            return json.loads(decoded)
        except Exception as e:
            logger.error(f"Failed to parse data URI: {e}")
            return None

    async def _fetch_ipfs(self, uri: str) -> dict[str, Any] | None:
        """Fetch from IPFS via public gateway with multiple gateway fallback."""
        cid = uri.replace("ipfs://", "")
        for gateway in self.IPFS_GATEWAYS:
            result = await self._fetch_https(f"{gateway}{cid}")
            if result is not None:
                return result
        logger.warning(f"All IPFS gateways failed for CID: {cid[:40]}")
        return None

    async def _fetch_https(self, url: str) -> dict[str, Any] | None:
        """Fetch JSON from HTTPS URL."""
        client = await self._get_http_client()
        try:
            response = await client.get(url, timeout=self.METADATA_FETCH_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            logger.warning(f"Metadata fetch timed out: {url}")
            return None
        except Exception as e:
            logger.error(f"Metadata fetch failed: {e}")
            return None

    # ─── Legacy Circle SDK Contract Reads ────────────────────────────

    async def _read_contract_legacy(
        self,
        network: Any,
        contract_address: str | None,
        function_sig: str,
        params: list[str],
    ) -> str | None:
        """
        Read from an ERC-8004 contract via Circle SDK (legacy fallback).

        Deprecated: Use ERC8004Provider for production reads.
        """
        if not contract_address or not self._wallet_service:
            return None

        try:
            circle = getattr(self._wallet_service, "_circle", None)
            if circle and hasattr(circle, "read_contract"):
                result = circle.read_contract(
                    contract_address=contract_address,
                    abi_function_signature=function_sig,
                    abi_parameters=params,
                    blockchain=network.value if hasattr(network, "value") else str(network),
                )
                return result
        except Exception as e:
            logger.debug(f"Legacy contract read failed ({function_sig}): {e}")
        return None

    # ─── Endpoint Domain Verification (EIP-8004 §5 — Optional) ──────

    async def verify_endpoint_domain(
        self,
        endpoint_url: str,
        agent_id: int,
        agent_registry: str,
    ) -> bool:
        """
        Verify that an HTTPS endpoint domain is controlled by the agent owner.

        Per EIP-8004 §5: An agent MAY optionally prove control of an HTTPS
        endpoint by publishing a `.well-known/agent-registration.json` file
        containing a `registrations` list with a matching `agentRegistry`
        and `agentId`.

        If the endpoint-domain is the same domain serving the agentURI
        registration file, this additional check is not needed.

        Args:
            endpoint_url: The HTTPS endpoint URL to verify
            agent_id: The agent's tokenId
            agent_registry: The agent's registry string (e.g., eip155:1:0x742...)

        Returns:
            True if the domain publishes a valid registration matching the agent
        """
        if not endpoint_url or not endpoint_url.startswith("https://"):
            return False

        try:
            # Extract domain from endpoint URL
            from urllib.parse import urlparse
            parsed = urlparse(endpoint_url)
            domain = parsed.netloc
            if not domain:
                return False

            well_known_url = f"https://{domain}/.well-known/agent-registration.json"

            async with httpx.AsyncClient(timeout=self.METADATA_FETCH_TIMEOUT) as client:
                resp = await client.get(well_known_url)
                if resp.status_code != 200:
                    logger.debug(
                        f"Endpoint domain verification: {well_known_url} returned {resp.status_code}"
                    )
                    return False

                data = resp.json()
                registrations = data.get("registrations", [])

                # Check if any registration matches our agent
                for reg in registrations:
                    if (
                        reg.get("agentId") == agent_id
                        and reg.get("agentRegistry") == agent_registry
                    ):
                        logger.info(
                            f"Endpoint domain verified: {domain} for agent {agent_id}"
                        )
                        return True

                logger.debug(
                    f"Endpoint domain verification: no matching registration "
                    f"for agent {agent_id} in {well_known_url}"
                )
                return False

        except Exception as e:
            logger.debug(f"Endpoint domain verification failed for {endpoint_url}: {e}")
            return False

    async def verify_all_endpoints(
        self,
        identity: AgentIdentity,
    ) -> list[str]:
        """
        Verify all HTTPS endpoints in an agent's registration file.

        Returns a list of verified endpoint domains. Does NOT modify the
        identity object — the caller decides how to use the results.

        Args:
            identity: The agent's resolved identity

        Returns:
            List of verified endpoint domain strings (e.g., ["agent.example.com"])
        """
        if not identity.services or not identity.agent_registry:
            return []

        verified: list[str] = []
        for service in identity.services:
            endpoint = service.endpoint
            if endpoint and endpoint.startswith("https://"):
                is_verified = await self.verify_endpoint_domain(
                    endpoint_url=endpoint,
                    agent_id=identity.agent_id,
                    agent_registry=identity.agent_registry,
                )
                if is_verified:
                    from urllib.parse import urlparse
                    verified.append(urlparse(endpoint).netloc)

        return verified


__all__ = ["IdentityResolver"]

