# OmniClaw

Policy-controlled payment infrastructure for agent buyers.

OmniClaw core is now focused on one job: letting agents and applications pay through controlled, auditable rails without giving software unrestricted wallet authority.

The hosted facilitator is a separate deployable product under [`services/hosted-facilitator`](services/hosted-facilitator). It owns seller project API keys, hosted x402 settlement, ops console, reconciliation, and OIDC/OpenFGA control-plane auth. Seller middleware remains in each seller's own app and points at the facilitator URL.

## Product Boundary

| Product | Directory | Owns |
| --- | --- | --- |
| OmniClaw core | `src/omniclaw` | buyer SDK, policy engine, wallet/payment routing, x402 buyer execution, Gateway buyer readiness |
| Hosted facilitator | `services/hosted-facilitator` | seller project API keys, x402 facilitator URLs, exact settlement, hosted control plane, reconciliation, ops console |

Core should not import hosted facilitator modules. The hosted facilitator service should be deployable from its own directory without installing OmniClaw core.

## Core Capabilities

- Financial Policy Engine for budgets, approvals, trust checks, and execution control
- Python buyer SDK via `OmniClaw().pay(...)`
- Agent buyer CLI via `omniclaw-cli pay`, `inspect-x402`, and `can-pay`
- Circle Gateway buyer funding/readiness helpers
- Standard x402 buyer flow for paying external seller endpoints
- Ledger, idempotency, simulation, and payment-intent controls

## Hosted Facilitator

The facilitator service has its own package, frontend, Dockerfile, infra config, docs, and tests:

```text
services/hosted-facilitator/
  apps/ops-console/
  docs/
  infra/
  scripts/
  src/hosted_facilitator/
  tests/
```

Local hosted stack:

```bash
cp services/hosted-facilitator/hosted.env.example hosted.env
# edit hosted.env with the hosted facilitator signer private key and provider config
docker compose -f docker-compose.hosted.yml up --build
```

Control plane:

```text
http://127.0.0.1:3001
```

Facilitator API:

```text
http://127.0.0.1:4022
```

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

omniclaw server --port 8080
```

Configure the buyer CLI:

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="agent-token"
```

Inspect and pay an x402 seller endpoint:

```bash
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
```

## Development

Run core tests:

```bash
uv run pytest
```

Run hosted facilitator tests:

```bash
cd services/hosted-facilitator
uv run pytest
```

Run ops console tests:

```bash
cd services/hosted-facilitator/apps/ops-console
npm test
```
