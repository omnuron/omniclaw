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
export OMNICLAW_PRIVATE_KEY="0x..."
export OMNICLAW_AGENT_TOKEN="agent-token"
export OMNICLAW_AGENT_POLICY_PATH="./policy.json"
export OMNICLAW_NETWORK="BASE-SEPOLIA"
export OMNICLAW_RPC_URL="https://sepolia.base.org"

docker compose up --build omniclaw-agent
```

Configure the buyer CLI:

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="agent-token"
```

Inspect and pay an x402 endpoint:

```bash
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --idempotency-key job-123
```

## Development

Run core tests:

```bash
uv run pytest
```
