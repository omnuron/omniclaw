# OmniClaw CLI Guide

This document is for human readers: owners, operators, reviewers, and developers.

It explains what OmniClaw CLI is, how setup works, what buyers and sellers do with the same CLI, how approval flows work, and where to find the exact live command reference.

## Executive Summary

`omniclaw-cli` is the agent-facing zero-trust execution layer for OmniClaw.

OmniClaw itself is the **Economic Execution and Control Layer for Agentic Systems**.
That full system is larger than the CLI alone:

- the CLI is the constrained execution surface the agent uses
- the Financial Policy Engine is the owner-run enforcement and signing layer
- the settlement rails include direct USDC transfers, x402, CCTP, and Circle Gateway nanopayments
- the policy, trust, ledger, and concurrency controls are part of the overall OmniClaw system

It is the same CLI for agent-side economic execution:

- buyer side: `omniclaw-cli pay`
- seller side for agent-run paid endpoints: `omniclaw-cli serve`

Vendor and enterprise seller APIs should use the Python SDK with `client.sell(...)`.

That two-sided model matters:

- without a seller exposing a paid endpoint with `serve`, there is nothing meaningful for a buyer to pay through x402
- without a buyer using `pay`, the seller endpoint does not earn

OmniClaw keeps the private key and policy enforcement on the Financial Policy Engine side.
The agent uses the CLI as a constrained execution surface.

## Reader Split

There are now three separate artifacts, each with a different audience:

- `docs/agent-skills.md`
  - human/operator guide
- `docs/omniclaw-cli-skill/SKILL.md`
  - public shipped skill specification
- `docs/cli-reference.md`
  - exact generated command reference for the public CLI surface

This split is deliberate.
It keeps the public skill specification separate from the human/operator guide and generated command reference.

## Setup Model

A typical OmniClaw agent runtime needs:

- `OMNICLAW_SERVER_URL`: Financial Policy Engine URL, for example `http://localhost:9090`
- `OMNICLAW_TOKEN`: scoped agent token
- optionally `OMNICLAW_OWNER_TOKEN`: only if the run is allowed to approve confirmations

For local convenience, you can persist those values in CLI config. `configure` writes saved CLI config; it does not export shell environment variables:

```bash
omniclaw-cli configure \
  --server-url http://localhost:9090 \
  --token payment-agent-token \
  --wallet omni-bot-v4
```

Available `configure` flags:

- `--server-url TEXT`
- `--token TEXT`
- `--wallet TEXT`
- `--owner-token TEXT`
- `--show`
- `--show-raw`
- `--interactive`

Show saved config:

```bash
omniclaw-cli configure --show
```

When the CLI has been configured already, later commands such as `balance`, `can-pay`, `pay`, and `serve` can reuse that saved config without re-exporting `OMNICLAW_SERVER_URL` and `OMNICLAW_TOKEN` in the shell.

## Runtime Architecture

Typical execution path:

1. owner starts the Financial Policy Engine
2. owner provisions policy and agent token(s)
3. agent invokes `omniclaw-cli`
4. Financial Policy Engine validates policy, balance, trust, and approval rules
5. only approved actions are signed and executed

In the normal CLI-agent model, the agent should not be given direct wallet secrets.

This matches the official OmniClaw framing:

- agents execute
- policies authorize
- infrastructure settles

## Buyer Flows

### Pay a paid URL

```bash
omniclaw-cli can-pay --recipient https://api.vendor.com/data
omniclaw-cli pay --recipient https://api.vendor.com/data --idempotency-key job-123
```

### Pay a paid POST endpoint

```bash
omniclaw-cli pay \
  --recipient https://api.vendor.com/inference \
  --method POST \
  --body '{"prompt":"hello"}' \
  --header 'Content-Type: application/json' \
  --idempotency-key job-123
```

### Direct USDC transfer

```bash
omniclaw-cli pay \
  --recipient 0xRecipientAddress \
  --amount 5.00 \
  --purpose "service payment" \
  --idempotency-key job-123
```

### Buyer-side inspection and preparation

Useful buyer commands:

- `status`
- `address`
- `balance`
- `balance-detail`
- `can-pay`
- `simulate`
- `pay`
- `deposit`
- `withdraw`
- `withdraw-trustless`
- `withdraw-trustless-complete`
- `ledger`

## Seller Flows

### Expose a paid endpoint

