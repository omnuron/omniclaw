# Example: Using CCTP Features

## Basic Cross-Chain Payment
```python
from omniclaw import OmniClaw
from omniclaw.core.types import Network
from decimal import Decimal

client = OmniClaw(
    circle_api_key="sk_...",
    entity_secret="...",
    network=Network.ARC_TESTNET
)

# Simple cross-chain payment (uses Fast Transfer by default)
result = await client.pay(
    wallet_id="wallet_123",
    recipient="0x742d35Cc...",
    amount=Decimal("10.0"),
    destination_chain=Network.BASE_SEPOLIA,
)
```

## CCTP Fast Transfer (Default)
```python
# Fast Transfer is enabled by default (~2-5 seconds)
result = await client.pay(
    wallet_id="wallet_123",
    recipient="0x742d35Cc...",
    amount=Decimal("10.0"),
    destination_chain=Network.BASE_SEPOLIA,
    use_fast_transfer=True,  # Default, explicit for clarity
)

# Check result
if result.success:
    print(f"Transfer mode: {result.metadata['transfer_mode']}")
    # Output: "Fast Transfer (~2-5s)"
```

## CCTP Standard Transfer
```python
# Use Standard Transfer for larger amounts (~13-19 minutes)
result = await client.pay(
    wallet_id="wallet_123",
    recipient="0x742d35Cc...",
    amount=Decimal("1000.0"),
    destination_chain=Network.BASE_SEPOLIA,
    use_fast_transfer=False,  # Opts into Standard Transfer
)

# Check result
if result.success:
    print(f"Transfer mode: {result.metadata['transfer_mode']}")
    # Output: "Standard Transfer (~13-19m)"
```

## Checking Transfer Details
```python
result = await client.pay(
    wallet_id="wallet_123",
    recipient="0x742d35Cc...",
    amount=Decimal("50.0"),
    destination_chain=Network.BASE_SEPOLIA,
    use_fast_transfer=True,  # Fast Transfer
    purpose="Payment for API access",
    wait_for_completion=True,
)

if result.success:
    print(f"✅ Transaction ID: {result.transaction_id}")
    print(f"Status: {result.status}")
    print(f"Method: {result.method}")
    
    # CCTP-specific metadata
    print(f"CCTP Version: {result.metadata['cctp_version']}")
    print(f"Transfer Mode: {result.metadata['transfer_mode']}")
    print(f"Source Domain: {result.metadata['source_domain']}")
    print(f"Dest Domain: {result.metadata['destination_domain']}")
    
    # Attestation URL (for manual mint if needed)
    print(f"Attestation URL: {result.metadata['attestation_url']}")
    # You can check this URL to get attestation status
else:
    print(f"❌ Payment failed: {result.error}")
```

## When to Use Each Mode

### Fast Transfer (use_fast_transfer=True)
- ✅ **Best for**: Most use cases, real-time payments
- ⏱️ **Speed**: 2-5 seconds
- 💰 **Fee**: ~0.0005 USDC max
- 📦 **Amount**: Any amount

### Standard Transfer (use_fast_transfer=False)
- ✅ **Best for**: Batch processing, non-urgent transfers
- ⏱️ **Speed**: 13-19 minutes
- 💰 **Fee**: Lower gas costs
- 📦 **Amount**: Any amount

## Network Support

CCTP works between these networks:
- Ethereum (ETH, ETH-SEPOLIA)
- Avalanche (AVAX, AVAX-FUJI)
- Optimism (OP, OP-SEPOLIA)
- Arbitrum (ARB, ARB-SEPOLIA)
- Base (BASE, BASE-SEPOLIA)
- Polygon (MATIC, MATIC-AMOY)
- **Arc (ARC-TESTNET)** ⭐ - Uses USDC for gas!

## Complete the Mint (Manual)

After burn transaction completes, you can manually complete the mint:

1. Get attestation from the URL in metadata
2. Call `receiveMessage` on destination chain

Or just wait - Circle will auto-mint after attestation is ready!
