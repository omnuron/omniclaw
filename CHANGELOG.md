# Changelog

All notable changes to OmniClaw are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Removed the obsolete secondary console entrypoint and pointed both console scripts at the unified `omniclaw.cli` buyer/core CLI.
- Updated public docs and release verification so removed setup/server/doctor commands are no longer advertised.

## [0.0.6] - 2026-04-14

### Added
- Added x402 exact-settlement buyer support.
- Added public documentation for Circle Gateway and x402 exact payment flows.
- Added Arc Testnet exact-settlement support documentation using CAIP-2 `eip155:5042002`.
- Added B2B SDK examples for machine-to-machine payments.
- Added a public `.env.example` with role-based configuration for agents, Circle Gateway, Thirdweb, and production hardening.

### Changed
- Moved the owner/operator CLI entrypoint away from the `omniclaw.cli` agent CLI package.
- Updated release artifact verification for the package layout.
- Reworked public README and docs around agent buyer, SDK buyer, and Financial Policy Engine paths.
- Updated the OmniClaw CLI skill to require idempotency keys for x402 URL payments.
- Bumped runtime and shipped CLI skill metadata to `0.0.6`.

## [0.0.5] - 2026-04-04

### Fixed
- Added a release verification gate so broken wheels are caught before upload.
- Added artifact checks for `omniclaw/__init__.py`, `omniclaw/cli.py`, `omniclaw/cli_agent.py`, and console entrypoints.
- Added a clean-room smoke install step for built wheels.

### Changed
- Bumped runtime version metadata to `0.0.5`.

## [0.1.0] - 2026-03-29

### Added
- **"Financial Firewall" Model**: Full production hardening with strict Owner/Agent role isolation.
- **Premium Agent CLI**: New `status`, `ledger`, and `serve` commands for `omniclaw-cli`.
- **Automated x402**: Agents now autonomously handle HTTP 402 "Payment Required" flows.
- **Zero-Friction Onboarding**: Automated entity secret generation and smart wallet preparation.
- **Service Exposure**: Agents can now expose their own payment-gated services using `omniclaw-cli serve`.
- **Idempotency & Safety**: Mandatory idempotency keys for all payments and automated "simulate-first" dry-runs.

### Changed
- Refactored `SKILL.md` to the 2026 High-Fidelity standard for AI agents.
- Consolidated all agent onboarding into a single `bootstrap.sh` self-onboarding script.
- Simplified Owner deployment to a single `docker compose up` flow.

## [0.0.3] - 2026-03-25

### Added
- Payment rail support: Circle Gateway, Coinbase CDP, OrderN, RBX, Thirdweb
- x402 buyer support for paid HTTP resources
- Trust Gate: ERC-8004 based identity and reputation verification
- Payment Intents: 2-phase commit with fund reservation
- Enhanced buyer SDK with smart payment routing

### Changed
- Rewrote the top-level documentation set for launch readability.
- Reduced README scope to the actual SDK entry points and runtime contract.
- Split docs by purpose: usage guide, API reference, architecture, and cross-chain usage.
- Removed stale or duplicate SDK markdown that conflicted with the current codebase.

### Fixed
- Documented the strict Redis environment contract around `OMNICLAW_REDIS_URL`.
- Documented trust-gate behavior so explicit trust checks require a real `OMNICLAW_RPC_URL`.
- Brought SDK-facing docs in line with the current async client surface and wallet flows.
- Fixed duplicate methods, test issues, and lint errors.

### Verified
- SDK unit suite passes with `1168` tests in `tests/`.
- All lint checks pass (0 errors).

## [0.0.2] - 2026-01-22

### Added
- Initial public alpha of the OmniClaw SDK.
- Core payment client, wallet management, routing, guards, intents, ledger, and webhook support.
- Transfer, x402, and cross-chain adapter support.
- Onboarding helpers for Circle entity secret setup.

### Notes
- Requires Python `3.10+`.
- Requires Circle Web3 Services credentials.

[0.0.2]: https://github.com/omniclaw/omniclaw/releases/tag/v0.0.2
[0.0.3]: https://github.com/omniclaw/omniclaw/releases/tag/v0.0.3
