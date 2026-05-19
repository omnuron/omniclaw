# Production Readiness

This checklist is for OmniClaw core: buyer-side agent payment infrastructure, policy controls, wallet routing, and x402 buyer execution.

## Core Readiness

- `omniclaw-cli can-pay` works for the target wallet and policy.
- `omniclaw-cli inspect-x402` reports the payment requirements and selected buyer route.
- `omniclaw-cli pay` executes through `/api/v1/pay`.
- Policy blocks unsafe recipients before money moves.
- Idempotency keys are supplied for production payment calls.
- Gateway payments require Gateway readiness before selecting `GatewayWalletBatched`.
- Standard exact x402 payments use the upstream x402 SDK path.
- Ledger, intent, and webhook records are available for audit.

## Validation

For a production canary, capture:

- paid resource URL
- `inspect-x402` output
- `pay` output
- transaction hash or settlement ID
- policy file used for the buyer
- dashboard or explorer evidence

## Release Gate

Run before shipping core changes:

```bash
uv sync --extra dev
uv run pytest -q
python3 scripts/release_verify.sh
```
