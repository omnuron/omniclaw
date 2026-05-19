# Operator CLI

`omniclaw` manages OmniClaw core: setup, policy-engine server startup, and policy utilities.

Hosted facilitator operations moved to `services/hosted-facilitator`.

## Core Commands

```bash
omniclaw setup
omniclaw env
omniclaw doctor
omniclaw server --port 8080
omniclaw policy lint --path policy.json
```

## Buyer CLI

`omniclaw-cli` is the agent buyer interface:

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/compute
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
```

## Hosted Facilitator

Use the standalone service for seller/facilitator operations:

```bash
cp services/hosted-facilitator/hosted.env.example hosted.env
# edit hosted.env with the hosted facilitator signer private key and provider config
docker compose -f docker-compose.hosted.yml up --build
```

Service docs:

```text
services/hosted-facilitator/docs/
```
