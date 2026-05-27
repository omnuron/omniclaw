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

docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

The first boot writes a visible local runtime policy to `examples/agent/buyer/runtime/policy.json`.
Edit that file for policy changes, or remove `examples/agent/buyer/runtime/` to recreate it from `.env`.

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
