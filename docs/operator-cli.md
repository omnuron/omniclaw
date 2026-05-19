# Core CLI

`omniclaw` and `omniclaw-cli` are aliases for the same buyer/core CLI surface.
They configure a local agent client, inspect x402 endpoints, submit buyer payments,
and query wallet, intent, ledger, and confirmation state.

Start the policy engine with Docker Compose:

```bash
docker compose up --build omniclaw-agent
```

Then configure the CLI:

```bash
omniclaw configure --server-url http://localhost:8080 --token agent-token
```

## Buyer CLI

`omniclaw-cli` remains available for compatibility:

```bash
omniclaw-cli can-pay --recipient https://paid.example.com/compute
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --idempotency-key job-123
```
