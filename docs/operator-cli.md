# Operator CLI

OmniClaw ships two command surfaces:

- `omniclaw` for infrastructure and control-plane services
- `omniclaw-cli` for agent-side financial execution

Use `omniclaw` when you are running the policy engine, setup flow, or facilitator infrastructure:

```bash
omniclaw setup --api-key "$CIRCLE_API_KEY" --entity-secret "$ENTITY_SECRET"
omniclaw server --port 8080
omniclaw facilitator exact --network-profile ARC-TESTNET --port 4022
omniclaw policy lint --path ./policy.json
omniclaw env
omniclaw doctor
```

`--entity-secret` is optional only when this Circle API key/account has not created one yet. Circle allows one active Entity Secret per account/API key. If you already have it, pass it directly; if you omit it and OmniClaw cannot find one in env or managed config, setup will generate and register a new one.

Use `omniclaw-cli` when an agent is performing constrained financial actions:

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/compute
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
omniclaw-cli serve --price 0.01 --endpoint /api/data --exec "python safe_readonly_service.py"
```

`omniclaw-cli serve` is the agent-facing seller surface. Use it when an agent needs to expose a paid endpoint for other agents or automation. Vendor and enterprise APIs that live inside application code should use the Python SDK seller middleware (`client.sell(...)`) instead.

`serve` binds to all interfaces and `--exec` runs the supplied host command. Treat it as an explicit owner-approved action, preferably in an isolated runtime.

## Responsibility Split

The infrastructure CLI manages trusted configuration and settlement services. The agent CLI executes through the Financial Policy Engine and never needs raw wallet authority.

This split is central to OmniClaw:

- tools expose what the agent can try to do
- the Financial Policy Engine governs what financial authority the agent actually has
- facilitators settle valid x402 payment payloads on supported rails

## Self-Hosted Facilitator

The operator CLI includes a first-class facilitator command:

```bash
export OMNICLAW_X402_FACILITATOR_PRIVATE_KEY="0x..."

omniclaw facilitator exact \
  --network-profile ARC-TESTNET \
  --port 4022
```

For the full facilitator guide, see [facilitators.md](facilitators.md).
