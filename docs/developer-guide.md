# Developer Guide

This guide covers OmniClaw core buyer integration.

## Pay From Python

```python
from omniclaw import OmniClaw

client = OmniClaw()

result = await client.pay(
    wallet_id="wallet-id",
    recipient="https://paid.example.com/compute",
    amount="0.10",
    idempotency_key="job-123",
)
```

For x402 URLs, pass the maximum amount you are willing to pay. The buyer server
inspects the payment requirements and rejects the payment if the seller asks for
more than the max amount.

## Run The Policy Engine

```bash
cp .env.example .env
# Fill buyer credentials and policy tokens in .env.

docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

## Pay With The CLI

```bash
set -a; source .env; set +a
export OMNICLAW_SERVER_URL="http://127.0.0.1:9091"
export OMNICLAW_TOKEN="$OMNICLAW_AGENT_TOKEN"

omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --amount 0.10 --idempotency-key job-123
```

## Gateway Buyer Funding

Gateway nanopayments require the buyer to hold/deposit USDC into Circle Gateway before using `GatewayWalletBatched` routes. Core keeps buyer-side deposit, withdrawal, balance, and readiness helpers.
