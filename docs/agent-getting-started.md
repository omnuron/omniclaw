# Agent Getting Started

This guide is for agent buyers.

## Start Core

```bash
export OMNICLAW_PRIVATE_KEY="0x..."
export OMNICLAW_AGENT_TOKEN="agent-token"
export OMNICLAW_AGENT_POLICY_PATH="./policy.json"
export OMNICLAW_NETWORK="BASE-SEPOLIA"
export OMNICLAW_RPC_URL="https://sepolia.base.org"

docker compose up --build omniclaw-agent
```

## Configure The Buyer CLI

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="agent-token"
```

## Inspect A Paid URL

```bash
omniclaw-cli can-pay --recipient https://paid.example.com/compute
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
```

## Pay

```bash
omniclaw-cli pay --recipient https://paid.example.com/compute --idempotency-key job-123
```
