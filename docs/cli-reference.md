# CLI Reference

`omniclaw-cli` is the buyer CLI for agents and automation.

## Configure

```bash
omniclaw-cli configure --server-url http://localhost:8080 --token agent-token --wallet wallet-id
```

## Inspect A Paid URL

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/compute
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
```

## Pay

```bash
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
omniclaw-cli pay --recipient 0xRecipient --amount 5.00 --idempotency-key job-124
```

## Wallets, Ledger, Intents, Confirmations

```bash
omniclaw-cli wallet list
omniclaw-cli ledger
omniclaw-cli intents
omniclaw-cli confirmations
omniclaw-cli status
```

Seller-facing paid endpoint hosting moved to the standalone hosted facilitator service.
