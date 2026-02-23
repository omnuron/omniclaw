# CCTP Autonomous Setup Guide (Arc Testnet)

## Overview
As of January 2026, CCTP transfers to **Arc Testnet** require **Agent-Side Minting**. This means your agent directly interacts with the destination chain to mint the USDC, instead of relying on a third-party relayer.

OmniClaw handles this **completely autonomously**. You do not need to intervene during the transfer.

## Prerequisite: Agent Gas Check

For the agent to autonomously sign the "Mint" transaction on the destination chain (Arc Testnet), it needs a small amount of native gas (Arc ETH).

### 1. Ensure Agent has an Arc Wallet
```python
from omniclaw import OmniClaw, Network

client = OmniClaw.from_env()

# This command ensures the agent has a wallet on Arc Testnet
wallet_set, wallet = client.wallet_service.setup_agent_wallet(
    agent_name="MyAgent",
    blockchain=Network.ARC_TESTNET
)

print(f"Agent Arc Address: {wallet.address}")
```

### 2. Fund Gas (One-Time Setup)
Send a small amount of native tokens (ETH) to the `Agent Arc Address`. This allows the agent to pay for the computation of the minting transaction.

*   **Amount**: 0.01 Arc ETH is plenty for hundreds of transactions.

## How it Runs Autonomously

When you call `client.pay(..., destination_chain=Network.ARC_TESTNET)`:

1.  **Burn**: Agent burns USDC on source chain.
2.  **Attestation**: SDK waits for Circle Attestation (2−5s).
3.  **Agent-Side Mint**: SDK automatically:
    *   Detects Arc Testnet destination.
    *   Finds the agent's funded wallet on Arc.
    *   Signs and broadcasts `receiveMessage` to mint the funds.
    *   Confirms receipt.

No human intervention is required once the agent is funded.
