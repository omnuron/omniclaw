# API Reference

OmniClaw core exposes buyer-side payment and policy APIs.

## Python SDK

```python
from omniclaw import OmniClaw

client = OmniClaw()
```

### `pay`

```python
await client.pay(
    wallet_id="wallet-id",
    recipient="https://paid.example.com/compute",
    amount=None,
    idempotency_key="job-123",
)
```

Use `amount=None` for x402 URLs where the endpoint publishes the amount in `PAYMENT-REQUIRED`.

### Gateway Buyer Helpers

```python
await client.deposit_to_gateway(wallet_id="wallet-id", amount_usdc="10.00")
await client.withdraw_from_gateway(wallet_id="wallet-id", amount_usdc="5.00")
await client.get_gateway_balance(wallet_id="wallet-id")
await client.get_gateway_onchain_balance(wallet_id="wallet-id")
```

### Policy Engine Endpoints

The local policy engine exposes buyer payment, wallet, ledger, policy, and x402 inspection endpoints under:

```text
/api/v1
```

Start it with:

```bash
docker compose up --build omniclaw-agent
```
