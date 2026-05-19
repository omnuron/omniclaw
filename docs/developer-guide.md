# Developer Guide

This guide covers OmniClaw core buyer integration.

Project API keys, facilitator URLs, ops console, and settlement operations live in the standalone hosted facilitator service: `services/hosted-facilitator`. Seller-facing middleware stays in the seller's own application and calls the hosted facilitator URL with its project API key.

## Pay From Python

```python
from omniclaw import OmniClaw

client = OmniClaw()

result = await client.pay(
    wallet_id="wallet-id",
    recipient="https://seller.example.com/compute",
    amount=None,
    idempotency_key="job-123",
)
```

For x402 URLs, OmniClaw inspects the seller requirements and routes through the buyer rail that is available and allowed by policy.

## Run The Policy Engine

```bash
export OMNICLAW_PRIVATE_KEY="0x..."
export OMNICLAW_AGENT_TOKEN="agent-token"
export OMNICLAW_AGENT_POLICY_PATH="./policy.json"
export OMNICLAW_NETWORK="BASE-SEPOLIA"
export OMNICLAW_RPC_URL="https://sepolia.base.org"

omniclaw server --port 8080
```

## Pay With The CLI

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="agent-token"

omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
```

## Gateway Buyer Funding

Gateway nanopayments require the buyer to hold/deposit USDC into Circle Gateway before using `GatewayWalletBatched` routes. Core keeps buyer-side deposit, withdrawal, balance, and readiness helpers.

## Facilitator Integration

To operate OmniClaw-hosted seller settlement, use:

```text
services/hosted-facilitator/
```
