# Roadmap

This roadmap shows what OmniClaw has already built, what is being built now, and what we plan to build next.

## What We Have Built (Today)

- wallet orchestration and management (Circle-backed)
- `simulate()` and `pay()` execution with guardrails
- payment intents with reservation and confirmation handling
- Redis-backed locking and execution state
- routing across address transfers, x402 HTTP payments, and cross-chain USDC gateway paths
- ledger persistence and webhook verification
- operator-facing guard controls
- optional trust gate for ERC-8004-style trust evaluation
- public alpha release (0.0.2)

## What We Are Building Next (2026)

### Enterprise Control Plane

Based on `enterprise-dashboard.md`:

- Redis Streams event bus inside the SDK
- Ops API (FastAPI + WebSocket)
- Dashboard MVP (HITL approvals + live ledger)
- Policy & Compliance (guard editor + audit export)
- Trust Inspector (ERC-8004 identity + network graph)

### Developer Integration Surface

- TypeScript / Node.js SDK
- MCP server (production-ready)
- `omniclaw` CLI for setup, diagnostics, and ops
- agent skills library and templates

## What We Plan After That (2027)

- escrow and milestone payment workflows
- dispute, cancellation, and rollback flows
- escrow visibility in the dashboard
- agent line of credit
- delegated spending + multi-party approvals
- treasury tooling for fleets of agents

## What We Anticipate Longer Term (Future)

- programmable payment policies that adapt to context (trust score, risk tier, transaction history)
- cross-rail policy enforcement across x402, card, and stablecoin rails
- standard compliance exports with signed attestations
- reputation and validation registry integrations (ERC-8004 evolution)
- marketplace primitives: splits, royalties, and revshare
- delegated authority scopes (time-bound, budget-bound, recipient-bound)
- capital routing policies (cheapest, fastest, safest rail by SLA)
- enterprise admin console: org-level controls, teams, roles, approval chains
