# Production Hardening

This document covers required runtime controls for production OmniClaw deployments.

## Required Environment

Set these for production (`OMNICLAW_ENV=production` or `mainnet`):

```env
OMNICLAW_ENV=production
OMNICLAW_STRICT_SETTLEMENT=true
OMNICLAW_SELLER_NONCE_REDIS_URL=redis://localhost:6379/1
OMNICLAW_WEBHOOK_VERIFICATION_KEY=your_public_key
OMNICLAW_WEBHOOK_DEDUP_DB_PATH=/var/lib/omniclaw/webhook_dedup.sqlite3
```

Startup fails fast if these are missing or if strict settlement is disabled.

For non-production package usage, `OMNICLAW_STRICT_SETTLEMENT` defaults to `false` so compatible x402 resources can still unlock even when a seller omits or delays settlement response metadata. Production deployments must opt into strict settlement explicitly.

## Webhook Security Model

- Signature verification is enforced when `OMNICLAW_WEBHOOK_VERIFICATION_KEY` is configured.
- Replay protection checks:
  - max replay age window (default 12h, configurable)
  - max future skew (default 5m, configurable)
- Persistent deduplication:
  - `notificationId` is stored in a SQLite table.
  - duplicate deliveries of the same `notificationId` are rejected deterministically.

Optional tuning:

```env
OMNICLAW_WEBHOOK_MAX_REPLAY_AGE_SECONDS=43200
OMNICLAW_WEBHOOK_MAX_FUTURE_SKEW_SECONDS=300
OMNICLAW_WEBHOOK_DEDUP_ENABLED=true
```

## Nonce Replay Protection

Production seller flows must use distributed nonce storage:

- `OMNICLAW_SELLER_NONCE_REDIS_URL` points to Redis.
- in-memory nonce replay protection is not accepted in production mode.

## Settlement Semantics

- `OMNICLAW_STRICT_SETTLEMENT=true` ensures success reflects irreversible settlement states.
- Do not disable strict settlement in production.

## Facilitator Strategy

OmniClaw is facilitator-agnostic. Production deployments should choose the settlement provider that fits the seller and network:

- Thirdweb-backed x402 facilitator for managed gas-sponsored exact settlement across broad EVM coverage
- Circle Gateway `GatewayWalletBatched` for gasless batched nanopayments
- external standard x402 facilitator where the seller already uses one
- self-hosted OmniClaw exact facilitator when local proof, custom network support, or enterprise self-hosting is required

Use a self-hosted facilitator when it fits the network and operational model. Use a managed facilitator when it already cleanly supports the target flow.

Before production traffic, validate the exact seller path with:

```bash
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key production-canary-001
```

For Thirdweb validation, use `examples/thirdweb-http-facilitator/README.md`.

## Canary and SLA

Use the canary script to validate end-to-end payment lifecycle before/after deploys:

```bash
python scripts/payment_canary.py \
  --wallet-id <wallet_id> \
  --recipient <recipient> \
  --amount 0.10 \
  --network <target_network> \
  --sla-seconds 300
```

Exit behavior:

- `0`: final success within SLA
- non-zero: final failure, missing transaction tracking metadata, or SLA breach

## Rollout Checklist

1. Apply required production env vars.
2. Run `omniclaw doctor`.
3. Run canary in target environment.
4. Confirm `inspect-x402` selects the expected seller scheme and network.
5. Confirm settlement appears in the selected facilitator dashboard or explorer.
6. Deploy with staged traffic.
7. Monitor:
   - settlement latency
   - webhook duplicate reject counts
   - pending settlement age distribution
8. Keep rollback path ready (app + env).
