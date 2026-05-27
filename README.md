# OmniClaw

Policy-controlled payment infrastructure for agent buyers.

OmniClaw core is focused on one job: letting agents and applications pay through controlled, auditable rails without giving software unrestricted wallet authority.

## Product Boundary

| Product | Directory | Owns |
| --- | --- | --- |
| OmniClaw core | `src/omniclaw` | buyer SDK, policy engine, wallet/payment routing, x402 buyer execution, Gateway buyer readiness |

Core should not include recipient-side paid endpoint hosting or settlement service code.

## Core Capabilities

- Financial Policy Engine for budgets, approvals, trust checks, and execution control
- Python buyer SDK via `OmniClaw().pay(...)`
- Agent buyer CLI via `omniclaw-cli pay`, `inspect-x402`, and `can-pay`
- Circle Gateway buyer funding/readiness helpers
- Standard x402 buyer flow for paying external paid endpoints
- Ledger, idempotency, simulation, and payment-intent controls

## Core Quickstart

Install:

```bash
pip install omniclaw
```

Start the policy engine:

```bash
cp .env.example .env
# Fill CIRCLE_API_KEY, ENTITY_SECRET, OMNICLAW_PRIVATE_KEY,
# OMNICLAW_AGENT_TOKEN, OMNICLAW_OWNER_TOKEN, OMNICLAW_NETWORK, and OMNICLAW_RPC_URL.

mkdir -p examples/agent/buyer/runtime
cp examples/agent/buyer/policy.example.json examples/agent/buyer/runtime/policy.json
# Edit examples/agent/buyer/runtime/policy.json so the token matches OMNICLAW_AGENT_TOKEN.

docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

The policy file is stable configuration. Generated wallet state is written separately
to `examples/agent/buyer/runtime/wallet-state.json`.

Buyer-facing policy rails are:

- `circle_transfer` for direct Circle Developer Wallet transfers.
- `x402` for paid API payments. OmniClaw chooses Gateway nanopayment or the standard
  x402 payment path internally based on seller accepts, buyer config, and Gateway balance.

Configure the buyer CLI:

```bash
set -a; source .env; set +a
export OMNICLAW_SERVER_URL="http://127.0.0.1:9091"
export OMNICLAW_TOKEN="$OMNICLAW_AGENT_TOKEN"
```

Inspect and pay an x402 endpoint:

```bash
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --amount 0.10 --idempotency-key job-123
```

## Development

Run core tests:

```bash
uv run pytest
```
