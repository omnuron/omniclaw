"""
ERC-8004 on-chain contract interface.

Provides deployed contract addresses, ABIs (as Python dicts), and helpers
for calling the Identity, Reputation, and Validation registries.

Reference: https://eips.ethereum.org/EIPS/eip-8004
"""

from __future__ import annotations

from omniclaw.core.types import Network


# ───────────────────────────────────────────────────────────────────
# Deployed Contract Addresses
# ───────────────────────────────────────────────────────────────────

IDENTITY_REGISTRY_ADDRESSES: dict[str, str] = {
    # Mainnet
    "ETH": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
    # Testnets
    "BASE-SEPOLIA": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
    "ETH-SEPOLIA": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
}

REPUTATION_REGISTRY_ADDRESSES: dict[str, str] = {
    # Mainnet
    "ETH": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
    # Testnets
    "BASE-SEPOLIA": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
    "ETH-SEPOLIA": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
}

VALIDATION_REGISTRY_ADDRESSES: dict[str, str] = {
    # Under active development as of ERC-8004 v1 (Jan 2026 mainnet deployment).
    # Contracts not yet deployed; will be added when published by the EIP authors.
}

# Chain IDs for agentRegistry string construction
CHAIN_IDS: dict[str, int] = {
    "ETH": 1,
    "ETH-SEPOLIA": 11155111,
    "BASE": 8453,
    "BASE-SEPOLIA": 84532,
    "ARB": 42161,
    "ARB-SEPOLIA": 421614,
    "MATIC": 137,
    "MATIC-AMOY": 80002,
    "OP": 10,
    "OP-SEPOLIA": 11155420,
}


# ───────────────────────────────────────────────────────────────────
# Contract ABIs (minimal — only functions we need)
# ───────────────────────────────────────────────────────────────────

IDENTITY_REGISTRY_ABI = [
    # ─── ERC-721 base functions ───
    # read: ownerOf(uint256) → address
    {
        "name": "ownerOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    # read: tokenURI(uint256) → string (agentURI)
    {
        "name": "tokenURI",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "string"}],
    },
    # read: balanceOf(address) → uint256
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    # read: tokenOfOwnerByIndex(address, uint256) → uint256
    {
        "name": "tokenOfOwnerByIndex",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "index", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },

    # ─── ERC-8004 Identity extensions ───
    # read: getAgentWallet(uint256) → address
    {
        "name": "getAgentWallet",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    # read: getMetadata(uint256, string) → bytes
    {
        "name": "getMetadata",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "metadataKey", "type": "string"},
        ],
        "outputs": [{"name": "", "type": "bytes"}],
    },
    # write: register() → uint256  (no URI, add later with setAgentURI)
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [{"name": "agentId", "type": "uint256"}],
    },
    # write: register(string) → uint256  (with agentURI)
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "agentURI", "type": "string"}],
        "outputs": [{"name": "agentId", "type": "uint256"}],
    },
    # write: register(string, MetadataEntry[]) → uint256  (with agentURI + metadata)
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentURI", "type": "string"},
            {
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {"name": "metadataKey", "type": "string"},
                    {"name": "metadataValue", "type": "bytes"},
                ],
            },
        ],
        "outputs": [{"name": "agentId", "type": "uint256"}],
    },
    # write: setAgentURI(uint256, string)
    {
        "name": "setAgentURI",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "newURI", "type": "string"},
        ],
        "outputs": [],
    },
    # write: setMetadata(uint256, string, bytes)
    {
        "name": "setMetadata",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "metadataKey", "type": "string"},
            {"name": "metadataValue", "type": "bytes"},
        ],
        "outputs": [],
    },
    # write: setAgentWallet(uint256, address, uint256, bytes)  — EIP-712 signature
    {
        "name": "setAgentWallet",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "newWallet", "type": "address"},
            {"name": "deadline", "type": "uint256"},
            {"name": "signature", "type": "bytes"},
        ],
        "outputs": [],
    },
    # write: unsetAgentWallet(uint256)
    {
        "name": "unsetAgentWallet",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [],
    },
]

