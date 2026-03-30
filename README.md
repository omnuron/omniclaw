# OmniClaw

OmniClaw is the economic control and trust infrastructure for autonomous agents — enabling them to pay, get paid, and transact securely under real-time policy enforcement.

It sits between raw wallet infrastructure and production payment flows so AI agents and AI-powered apps can move money with better safety, trust, and operator control. Instead of wiring wallets, payment routing, guardrails, intents, trust checks, and recovery flows by hand, OmniClaw gives you one SDK.

## Key Capabilities

- **For Agents That Pay** — guarded `pay()` execution, `simulate()` before funds move, x402 and direct transfer routing, cross-chain USDC flows, nanopayments via Circle Gateway
- **For Agents That Earn** — Seller SDK, `sell()` decorator, facilitated transfers, trust-gated access
- **For Operators That Control** — policy enforcement, spending limits, velocity controls, circuit breakers, audit-ready logs, recovery flows

## Install

```bash
pip install omniclaw
```

For local development:

```bash
uv sync --extra dev
```

## Quick Start

1. Create a `.env` file:

```
CIRCLE_API_KEY=your_circle_api_key
ENTITY_SECRET=your_entity_secret
```

2. Configure in code:

```python
from omniclaw import OmniClaw, Network

client = OmniClaw(network=Network.BASE_SEPOLIA)
```

3. Verify setup:

```bash
omniclaw doctor   # Verify credentials
omniclaw env      # List all env vars
```

## Documentation

For detailed guides and architecture docs, see the **[Wiki](https://github.com/omnuron/omniclaw/wiki)**:

| Page | Description |
|------|-------------|
| [Getting Started](https://github.com/omnuron/omniclaw/wiki/Getting-Started) | Full installation, environment setup, and first payment walkthrough |
| [Architecture](https://github.com/omnuron/omniclaw/wiki/Architecture) | System design, module breakdown, and payment flow |
| [Compliance Design](https://github.com/omnuron/omniclaw/wiki/Compliance-Design) | Authorization traceability, regulatory alignment (CLARITY Act, GENIUS Act), and gray zone analysis |
| [Trust & ERC-8004](https://github.com/omnuron/omniclaw/wiki/Trust-and-ERC-8004) | Trust evaluation framework, on-chain signals, and audit comparison |
| [API Reference](https://github.com/omnuron/omniclaw/wiki/API-Reference) | `pay()`, `simulate()`, `sell()`, NanoPayment, Trust, CLI |
| [Contributing Guide](https://github.com/omnuron/omniclaw/wiki/Contributing-Guide) | Dev setup, branch workflow, commit conventions, code quality |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Contributing Guide](https://github.com/omnuron/omniclaw/wiki/Contributing-Guide) for development setup, coding standards, and how to submit pull requests.

## License

MIT — see [LICENSE](LICENSE) for details.
