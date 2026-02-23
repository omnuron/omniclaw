"""
CCTP V2 (Cross-Chain Transfer Protocol) constants.

Official contract addresses from Circle:
https://developers.circle.com/cctp/references/contract-addresses
"""

from omniclaw.core.types import Network

# CCTP V2 Domain IDs
# https://developers.circle.com/cctp/concepts/supported-chains-and-domains
CCTP_DOMAIN_IDS = {
    # Ethereum
    Network.ETH: 0,
    Network.ETH_SEPOLIA: 0,
    # Avalanche
    Network.AVAX: 1,
    Network.AVAX_FUJI: 1,
    # Optimism
    Network.OP: 2,
    Network.OP_SEPOLIA: 2,
    # Arbitrum
    Network.ARB: 3,
    Network.ARB_SEPOLIA: 3,
    # Solana
    Network.SOL: 5,
    Network.SOL_DEVNET: 5,
    # Base
    Network.BASE: 6,
    Network.BASE_SEPOLIA: 6,
    # Polygon
    Network.MATIC: 7,
    Network.MATIC_AMOY: 7,
    # Arc
    Network.ARC_TESTNET: 26,
}

# TokenMessengerV2 Contract Addresses
TOKEN_MESSENGER_V2_MAINNET = "0x28b5a0e9C621a5BadaA536219b3a228C8168cf5d"
TOKEN_MESSENGER_V2_TESTNET = "0x8FE6B999Dc680CcFDD5Bf7EB0974218be2542DAA"

TOKEN_MESSENGER_V2_CONTRACTS = {
    # Mainnet
    "ETH": TOKEN_MESSENGER_V2_MAINNET,
    "AVAX": TOKEN_MESSENGER_V2_MAINNET,
    "OP": TOKEN_MESSENGER_V2_MAINNET,
    "ARB": TOKEN_MESSENGER_V2_MAINNET,
    "BASE": TOKEN_MESSENGER_V2_MAINNET,
    "MATIC": TOKEN_MESSENGER_V2_MAINNET,
    # Testnet
    "ETH-SEPOLIA": TOKEN_MESSENGER_V2_TESTNET,
    "AVAX-FUJI": TOKEN_MESSENGER_V2_TESTNET,
    "OP-SEPOLIA": TOKEN_MESSENGER_V2_TESTNET,
    "ARB-SEPOLIA": TOKEN_MESSENGER_V2_TESTNET,
    "BASE-SEPOLIA": TOKEN_MESSENGER_V2_TESTNET,
    "MATIC-AMOY": TOKEN_MESSENGER_V2_TESTNET,
    "ARC-TESTNET": TOKEN_MESSENGER_V2_TESTNET,
}

# MessageTransmitterV2 Contract Addresses
MESSAGE_TRANSMITTER_V2_MAINNET = "0x81D40F21F12A8F0E3252Bccb954D722d4c464B64"
MESSAGE_TRANSMITTER_V2_TESTNET = "0xE737e5cEBEEBa77EFE34D4aa090756590b1CE275"

MESSAGE_TRANSMITTER_V2_CONTRACTS = {
    # Mainnet
    "ETH": MESSAGE_TRANSMITTER_V2_MAINNET,
    "AVAX": MESSAGE_TRANSMITTER_V2_MAINNET,
    "OP": MESSAGE_TRANSMITTER_V2_MAINNET,
    "ARB": MESSAGE_TRANSMITTER_V2_MAINNET,
    "BASE": MESSAGE_TRANSMITTER_V2_MAINNET,
    "MATIC": MESSAGE_TRANSMITTER_V2_MAINNET,
    # Testnet
    "ETH-SEPOLIA": MESSAGE_TRANSMITTER_V2_TESTNET,
    "AVAX-FUJI": MESSAGE_TRANSMITTER_V2_TESTNET,
    "OP-SEPOLIA": MESSAGE_TRANSMITTER_V2_TESTNET,
    "ARB-SEPOLIA": MESSAGE_TRANSMITTER_V2_TESTNET,
    "BASE-SEPOLIA": MESSAGE_TRANSMITTER_V2_TESTNET,
    "MATIC-AMOY": MESSAGE_TRANSMITTER_V2_TESTNET,
    "ARC-TESTNET": MESSAGE_TRANSMITTER_V2_TESTNET,
}

# USDC Contract Addresses
USDC_CONTRACTS = {
    # Ethereum
    "ETH": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "ETH-SEPOLIA": "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
    # Avalanche
    "AVAX": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
    "AVAX-FUJI": "0x5425890298aed601595a70AB815c96711a31Bc65",
    # Optimism
    "OP": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    "OP-SEPOLIA": "0x5fd84259d66Cd46123540766Be93DFE6D43130D7",
    # Arbitrum
    "ARB": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "ARB-SEPOLIA": "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d",
    # Base
    "BASE": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "BASE-SEPOLIA": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    # Polygon
    "MATIC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    "MATIC-AMOY": "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582",
    # Arc - USDC on Arc Testnet
    "ARC-TESTNET": "0x79A02482A880bCE3F13e09Da970dC34db4CD24d1",
}

# Iris API
IRIS_API_SANDBOX = "https://iris-api-sandbox.circle.com"
IRIS_API_MAINNET = "https://iris-api.circle.com"
IRIS_V2_MESSAGES_PATH = "/v2/messages"


def get_iris_url(network: Network) -> str:
    """Get the appropriate Iris API URL for a network."""
    return IRIS_API_SANDBOX if network.is_testnet() else IRIS_API_MAINNET


def get_iris_v2_attestation_url(network: Network, domain: int, tx_hash: str) -> str:
    """Get the CCTP V2 attestation API URL."""
    base_url = get_iris_url(network)
    return f"{base_url}{IRIS_V2_MESSAGES_PATH}/{domain}?transactionHash={tx_hash}"


def is_cctp_supported(network: Network) -> bool:
    """Check if a network is supported by CCTP."""
    return network in CCTP_DOMAIN_IDS


def get_token_messenger_v2(network: Network) -> str | None:
    """Get TokenMessengerV2 contract address."""
    return TOKEN_MESSENGER_V2_CONTRACTS.get(network.value)


def get_message_transmitter_v2(network: Network) -> str | None:
    """Get MessageTransmitterV2 contract address."""
    return MESSAGE_TRANSMITTER_V2_CONTRACTS.get(network.value)


# CCTP V2 Transfer Parameters

# Fast Transfer: minFinalityThreshold <= 1000
FAST_TRANSFER_THRESHOLD = 1000

# Standard Transfer: minFinalityThreshold >= 2000
STANDARD_TRANSFER_THRESHOLD = 2000

# Default max fee in USDC subunits (0.0005 USDC = 500)
DEFAULT_MAX_FEE = 500

# Empty bytes32 for destinationCaller
EMPTY_DESTINATION_CALLER = "0x0000000000000000000000000000000000000000000000000000000000000000"
