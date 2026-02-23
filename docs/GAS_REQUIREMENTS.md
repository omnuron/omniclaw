"""
Gas Requirements Documentation for OmniClaw Networks

This document outlines the gas token requirements for each supported network.
"""

# Gas Requirements by Network

## Overview

Different blockchain networks have different gas token requirements:
- **Standard EVM Chains**: Require native tokens (ETH, MATIC, etc.) for gas fees
- **Arc Network**: Uses USDC directly for gas fees (unique feature)

---

## Network Gas Requirements

### Ethereum (ETH & ETH-SEPOLIA)
- **Gas Token**: ETH (native token)
- **Required for**:
  - Approving USDC for CCTP
  - Executing `depositForBurn` transaction
  - All on-chain operations
- **Recommendation**: Keep at least 0.01 ETH in wallet for CCTP transfers
- **Faucet (Testnet)**: https://www.alchemy.com/faucets/ethereum-sepolia

### Avalanche (AVAX & AVAX-FUJI)
- **Gas Token**: AVAX (native token)
- **Required for**: All on-chain operations
- **Recommendation**: Keep at least 0.1 AVAX for CCTP transfers

### Optimism (OP & OP-SEPOLIA)
- **Gas Token**: ETH (native token on L2)
- **Required for**: All on-chain operations
- **Recommendation**: Keep at least 0.001 ETH for CCTP transfers

### Arbitrum (ARB & ARB-SEPOLIA)
- **Gas Token**: ETH (native token on L2)
- **Required for**: All on-chain operations
- **Recommendation**: Keep at least 0.001 ETH for CCTP transfers

### Base (BASE & BASE-SEPOLIA)
- **Gas Token**: ETH (native token on L2)
- **Required for**: All on-chain operations
- **Recommendation**: Keep at least 0.001 ETH for CCTP transfers
- **Faucet (Testnet)**: https://www.alchemy.com/faucets/base-sepolia

### Polygon (MATIC & MATIC-AMOY)
- **Gas Token**: MATIC (native token)
- **Required for**: All on-chain operations
- **Recommendation**: Keep at least 0.1 MATIC for CCTP transfers

### **Arc (ARC-TESTNET)** ⭐
- **Gas Token**: **USDC** (unique feature!)
- **Required for**: All on-chain operations
- **Recommendation**: USDC balance covers both payment AND gas
- **Advantage**: Simplified wallet management - only need USDC
- **Note**: USDC operates with 18 decimals for native balance on Arc

---

## CCTP Gas Costs (Approximate)

### Source Chain (Burn)
- **Approval Transaction**: ~50,000 gas
- **depositForBurn Transaction**: ~100,000-150,000 gas
- **Total**: ~150,000-200,000 gas units

### Destination Chain (Mint)
- **receiveMessage Transaction**: ~100,000 gas
- **Note**: Circle may auto-mint in some cases

### Arc Network (USDC as Gas)
- **Approval**: ~0.001-0.002 USDC
- **Burn**: ~0.002-0.003 USDC
- **Total**: ~0.003-0.005 USDC per CCTP transfer

---

## Error Messages

### Insufficient Gas

**Error**: `insufficient token balance (0) in wallet, requiring > 0 native tokens`

**Cause**: Wallet lacks native gas tokens

**Solution**:
1. Identify the network you're transferring FROM
2. Get the native token for that network:
   - ETH chains: Need ETH
   - AVAX: Need AVAX
   - MATIC: Need MATIC  
   - **Arc: Already using USDC!**
3. Transfer native tokens to your wallet
4. Retry the transaction

---

## Best Practices

1. **Always Maintain Gas Balance**:
   - Check gas token balance before CCTP transfers
   - Keep buffer for multiple transactions

2. **Arc Network Advantage**:
   - No need for separate gas tokens
   - USDC balance handles everything
   - Ideal for AI agents (single token management)

3. **Testnet Faucets**:
   - Use faucets to get free testnet gas tokens
   - Links provided in network sections above

4. **Production Deployment**:
   - Monitor gas token levels
   - Set up alerts for low balances
   - Consider automatic top-ups

---

## Quick Reference Table

| Network | Gas Token | CCTP Supported | Arc USDC Feature |
|---------|-----------|----------------|------------------|
| ETH | ETH | ✅ | ❌ |
| AVAX | AVAX | ✅ | ❌ |
| OP | ETH | ✅ | ❌ |
| ARB | ETH | ✅ | ❌ |
| BASE | ETH | ✅ | ❌ |
| MATIC | MATIC | ✅ | ❌ |
| **ARC** | **USDC** | ✅ | ✅ **Unique!** |

---

## Circle API Rate Limits

- **Attestation Service**: 35 requests/second
- **Wallet API**: Varies by endpoint
- **Recommendation**: Implement client-side rate limiting
- **Penalty**: 5-minute block on rate limit exceeded (HTTP 429)
