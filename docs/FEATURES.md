# Core Features

OmniClaw core is the buyer-side policy and payment-control layer.

## Buyer Payment Control

- Wallet-scoped policy enforcement
- Budgets, recipient rules, approval gates, and trust checks
- Idempotent payment execution
- Ledger and payment-intent tracking
- Simulation and readiness checks before money moves

## x402 Buyer Support

- Inspect seller `PAYMENT-REQUIRED` responses
- Select supported x402 routes
- Pay standard `exact` seller endpoints
- Use Circle Gateway `GatewayWalletBatched` when the buyer is funded and the route is advertised

## Circle Gateway Buyer Operations

- Gateway balance checks
- On-chain Gateway balance checks
- Deposit and withdraw helpers
- Buyer readiness for nanopayment routes

## Standalone Hosted Facilitator

Hosted settlement, seller onboarding, ops console, reconciliation, OIDC/OpenFGA auth, and provider adapters live outside core:

```text
services/hosted-facilitator/
```
