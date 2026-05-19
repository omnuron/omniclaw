# Machine-to-Machine Payments

This example documents a service-to-service payment flow where one machine consumes another machine's paid API.

Use it when an internal job runner, workflow engine, or autonomous agent needs to buy compute or data from another service without involving a human.

## What It Proves

- the consumer can inspect a paid URL
- the consumer can pay from a policy-controlled agent
- the producer can keep a clean HTTP product surface
- retries stay safe through an idempotency key

## Example Flow

Producer service:

```text
https://api.paid-resource.example/compute
```

Consumer service:

```bash
export OMNICLAW_SERVER_URL="http://127.0.0.1:8080"
export OMNICLAW_TOKEN="service-agent-token"

omniclaw-cli can-pay --recipient https://api.paid-resource.example/compute
omniclaw-cli inspect-x402 --recipient https://api.paid-resource.example/compute
omniclaw-cli pay --recipient https://api.paid-resource.example/compute --idempotency-key batch-042
```

## Service Contract

Design the downstream API so a machine can use it without special casing:

- return `402 Payment Required` when the resource is unpaid
- publish a stable URL that identifies the paid resource
- accept safe retries with the same idempotency key
- keep the paid response deterministic for the same job inputs

## When To Use Exact Or Gateway

OmniClaw chooses the route based on the endpoint's advertised requirements:

- use `GatewayWalletBatched` when the producer supports Circle Gateway nanopayments and the consumer has Gateway balance
- use `exact` when the producer supports standard x402 settlement
- let `pay` route directly when the endpoint is exact-only

That keeps the consumer side simple: one URL, one policy engine, one payment command.

## Verification Checklist

- the consumer sees `can-pay: true` before execution
- `inspect-x402` shows the endpoint's supported scheme
- payment succeeds with the same idempotency key on retry
- the producer logs a single successful fulfillment event
