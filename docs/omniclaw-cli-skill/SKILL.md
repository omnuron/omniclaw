---
name: omniclaw
description: >
  Use this skill whenever an agent needs to pay for an x402 URL, transfer USDC
  to an address, inspect OmniClaw balances or ledger entries, or explicitly
  expose a paid endpoint for other agents or automation with omniclaw-cli serve.
  OmniClaw is the
  Economic Execution and Control Layer for Agentic Systems. The CLI is the
  zero-trust execution layer for agents. Use this skill for the CLI execution
  path only, not for vendor SDK integration, owner setup, policy editing, wallet
  provisioning, or Financial Policy Engine administration.
metadata: '{"openclaw":{"requires":{"bins":["omniclaw-cli"],"env":["OMNICLAW_SERVER_URL","OMNICLAW_TOKEN"]},"primaryEnv":"OMNICLAW_TOKEN","required_env":["OMNICLAW_SERVER_URL","OMNICLAW_TOKEN"],"optional_env":["OMNICLAW_OWNER_TOKEN"],"required_secrets":["OMNICLAW_TOKEN"],"optional_secrets":["OMNICLAW_OWNER_TOKEN"],"required_binaries":["omniclaw-cli"],"network_access":"required","data_access":"payment URLs, recipient addresses, balances, ledger entries, and paid endpoint responses only when requested","security_notes":"Requires a trusted OmniClaw Financial Policy Engine URL and scoped agent token. OMNICLAW_OWNER_TOKEN is optional and must only be provided intentionally for owner approvals. omniclaw-cli serve binds to 0.0.0.0 and --exec runs a host command, so serve/--exec must only be used after an explicit owner request, preferably inside an isolated runtime."}}'
requires:
  - env: OMNICLAW_SERVER_URL
    description: >
      OmniClaw Financial Policy Engine base URL. Required unless the CLI was
      already persisted in local CLI config before the agent turn.
  - env: OMNICLAW_TOKEN
    description: >
      Scoped agent token. Never print, log, or transmit it. If missing, stop
      and notify the owner.
version: 0.0.8
author: Omnuron AI
---

# OmniClaw CLI Skill

## Trigger

Use `omniclaw-cli` only when the task is directly about one of these actions:

- pay for a paid URL that returns `402 Payment Required`
- transfer USDC to an address
- inspect wallet, Gateway, or Circle balances
- inspect transaction history
- expose a paid endpoint for other agents or automation with `serve`, only when the owner explicitly asks for it

Do not use this skill for:

- editing policy files
- creating wallets
- provisioning secrets
- changing allowlists, limits, or owner approvals outside the exposed CLI commands
- administering the Financial Policy Engine process itself

## Core Model

OmniClaw is not just a wallet wrapper.
It is the economic execution and control layer that combines:

- zero-trust execution through the CLI
- owner-defined financial policy through the Financial Policy Engine
- settlement rails such as direct transfers, x402, CCTP, and Circle Gateway nanopayments

This skill is specifically about the CLI execution surface.

The same CLI has two agent-side economic roles:

- buyer role: `omniclaw-cli pay`
- seller role for agent-run paid endpoints: `omniclaw-cli serve`

Vendor and enterprise seller APIs should use the Python SDK with `client.sell(...)`, not this CLI skill.

The agent does not control the private key.
The Financial Policy Engine enforces policy and signs allowed actions.

## Dependency and Credential Contract

The runtime must have:

- `omniclaw-cli` installed from the official OmniClaw package
- `OMNICLAW_SERVER_URL` pointing to the trusted Financial Policy Engine
- `OMNICLAW_TOKEN` scoped to the agent wallet/policy

Optional:

- `OMNICLAW_OWNER_TOKEN`, only when the owner intentionally grants approval authority for this run

Never print tokens, write tokens into generated files, or pass tokens to third-party services.

## Inputs The Agent Should Expect

The runtime should normally provide either:

1. environment-driven execution
- `OMNICLAW_SERVER_URL`
- `OMNICLAW_TOKEN`
- optionally `OMNICLAW_OWNER_TOKEN` if this run is allowed to approve confirmations

2. persisted CLI config
- `omniclaw-cli configure` was already run before the turn
- the CLI reads saved config values for server URL, token, wallet alias, and optional owner token

If neither is true, stop and ask the owner for:

- Financial Policy Engine URL
- agent token
- wallet alias

Do not invent or search for them yourself.

## Safe Default Workflow

### For any new spend

1. Run `omniclaw-cli status` if connectivity or health is uncertain.
2. Run `omniclaw-cli balance-detail` if Gateway balance matters.
3. Run `omniclaw-cli can-pay --recipient ...` before paying a new recipient.
4. Use `--idempotency-key` for job-based payments.
5. For direct-address payments where budget/guards matter, use `simulate` first.

### For x402 URLs

1. Run `omniclaw-cli inspect-x402 --recipient <url>` before the first live payment to confirm the seller requirements and buyer funding path.
2. Use `omniclaw-cli pay --recipient <url> --idempotency-key <unique-id>`.
3. Add `--method`, `--body`, and `--header` when the paid endpoint expects a non-GET request.
4. Add `--output` if the paid response should be saved.

### For direct address transfers

1. Use `omniclaw-cli pay --recipient <0xaddress> --amount <usdc>`.
2. Always include `--purpose`.

### For agent-run seller tasks

1. Inspect current state with `balance-detail`.
2. Confirm the owner explicitly asked this agent to expose a paid endpoint.
3. Start the paid endpoint with `omniclaw-cli serve` only for the approved endpoint, price, command, and port.
4. Remember that `serve` binds to `0.0.0.0` even if the banner prints `localhost`.

## Serve Safety Rules

`omniclaw-cli serve` is powerful because it starts a network-accessible service and requires `--exec`.

Rules:

- do not run `serve` unless the owner explicitly requested a seller endpoint in the current task
- do not invent the `--exec` command
- do not use `--exec` for shell pipelines, downloads, package installs, destructive commands, or credential access
- prefer an isolated container or private development network for `serve`
- disclose the port and endpoint before treating the service as ready

## Approval Handling

If `pay` returns approval-required output, for example:

- `requires_confirmation: true`
- `confirmation_id: ...`

Then:

- do not retry blindly
- do not invent a workaround
- if the run explicitly has owner authority, use `omniclaw-cli confirmations approve --id <confirmation-id>`
- otherwise stop and notify the owner

## Stop Conditions

Stop and notify the owner if any of these happen:

- token or Financial Policy Engine URL is missing
- `can-pay` says the recipient is blocked
- `pay` returns a policy or guard rejection
- available or Gateway balance is insufficient
- the exact command or flag is unclear
- `serve` is requested without an explicit owner instruction
- `serve --exec` is requested but the command is not supplied or approved by the owner

## Command Reference

For exact command schemas, flags, and live help output, read:

- `references/cli-reference.md`

Do not guess flags from memory when a reference is available.
