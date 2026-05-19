# Agent Getting Started

This guide is for agent buyers.

## Start Core

```bash
export OMNICLAW_PRIVATE_KEY="0x..."
export OMNICLAW_AGENT_TOKEN="agent-token"
export OMNICLAW_AGENT_POLICY_PATH="./policy.json"
export OMNICLAW_NETWORK="BASE-SEPOLIA"
export OMNICLAW_RPC_URL="https://sepolia.base.org"

omniclaw server --port 8080
```

## Configure The Buyer CLI

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="agent-token"
```

## Inspect A Paid URL

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/compute
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
```

## Pay

```bash
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
```

## Seller/Facilitator Work

Seller-facing service code and hosted facilitator operations are separate from core:

```text
services/hosted-facilitator/
```
