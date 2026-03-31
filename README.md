# OmniClaw

The economic control and trust infrastructure for autonomous agents — enabling them to pay, get paid, and transact securely under real-time policy enforcement.

## Why OmniClaw

Every AI agent that touches money needs the same handful of things: wallet orchestration, payment routing, spending guardrails, trust evaluation, audit trails, and recovery flows. Today teams wire these by hand, one integration at a time, and re-learn the same compliance lessons the hard way.

OmniClaw replaces that patchwork with one SDK. You get guarded execution, policy enforcement, and regulatory-aware defaults out of the box — so you can focus on what your agent actually does, not how it moves money.

## Key Capabilities

**For Agents That Pay** — guarded `pay()` execution, `simulate()` before funds move, x402 and direct transfer routing, cross-chain USDC flows, nanopayments via Circle Gateway

**For Agents That Earn** — Seller SDK, `sell()` decorator, facilitated transfers, trust-gated access

**For Operators That Control** — policy enforcement, spending limits, velocity controls, circuit breakers, audit-ready logs, recovery flows

## Install

```bash
pip install omniclaw
```

For local development:

```bash
uv sync --extra dev
```

## Quick Start

### 1. Run the Server

```bash
git clone https://github.com/omnuron/omniclaw.git
cd omniclaw
```

Create a `.env` file with your Circle credentials:

```
CIRCLE_API_KEY=your_circle_api_key
ENTITY_SECRET=your_entity_secret
```

Start the server:

```bash
docker-compose up -d
# Server runs at http://localhost:8088
```

Verify the setup:

```bash
omniclaw doctor    # Verify credentials
omniclaw env       # List all env vars
```

### 2. Connect the CLI

```bash
pip install omniclaw
omniclaw-cli configure --server-url http://localhost:8088 --token <TOKEN> --wallet primary
```

### 3. Use in Code

```python
from omniclaw import OmniClaw, Network

client = OmniClaw(network=Network.BASE_SEPOLIA)
```

## Documentation

For detailed guides and architecture docs, see the [Wiki](../../wiki):

| Page | Description |
|------|-------------|
| [Getting Started](../../wiki/Getting-Started) | Full installation, environment setup, and first payment walkthrough |
| [Architecture](../../wiki/Architecture) | System design, module breakdown, and payment flow |
| [Compliance Design](../../wiki/Compliance-Design) | Authorization traceability, regulatory alignment (CLARITY Act, GENIUS Act), and gray-zone analysis |
| [Trust & ERC-8004](../../wiki/Trust-&-ERC-8004) | Trust evaluation framework, on-chain signals, and audit comparison |
| [API Reference](../../wiki/API-Reference) | `pay()`, `simulate()`, `sell()`, NanoPayment, Trust, CLI |
| [Contributing Guide](../../wiki/Contributing-Guide) | Dev setup, branch workflow, commit conventions, code quality |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Contributing Guide](../../wiki/Contributing-Guide) for development setup, coding standards, and how to submit pull requests.

## License

MIT — see [LICENSE](LICENSE) for details.
