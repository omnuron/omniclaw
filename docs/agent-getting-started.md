# Agent Getting Started

This guide is for agent buyers.

## Start The Buyer Server

```bash
cp .env.example .env
# For hybrid mode, fill CIRCLE_API_KEY, ENTITY_SECRET, OMNICLAW_PRIVATE_KEY,
# OMNICLAW_AGENT_TOKEN, OMNICLAW_OWNER_TOKEN, OMNICLAW_NETWORK, and OMNICLAW_RPC_URL.
# For x402-only Gateway mode instead, set OMNICLAW_BUYER_MODE=x402 and leave
# CIRCLE_API_KEY and ENTITY_SECRET empty unless you need optional Circle Gateway
# API helper operations.

mkdir -p examples/agent/buyer/runtime
cp examples/agent/buyer/policy.example.json examples/agent/buyer/runtime/policy.json
# Edit examples/agent/buyer/runtime/policy.json so the token matches OMNICLAW_AGENT_TOKEN.

docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

The buyer server runs in hybrid mode by default:

- Circle Developer Wallet for direct USDC transfers.
- EOA signer for x402 paid APIs. When the seller advertises `GatewayWalletBatched`
  and the buyer has Gateway balance, OmniClaw can use the Gateway nanopayment path.
- Stable policy in `examples/agent/buyer/runtime/policy.json`.
- Generated wallet state in `examples/agent/buyer/runtime/wallet-state.json`.

Mode requirements:

| Mode | Credentials |
| --- | --- |
| `hybrid` | `CIRCLE_API_KEY`, `ENTITY_SECRET`, `OMNICLAW_PRIVATE_KEY`, `OMNICLAW_RPC_URL` |
| `circle` | `CIRCLE_API_KEY`, `ENTITY_SECRET` |
| `x402` | `OMNICLAW_PRIVATE_KEY`, `OMNICLAW_RPC_URL`, and funded Gateway balance for `GatewayWalletBatched` nanopayments |

`CIRCLE_API_KEY` is not required for x402 Gateway nanopayments. It is only needed
for Circle direct transfers and optional Circle Gateway API helper operations.
Gateway is an x402 execution path, not a separate buyer rail.

## Configure The Buyer CLI

```bash
set -a; source .env; set +a
export OMNICLAW_SERVER_URL="http://127.0.0.1:9091"
export OMNICLAW_TOKEN="$OMNICLAW_AGENT_TOKEN"
```

## Inspect A Paid URL

```bash
omniclaw-cli can-pay --recipient "http://127.0.0.1:4023/compute?size=20"
omniclaw-cli inspect-x402 --recipient "http://127.0.0.1:4023/compute?size=20"
```

## Pay A Paid API

```bash
omniclaw-cli pay --recipient "http://127.0.0.1:4023/compute?size=20" --amount 0.10 --idempotency-key job-123
```

## Direct Transfer

```bash
omniclaw-cli pay \
  --recipient <recipient-evm-address> \
  --amount 1.00 \
  --idempotency-key transfer-123
```

## x402 Nanopayment Funding

```bash
omniclaw-cli deposit-address
omniclaw-cli balance-detail
omniclaw-cli deposit --amount 10.00 --check-gas
```