Only use this path when the owner explicitly wants an agent-run seller endpoint. Vendor and enterprise APIs should use the SDK seller middleware instead.

```bash
omniclaw-cli serve \
  --price 0.01 \
  --endpoint /api/data \
  --exec "python safe_readonly_service.py" \
  --port 8000
```

What `serve` does:

- starts an x402 payment gate
- returns `402 Payment Required` to unpaid callers
- verifies payment through Circle Gateway middleware
- runs the command supplied via `--exec`
- returns command output to the paid caller

Important implementation detail:

- `serve` binds to `0.0.0.0`
- the banner may print `localhost`, but the actual bind host is all interfaces
- `--exec` runs the supplied host command after payment verification
- do not invent the `--exec` command; run only a command supplied or approved by the owner
- prefer an isolated container or private development network for `serve`

Useful seller commands:

- `status`
- `address`
- `balance`
- `balance-detail`
- `serve`
- `ledger`

## Approval and Intent Flows

Some policies require approval before spend.
In those cases `pay` can return fields such as:

- `requires_confirmation: true`
- `confirmation_id: ...`

Owner approval commands:

```bash
omniclaw-cli confirmations get --id <confirmation-id>
omniclaw-cli confirmations approve --id <confirmation-id>
omniclaw-cli confirmations deny --id <confirmation-id>
```

Intent commands:

```bash
omniclaw-cli create-intent --recipient 0xRecipient --amount 5.00 --purpose "vendor payment"
omniclaw-cli confirm-intent --intent-id <intent-id>
omniclaw-cli get-intent --intent-id <intent-id>
omniclaw-cli cancel-intent --intent-id <intent-id> --reason "no longer needed"
```

## Full Command Surface

Current top-level commands exposed by the CLI:

- `configure`
- `address`
- `balance`
- `balance-detail`
- `balance_detail`
- `deposit`
- `withdraw`
- `withdraw-trustless`
- `withdraw_trustless`
- `withdraw-trustless-complete`
- `withdraw_trustless_complete`
- `pay`
- `simulate`
- `can-pay`
- `can_pay`
- `create-intent`
- `create_intent`
- `confirm-intent`
- `confirm_intent`
- `get-intent`
- `get_intent`
- `cancel-intent`
- `cancel_intent`
- `ledger`
- `list-tx`
- `list_tx`
- `serve`
- `status`
- `ping`
- `wallet`
- `intents`
- `confirmations`

## Command Families

### Payment execution

- `pay`
- `simulate`
- `can-pay`
- `create-intent`
- `confirm-intent`
- `get-intent`
- `cancel-intent`
- `confirmations get|approve|deny`

### Balance and funds movement

- `address`
- `balance`
- `balance-detail`
- `deposit`
- `withdraw`
- `withdraw-trustless`
- `withdraw-trustless-complete`

### Seller execution

- `serve`

### Inspection

- `status`
- `ping`
- `ledger`
- `list-tx`

## Recommended Operational Rules

- use `can-pay` for new recipients
- use `inspect-x402` for a new paid URL before the first live payment
- use `--idempotency-key` for job-based payments
- use `balance-detail` when Gateway balances matter
- use `simulate` when the amount or guard risk is non-trivial
- do not give agents raw wallet secrets in the normal CLI path
- treat `serve` and `pay` as one economic system, not separate products

## Auto-Generated Reference

The exact command reference is generated from the live CLI help surface.

Regenerate it with:

```bash
python docs/omniclaw-cli-skill/scripts/generate_cli_reference.py
```

Generated outputs:

- `docs/cli-reference.md`

That keeps the documented flags and command surface aligned with the actual CLI.

## Why There Is No `agents/openai.yaml`

`agents/openai.yaml` is optional UI metadata.

It is useful for things like:

- display names in skill pickers
- short descriptions in UI chips
- marketplace-style metadata

It is not required for the OmniClaw agent skill to work.

For this repository, the public sources of truth are:

- `docs/omniclaw-cli-skill/SKILL.md`
- `docs/cli-reference.md`

That keeps the shipped skill and the shipped command reference in public docs.

## Ship Recommendation

This is now the recommended storage layout:

- keep public shipped skill specs under `docs/`
- keep repo-local internal-use skills under `.agents/skills/`
- keep human/operator docs under `docs/`
- keep the exact CLI reference generated, not handwritten

That is the cleanest split for long-term maintenance and for reducing agent mistakes.
