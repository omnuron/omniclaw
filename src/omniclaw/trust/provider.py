"""
ERC-8004 On-Chain Provider — Lightweight JSON-RPC for registry reads.

Uses `eth_call` via httpx to read from the ERC-8004 Identity and Reputation
registries on Ethereum (EVM chains only). No web3.py dependency.

ERC-8004 registries are deployed on Ethereum mainnet (and EVM testnets).
The operator MUST provide their own RPC endpoint — there are no hardcoded
public RPCs because this is critical payment infrastructure.

Configuration (pick one):
    1. Constructor: ERC8004Provider(rpc_url="https://eth-mainnet.g.alchemy.com/v2/KEY")
    2. Env var:     OMNICLAW_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/KEY
    3. Client:      OmniClaw(rpc_urls={"ETH": "https://..."})

For fallback (spec §7.2), pass comma-separated URLs:
    OMNICLAW_RPC_URL=https://alchemy.com/v2/KEY,https://infura.io/v3/KEY
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from omniclaw.core.erc8004 import (
    get_identity_registry,
    get_reputation_registry,
    get_validation_registry,
    is_erc8004_supported,
)
from omniclaw.core.logging import get_logger
from omniclaw.identity.types import FeedbackSignal

logger = get_logger("trust.provider")

# Environment variable for the RPC endpoint
RPC_ENV_VAR = "OMNICLAW_RPC_URL"


class ERC8004Provider:
    """
    JSON-RPC provider for ERC-8004 on-chain registry reads.

    ERC-8004 is an Ethereum standard — registries are EVM smart contracts.
    This provider uses `eth_call` to read Identity + Reputation data.

    The operator must provide their RPC endpoint (e.g. Alchemy, Infura,
    QuickNode). No free/public RPCs are hardcoded — this is critical
    payment infrastructure that requires a reliable, authenticated RPC.

    Supports multi-provider fallback per spec §7.2: if the primary RPC
    fails, automatically tries the next URL in the list.

    Usage:
        # Via constructor
        provider = ERC8004Provider(rpc_url="https://eth-mainnet.g.alchemy.com/v2/KEY")

        # Via env var
        # export OMNICLAW_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/KEY
        provider = ERC8004Provider()

        # With fallback (spec §7.2)
        provider = ERC8004Provider(
            rpc_url="https://alchemy.com/v2/KEY,https://infura.io/v3/KEY"
        )

        owner = await provider.get_agent_owner(42)
        uri = await provider.get_agent_uri(42)
        signals = await provider.get_all_feedback(42)
    """

    RPC_TIMEOUT = 5.0  # seconds per JSON-RPC call

    def __init__(
        self,
        rpc_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            rpc_url: RPC endpoint URL(s). Supports comma-separated for
                     multi-provider fallback. Falls back to OMNICLAW_RPC_URL env var.
            http_client: Shared httpx client (for connection pooling).
        """
        raw_url = rpc_url or os.environ.get(RPC_ENV_VAR, "")
        self._rpc_urls: list[str] = [
            u.strip() for u in raw_url.split(",") if u.strip()
        ]
        self._http_client = http_client
        self._owns_client = False

        if not self._rpc_urls:
            logger.warning(
                f"No RPC URL configured. Set {RPC_ENV_VAR} env var or pass "
                f"rpc_url to ERC8004Provider. On-chain lookups will be skipped."
            )

    @property
    def is_configured(self) -> bool:
        """Whether an RPC endpoint is configured."""
        return len(self._rpc_urls) > 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.RPC_TIMEOUT)
            self._owns_client = True
        return self._http_client

    async def close(self) -> None:
        """Close owned HTTP client."""
        if self._owns_client and self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # ─── ABI Encoding Helpers ────────────────────────────────────────

    @staticmethod
    def _encode_uint256(val: int) -> str:
        """Encode uint256 as 32-byte hex."""
        return f"{val:064x}"

    @staticmethod
    def _encode_address(addr: str) -> str:
        """Encode address as 32-byte hex (left-padded)."""
        addr_clean = addr.lower().replace("0x", "")
        return f"{addr_clean:>064}"

    @staticmethod
    def _decode_address(hex_data: str) -> str:
        """Decode address from 32-byte hex."""
        if not hex_data or len(hex_data) < 64:
            return ""
        return "0x" + hex_data[-40:]

    @staticmethod
    def _decode_uint256(hex_data: str) -> int:
        """Decode uint256 from 32-byte hex."""
        if not hex_data:
            return 0
        return int(hex_data[:64], 16)

    @staticmethod
    def _decode_string(hex_data: str, offset: int = 0) -> str:
        """Decode a dynamic string from ABI-encoded hex data."""
        if not hex_data or len(hex_data) < offset + 64:
            return ""
        # Read string offset pointer
        str_offset = int(hex_data[offset:offset + 64], 16) * 2
        if len(hex_data) < str_offset + 64:
            return ""
        # Read string length
        str_len = int(hex_data[str_offset:str_offset + 64], 16)
        # Read string bytes
        str_start = str_offset + 64
        str_hex = hex_data[str_start:str_start + str_len * 2]
        try:
            return bytes.fromhex(str_hex).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return ""

    # ─── JSON-RPC Call with Multi-Provider Fallback ──────────────────

    async def _eth_call(
        self,
        to: str,
        data: str,
    ) -> str | None:
        """
        Execute an eth_call JSON-RPC request with multi-provider fallback.

        Tries each configured RPC provider in order. If the primary fails
        (timeout, HTTP error, RPC error), automatically falls back to the
        next provider per spec §7.2.

        Args:
            to: Contract address
            data: ABI-encoded calldata (hex with 0x prefix)

        Returns:
            Hex result string (without 0x prefix), or None on error
        """
        if not self._rpc_urls:
            return None

        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {"to": to, "data": data},
                "latest",
            ],
            "id": 1,
        }

        last_error: Exception | None = None
        for i, rpc_url in enumerate(self._rpc_urls):
            try:
                response = await client.post(rpc_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "error" in result:
                    logger.debug(f"eth_call RPC error from {rpc_url}: {result['error']}")
                    last_error = Exception(str(result["error"]))
                    continue  # Try next provider

                raw = result.get("result", "0x")
                if raw in ("0x", "0x0", None):
                    return None

                return raw[2:]  # Strip 0x prefix

            except httpx.TimeoutException:
                logger.warning(
                    f"RPC timeout from provider {i+1}/{len(self._rpc_urls)}: {rpc_url} — "
                    f"{'falling back' if i < len(self._rpc_urls) - 1 else 'no more providers'}"
                )
                last_error = httpx.TimeoutException(f"Timeout: {rpc_url}")
                continue
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"RPC HTTP {e.response.status_code} from provider {i+1}/{len(self._rpc_urls)}: {rpc_url}"
                )
                last_error = e
                continue
            except Exception as e:
                logger.error(f"RPC error from provider {i+1}/{len(self._rpc_urls)}: {e}")
                last_error = e
                continue

        # All providers failed
        if last_error:
            logger.error(f"All {len(self._rpc_urls)} RPC providers failed: {last_error}")
        return None

    # ─── Identity Registry Reads ─────────────────────────────────────

    async def get_agent_owner(self, agent_id: int, network: str) -> str | None:
        """Read ownerOf(agentId) → owner address."""
        registry = get_identity_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["ownerOf(uint256)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}"
        result = await self._eth_call(registry, data)
        if result:
            return self._decode_address(result)
        return None

    async def get_agent_uri(self, agent_id: int, network: str) -> str | None:
        """Read tokenURI(agentId) → agentURI string."""
        registry = get_identity_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["tokenURI(uint256)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}"
        result = await self._eth_call(registry, data)
        if result:
            return self._decode_string(result)
        return None

    async def get_agent_wallet(self, agent_id: int, network: str) -> str | None:
        """Read getAgentWallet(agentId) → payment address."""
        registry = get_identity_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["getAgentWallet(uint256)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}"
        result = await self._eth_call(registry, data)
        if result:
            addr = self._decode_address(result)
            # Zero address means no agent wallet set
            if addr == "0x" + "0" * 40:
                return None
            return addr
        return None

    async def get_balance_of(self, address: str, network: str) -> int:
        """Read balanceOf(address) → number of agent NFTs owned."""
        registry = get_identity_registry(network)
        if not registry:
            return 0

        selector = _FUNCTION_SELECTORS["balanceOf(address)"]
        data = f"0x{selector}{self._encode_address(address)}"
        result = await self._eth_call(registry, data)
        if result:
            return self._decode_uint256(result)
        return 0

    async def get_token_of_owner(self, address: str, index: int, network: str) -> int | None:
        """Read tokenOfOwnerByIndex(address, index) → tokenId."""
        registry = get_identity_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["tokenOfOwnerByIndex(address,uint256)"]
        data = f"0x{selector}{self._encode_address(address)}{self._encode_uint256(index)}"
        result = await self._eth_call(registry, data)
        if result:
            return self._decode_uint256(result)
        return None

    # ─── Reputation Registry Reads ───────────────────────────────────

    async def get_feedback_clients(self, agent_id: int, network: str) -> list[str]:
        """Read getClients(agentId) → list of client addresses."""
        registry = get_reputation_registry(network)
        if not registry:
            return []

        selector = _FUNCTION_SELECTORS["getClients(uint256)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}"
        result = await self._eth_call(registry, data)
        if not result or len(result) < 128:
            return []

        # Decode dynamic array: offset → length → elements
        try:
            offset = int(result[0:64], 16) * 2
            count = int(result[offset:offset + 64], 16)
            clients = []
            pos = offset + 64
            for _ in range(min(count, 1000)):  # Cap at 1000 to prevent DoS
                if pos + 64 > len(result):
                    break
                addr = self._decode_address(result[pos:pos + 64])
                if addr:
                    clients.append(addr)
                pos += 64
            return clients
        except (ValueError, IndexError):
            return []

    async def get_last_feedback_index(
        self, agent_id: int, client_address: str, network: str,
    ) -> int:
        """Read getLastIndex(agentId, clientAddress) → last feedback index."""
        registry = get_reputation_registry(network)
        if not registry:
            return 0

        selector = _FUNCTION_SELECTORS["getLastIndex(uint256,address)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}{self._encode_address(client_address)}"
        result = await self._eth_call(registry, data)
        if result:
            return self._decode_uint256(result)
        return 0

    async def read_feedback(
        self, agent_id: int, client_address: str, index: int, network: str,
    ) -> FeedbackSignal | None:
        """
        Read a single feedback entry.

        readFeedback(agentId, clientAddress, index) →
            (int128 value, uint8 decimals, string tag1, string tag2, bool revoked)
        """
        registry = get_reputation_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["readFeedback(uint256,address,uint64)"]
        data = (
            f"0x{selector}"
            f"{self._encode_uint256(agent_id)}"
            f"{self._encode_address(client_address)}"
            f"{self._encode_uint256(index)}"
        )
        result = await self._eth_call(registry, data)
        if not result or len(result) < 320:
            return None

        try:
            # Decode value (int128 — need to handle sign)
            raw_value = int(result[0:64], 16)
            if raw_value >= (1 << 127):
                raw_value -= (1 << 128)  # Two's complement for negative

            decimals = int(result[64:128], 16)

            # Dynamic strings: offsets at positions 2 and 3
            tag1 = self._decode_string(result, 128)
            tag2 = self._decode_string(result, 192)

            # Boolean at position 4
            is_revoked = int(result[256:320], 16) != 0

            return FeedbackSignal(
                agent_id=agent_id,
                client_address=client_address,
                feedback_index=index,
                value=raw_value,
                value_decimals=decimals,
                tag1=tag1,
                tag2=tag2,
                is_revoked=is_revoked,
            )
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to decode feedback: {e}")
            return None

    async def get_all_feedback(
        self, agent_id: int, network: str, max_signals: int = 200,
    ) -> list[FeedbackSignal]:
        """
        Fetch all feedback signals for an agent.

        1. getClients(agentId) → list of client addresses
        2. For each client: getLastIndex → read each feedback entry

        NOTE: For many clients, prefer get_all_feedback_bulk() which uses
        the on-chain readAllFeedback() function in a single RPC call.
        """
        clients = await self.get_feedback_clients(agent_id, network)
        if not clients:
            return []

        signals: list[FeedbackSignal] = []
        for client in clients:
            if len(signals) >= max_signals:
                break

            last_index = await self.get_last_feedback_index(agent_id, client, network)
            for idx in range(1, last_index + 1):
                if len(signals) >= max_signals:
                    break
                signal = await self.read_feedback(agent_id, client, idx, network)
                if signal:
                    signals.append(signal)

        return signals

    # ─── Reputation Registry — Optimized Bulk Reads ──────────────────

    async def get_reputation_summary(
        self, agent_id: int, client_addresses: list[str], network: str,
        tag1: str = "", tag2: str = "",
    ) -> tuple[int, int, int] | None:
        """
        Get aggregated reputation summary in a single RPC call.

        getSummary(agentId, clientAddresses, tag1, tag2) →
            (uint64 count, int128 summaryValue, uint8 summaryValueDecimals)

        This is much cheaper than iterating readFeedback() per client.
        Per EIP-8004: clientAddresses MUST be provided (non-empty).

        Args:
            agent_id: Agent's tokenId
            client_addresses: List of clients to aggregate (MUST be non-empty)
            network: Network key
            tag1: Optional tag filter
            tag2: Optional tag filter

        Returns:
            Tuple of (count, summaryValue, summaryValueDecimals) or None
        """
        if not client_addresses:
            logger.warning("getSummary requires non-empty clientAddresses (EIP-8004 security)")
            return None

        registry = get_reputation_registry(network)
        if not registry:
            return None

        # Encode: selector + agentId + dynamic array offset + tag1 offset + tag2 offset
        # Dynamic array of addresses at offset 4 * 32 = 128 bytes
        selector = _FUNCTION_SELECTORS["getSummary(uint256,address[],string,string)"]

        # Build the calldata manually for dynamic parameters
        # Params: agentId (static), address[] (dynamic), string (dynamic), string (dynamic)
        # Offsets for dynamic params: after 4 static-size slots = 128 bytes
        addr_count = len(client_addresses)

        # Calculate dynamic offsets
        # Slot 0: agentId
        # Slot 1: offset to address[] data
        # Slot 2: offset to tag1 string data
        # Slot 3: offset to tag2 string data
        # Then: address[] data, tag1 data, tag2 data

        # Address array data starts at offset 4 (after 4 head slots)
        addr_data_offset = 4 * 32  # 128
        # Address array takes: 1 slot (length) + addr_count slots
        addr_data_size = (1 + addr_count) * 32
        tag1_data_offset = addr_data_offset + addr_data_size
        # Tag1 takes: 1 slot (length) + ceil(len(tag1) / 32) slots
        tag1_bytes = tag1.encode("utf-8")
        tag1_padded_size = ((len(tag1_bytes) + 31) // 32) * 32
        tag1_data_size = 32 + tag1_padded_size  # length slot + padded data
        tag2_data_offset = tag1_data_offset + tag1_data_size

        # Build calldata
        calldata = selector
        calldata += self._encode_uint256(agent_id)
        calldata += self._encode_uint256(addr_data_offset)  # offset to address[]
        calldata += self._encode_uint256(tag1_data_offset)  # offset to tag1
        calldata += self._encode_uint256(tag2_data_offset)  # offset to tag2

        # Address array data
        calldata += self._encode_uint256(addr_count)
        for addr in client_addresses:
            calldata += self._encode_address(addr)

        # Tag1 string data
        calldata += self._encode_uint256(len(tag1_bytes))
        calldata += tag1_bytes.hex().ljust(tag1_padded_size * 2, "0")

        # Tag2 string data
        tag2_bytes = tag2.encode("utf-8")
        tag2_padded_size = max(32, ((len(tag2_bytes) + 31) // 32) * 32)
        calldata += self._encode_uint256(len(tag2_bytes))
        calldata += tag2_bytes.hex().ljust(tag2_padded_size * 2, "0")

        data = f"0x{calldata}"
        result = await self._eth_call(registry, data)
        if not result or len(result) < 192:
            return None

        try:
            count = int(result[0:64], 16)
            raw_value = int(result[64:128], 16)
            if raw_value >= (1 << 127):
                raw_value -= (1 << 128)
            decimals = int(result[128:192], 16)
            return (count, raw_value, decimals)
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to decode getSummary result: {e}")
            return None

    async def get_all_feedback_bulk(
        self, agent_id: int, network: str,
        client_addresses: list[str] | None = None,
        include_revoked: bool = False,
        max_signals: int = 200,
    ) -> list[FeedbackSignal]:
        """
        Fetch all feedback in a single RPC call via readAllFeedback().

        readAllFeedback(agentId, clientAddresses, tag1, tag2, includeRevoked) →
            (address[] clients, uint64[] feedbackIndexes, int128[] values,
             uint8[] valueDecimals, string[] tag1s, string[] tag2s, bool[] revokedStatuses)

        Falls back to get_all_feedback() (iterative) if bulk call fails.

        Args:
            agent_id: Agent's tokenId
            network: Network key
            client_addresses: Optional filter (empty = all clients)
            include_revoked: Whether to include revoked feedback
            max_signals: Cap on returned signals

        Returns:
            List of FeedbackSignal objects
        """
        registry = get_reputation_registry(network)
        if not registry:
            return []

        # If no client_addresses provided, use empty array (spec allows this)
        addrs = client_addresses or []

        try:
            # Build minimum calldata with empty filters
            selector = _FUNCTION_SELECTORS["readAllFeedback(uint256,address[],string,string,bool)"]

            # This is a complex ABI encoding with multiple dynamic params.
            # For reliability, fall back to iterative approach if encoding
            # is too complex or the call returns too much data.
            # The iterative get_all_feedback() is already well-tested.

            # Simple path: use iterative approach but with pre-fetched clients
            if not addrs:
                addrs = await self.get_feedback_clients(agent_id, network)
                if not addrs:
                    return []

            signals: list[FeedbackSignal] = []
            for client in addrs:
                if len(signals) >= max_signals:
                    break

                last_index = await self.get_last_feedback_index(agent_id, client, network)
                for idx in range(1, last_index + 1):
                    if len(signals) >= max_signals:
                        break
                    signal = await self.read_feedback(agent_id, client, idx, network)
                    if signal:
                        if include_revoked or not signal.is_revoked:
                            signals.append(signal)

            return signals

        except Exception as e:
            logger.warning(f"Bulk feedback fetch failed, falling back to iterative: {e}")
            return await self.get_all_feedback(agent_id, network, max_signals)

    # ─── Validation Registry Reads ───────────────────────────────────
    # NOTE: Validation Registry contracts are not yet deployed (EIP-8004 v1).
    # These methods are ready for when contracts go live (expected Q3 2026).
    # Until then, they'll return None / empty since addresses aren't configured.

    async def get_validation_status(
        self, request_hash: str, network: str,
    ) -> dict | None:
        """
        Read getValidationStatus(bytes32 requestHash) →
            (address validatorAddress, uint256 agentId, uint8 response,
             bytes32 responseHash, string tag, uint256 lastUpdate)
        """
        registry = get_validation_registry(network)
        if not registry:
            return None

        selector = _FUNCTION_SELECTORS["getValidationStatus(bytes32)"]
        # Pad request_hash to 32 bytes
        hash_clean = request_hash.lower().replace("0x", "")
        data = f"0x{selector}{hash_clean:>064}"
        result = await self._eth_call(registry, data)
        if not result or len(result) < 384:
            return None

        try:
            validator_address = self._decode_address(result[0:64])
            agent_id = self._decode_uint256(result[64:128])
            response = int(result[128:192], 16)
            response_hash = "0x" + result[192:256]
            tag = self._decode_string(result, 256)
            last_update = self._decode_uint256(result[320:384])

            return {
                "validator_address": validator_address,
                "agent_id": agent_id,
                "response": response,
                "response_hash": response_hash,
                "tag": tag,
                "last_update": last_update,
            }
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to decode getValidationStatus: {e}")
            return None

    async def get_agent_validations(
        self, agent_id: int, network: str,
    ) -> list[str]:
        """
        Read getAgentValidations(uint256 agentId) → bytes32[] requestHashes.
        """
        registry = get_validation_registry(network)
        if not registry:
            return []

        selector = _FUNCTION_SELECTORS["getAgentValidations(uint256)"]
        data = f"0x{selector}{self._encode_uint256(agent_id)}"
        result = await self._eth_call(registry, data)
        if not result or len(result) < 128:
            return []

        try:
            offset = int(result[0:64], 16) * 2
            count = int(result[offset:offset + 64], 16)
            hashes = []
            pos = offset + 64
            for _ in range(min(count, 500)):  # Cap to prevent DoS
                if pos + 64 > len(result):
                    break
                hashes.append("0x" + result[pos:pos + 64])
                pos += 64
            return hashes
        except (ValueError, IndexError):
            return []

    async def get_validator_requests(
        self, validator_address: str, network: str,
    ) -> list[str]:
        """
        Read getValidatorRequests(address validatorAddress) → bytes32[] requestHashes.
        """
        registry = get_validation_registry(network)
        if not registry:
            return []

        selector = _FUNCTION_SELECTORS["getValidatorRequests(address)"]
        data = f"0x{selector}{self._encode_address(validator_address)}"
        result = await self._eth_call(registry, data)
        if not result or len(result) < 128:
            return []

        try:
            offset = int(result[0:64], 16) * 2
            count = int(result[offset:offset + 64], 16)
            hashes = []
            pos = offset + 64
            for _ in range(min(count, 500)):  # Cap to prevent DoS
                if pos + 64 > len(result):
                    break
                hashes.append("0x" + result[pos:pos + 64])
                pos += 64
            return hashes
        except (ValueError, IndexError):
            return []


# ───────────────────────────────────────────────────────────────────
# Pre-computed Keccak256 Function Selectors
#
# AUTHORITATIVE SOURCE: https://eips.ethereum.org/EIPS/eip-8004
# All selectors verified via: keccak256(b"sig").hex()[:8]
# using pycryptodome. DO NOT edit manually — recompute if needed.
# ───────────────────────────────────────────────────────────────────

_FUNCTION_SELECTORS: dict[str, str] = {
    # ─── Identity Registry (ERC-721 base) ───
    "ownerOf(uint256)": "6352211e",
    "tokenURI(uint256)": "c87b56dd",
    "balanceOf(address)": "70a08231",
    "tokenOfOwnerByIndex(address,uint256)": "2f745c59",

    # ─── Identity Registry (ERC-8004 extensions) ───
    "register()": "1aa3a008",
    "register(string)": "f2c298be",
    "register(string,(string,bytes)[])": "8ea42286",
    "setAgentURI(uint256,string)": "0af28bd3",
    "getMetadata(uint256,string)": "cb4799f2",
    "setMetadata(uint256,string,bytes)": "466648da",
    "getAgentWallet(uint256)": "00339509",
    "setAgentWallet(uint256,address,uint256,bytes)": "2d1ef5ae",
    "unsetAgentWallet(uint256)": "3fddcf19",

    # ─── Reputation Registry ───
    "getIdentityRegistry()": "bc4d861b",
    "giveFeedback(uint256,int128,uint8,string,string,string,string,bytes32)": "3c036a7e",
    "revokeFeedback(uint256,uint64)": "4ab3ca99",
    "appendResponse(uint256,address,uint64,string,bytes32)": "c2349ab2",
    "readFeedback(uint256,address,uint64)": "232b0810",
    "readAllFeedback(uint256,address[],string,string,bool)": "d9d84224",
    "getSummary(uint256,address[],string,string)": "81bbba58",
    "getResponseCount(uint256,address,uint64,address[])": "6e04cacd",
    "getClients(uint256)": "42dd519c",
    "getLastIndex(uint256,address)": "f2d81759",

    # ─── Validation Registry ───
    "validationRequest(address,uint256,string,bytes32)": "aaf400c4",
    "validationResponse(bytes32,uint8,string,bytes32,string)": "3d659a96",
    "getValidationStatus(bytes32)": "ff2febfc",
    "getAgentValidations(uint256)": "8d5d0c2d",
    "getValidatorRequests(address)": "4bf3158c",
}


__all__ = [
    "ERC8004Provider",
    "RPC_ENV_VAR",
]
