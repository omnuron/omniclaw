# Core CLI

`omniclaw` and `omniclaw-cli` are aliases for the same buyer/core CLI surface.
They configure a local agent client, inspect x402 endpoints, submit buyer payments,
and query wallet, intent, ledger, and confirmation state.

Start the policy engine with Docker Compose:

```bash
docker compose -f examples/agent/buyer/docker-compose.yml --env-file .env up --build
```

Then configure the CLI:

```bash
omniclaw configure --server-url http://127.0.0.1:9091 --token agent-token
```

## Buyer CLI

`omniclaw-cli` remains available for compatibility:

```bash
omniclaw-cli can-pay --recipient https://paid.example.com/compute
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --amount 0.10 --idempotency-key job-123
```
