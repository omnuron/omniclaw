# Agent Getting Started

This guide is for agent buyers.

## Start The Buyer Server

```bash
cp .env.example .env
# For hybrid mode, fill CIRCLE_API_KEY, ENTITY_SECRET, OMNICLAW_PRIVATE_KEY,
# OMNICLAW_AGENT_TOKEN, OMNICLAW_OWNER_TOKEN, OMNICLAW_NETWORK, and OMNICLAW_RPC_URL.

docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

The buyer server runs in hybrid mode by default:

- Circle Developer Wallet for direct USDC transfers.
- EOA/Gateway signer for x402 exact and Gateway routes.
- Stable policy in `examples/agent/buyer/runtime/policy.json`.
- Generated wallet state in `examples/agent/buyer/runtime/wallet-state.json`.

Mode requirements:

| Mode | Credentials |
| --- | --- |
| `hybrid` | `CIRCLE_API_KEY`, `ENTITY_SECRET`, `OMNICLAW_PRIVATE_KEY`, `OMNICLAW_RPC_URL` |
| `circle` | `CIRCLE_API_KEY`, `ENTITY_SECRET` |
| `gateway` | `CIRCLE_API_KEY`, `OMNICLAW_PRIVATE_KEY`, `OMNICLAW_RPC_URL` |
| `x402` | `OMNICLAW_PRIVATE_KEY`, `OMNICLAW_RPC_URL` |

## Configure The Buyer CLI

```bash
set -a; source .env; set +a
export OMNICLAW_SERVER_URL="http://127.0.0.1:9091"
export OMNICLAW_TOKEN="$OMNICLAW_AGENT_TOKEN"
```

## Inspect A Paid URL

```bash
omniclaw-cli can-pay --recipient https://paid.example.com/compute
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
```

## Pay A Paid API

```bash
omniclaw-cli pay --recipient https://paid.example.com/compute --amount 0.10 --idempotency-key job-123
```

## Direct Transfer

```bash
omniclaw-cli pay \
  --recipient <recipient-evm-address> \
  --amount 1.00 \
  --idempotency-key transfer-123
```

## Gateway Funding

```bash
omniclaw-cli deposit-address
omniclaw-cli balance-detail
omniclaw-cli deposit --amount 10.00 --check-gas
```