REPUTATION_REGISTRY_ABI = [
    # ─── Read functions ───
    # read: getIdentityRegistry() → address
    {
        "name": "getIdentityRegistry",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "identityRegistry", "type": "address"}],
    },
    # read: getClients(uint256) → address[]
    {
        "name": "getClients",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address[]"}],
    },
    # read: readFeedback(uint256, address, uint64) → (int128, uint8, string, string, bool)
    {
        "name": "readFeedback",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
            {"name": "feedbackIndex", "type": "uint64"},
        ],
        "outputs": [
            {"name": "value", "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "isRevoked", "type": "bool"},
        ],
    },
    # read: readAllFeedback(uint256, address[], string, string, bool) → multiple arrays
    {
        "name": "readAllFeedback",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddresses", "type": "address[]"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "includeRevoked", "type": "bool"},
        ],
        "outputs": [
            {"name": "clients", "type": "address[]"},
            {"name": "feedbackIndexes", "type": "uint64[]"},
            {"name": "values", "type": "int128[]"},
            {"name": "valueDecimals", "type": "uint8[]"},
            {"name": "tag1s", "type": "string[]"},
            {"name": "tag2s", "type": "string[]"},
            {"name": "revokedStatuses", "type": "bool[]"},
        ],
    },
    # read: getLastIndex(uint256, address) → uint64
    {
        "name": "getLastIndex",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint64"}],
    },
    # read: getSummary(uint256, address[], string, string) → (uint64, int128, uint8)
    {
        "name": "getSummary",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddresses", "type": "address[]"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
        ],
        "outputs": [
            {"name": "count", "type": "uint64"},
            {"name": "summaryValue", "type": "int128"},
            {"name": "summaryValueDecimals", "type": "uint8"},
        ],
    },
    # read: getResponseCount(uint256, address, uint64, address[]) → uint64
    {
        "name": "getResponseCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
            {"name": "feedbackIndex", "type": "uint64"},
            {"name": "responders", "type": "address[]"},
        ],
        "outputs": [{"name": "count", "type": "uint64"}],
    },
    # ─── Write functions ───
    # write: giveFeedback(uint256, int128, uint8, string, string, string, string, bytes32)
    {
        "name": "giveFeedback",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "value", "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "endpoint", "type": "string"},
            {"name": "feedbackURI", "type": "string"},
            {"name": "feedbackHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    # write: revokeFeedback(uint256, uint64)
    {
        "name": "revokeFeedback",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "feedbackIndex", "type": "uint64"},
        ],
        "outputs": [],
    },
    # write: appendResponse(uint256, address, uint64, string, bytes32)
    {
        "name": "appendResponse",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
            {"name": "feedbackIndex", "type": "uint64"},
            {"name": "responseURI", "type": "string"},
            {"name": "responseHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
]

VALIDATION_REGISTRY_ABI = [
    # ─── Read functions ───
    # read: getValidationStatus(bytes32) → (address, uint256, uint8, bytes32, string, uint256)
    {
        "name": "getValidationStatus",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "requestHash", "type": "bytes32"}],
        "outputs": [
            {"name": "validatorAddress", "type": "address"},
            {"name": "agentId", "type": "uint256"},
            {"name": "response", "type": "uint8"},
            {"name": "responseHash", "type": "bytes32"},
            {"name": "tag", "type": "string"},
            {"name": "lastUpdate", "type": "uint256"},
        ],
    },
    # read: getSummary(uint256, address[], string) → (uint64, uint8)
    {
        "name": "getSummary",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "validatorAddresses", "type": "address[]"},
            {"name": "tag", "type": "string"},
        ],
        "outputs": [
            {"name": "count", "type": "uint64"},
            {"name": "averageResponse", "type": "uint8"},
        ],
    },
    # read: getAgentValidations(uint256) → bytes32[]
    {
        "name": "getAgentValidations",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "requestHashes", "type": "bytes32[]"}],
    },
    # read: getValidatorRequests(address) → bytes32[]
    {
        "name": "getValidatorRequests",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "validatorAddress", "type": "address"}],
        "outputs": [{"name": "requestHashes", "type": "bytes32[]"}],
    },
    # ─── Write functions ───
    # write: validationRequest(address, uint256, string, bytes32)
    {
        "name": "validationRequest",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "validatorAddress", "type": "address"},
            {"name": "agentId", "type": "uint256"},
            {"name": "requestURI", "type": "string"},
            {"name": "requestHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    # write: validationResponse(bytes32, uint8, string, bytes32, string)
    {
        "name": "validationResponse",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "requestHash", "type": "bytes32"},
            {"name": "response", "type": "uint8"},
            {"name": "responseURI", "type": "string"},
            {"name": "responseHash", "type": "bytes32"},
            {"name": "tag", "type": "string"},
        ],
        "outputs": [],
    },
]


# ───────────────────────────────────────────────────────────────────
# Helper Functions
# ───────────────────────────────────────────────────────────────────

def get_identity_registry(network: Network | str) -> str | None:
    """Get Identity Registry address for a network."""
    key = network.value if isinstance(network, Network) else str(network).upper()
    return IDENTITY_REGISTRY_ADDRESSES.get(key)


def get_reputation_registry(network: Network | str) -> str | None:
    """Get Reputation Registry address for a network."""
    key = network.value if isinstance(network, Network) else str(network).upper()
    return REPUTATION_REGISTRY_ADDRESSES.get(key)


def get_chain_id(network: Network | str) -> int | None:
    """Get chain ID for a network."""
    key = network.value if isinstance(network, Network) else str(network).upper()
    return CHAIN_IDS.get(key)


def get_validation_registry(network: Network | str) -> str | None:
    """Get Validation Registry address for a network.

    NOTE: Validation Registry contracts are not yet deployed (EIP-8004 v1).
    This will return None until contracts go live (expected Q3 2026).
    """
    key = network.value if isinstance(network, Network) else str(network).upper()
    return VALIDATION_REGISTRY_ADDRESSES.get(key)


def build_agent_registry_string(network: Network | str) -> str | None:
    """
    Build the ERC-8004 agentRegistry identifier string.

    Format: {namespace}:{chainId}:{identityRegistry}
    Example: eip155:1:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432
    """
    chain_id = get_chain_id(network)
    identity_addr = get_identity_registry(network)
    if chain_id is None or identity_addr is None:
        return None
    return f"eip155:{chain_id}:{identity_addr}"


def is_erc8004_supported(network: Network | str) -> bool:
    """Check if ERC-8004 registries are deployed on this network."""
    return get_identity_registry(network) is not None


__all__ = [
    "IDENTITY_REGISTRY_ADDRESSES",
    "REPUTATION_REGISTRY_ADDRESSES",
    "VALIDATION_REGISTRY_ADDRESSES",
    "IDENTITY_REGISTRY_ABI",
    "REPUTATION_REGISTRY_ABI",
    "VALIDATION_REGISTRY_ABI",
    "CHAIN_IDS",
    "get_identity_registry",
    "get_reputation_registry",
    "get_validation_registry",
    "get_chain_id",
    "build_agent_registry_string",
    "is_erc8004_supported",
]
