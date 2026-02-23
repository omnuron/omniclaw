# Changelog

All notable changes to OmniClaw will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] - 2026-01-22

### Added
- **Core Payment Infrastructure**
  - `OmniClaw` client for autonomous AI agent payments
  - Developer-Controlled Wallets via Circle API integration
  - Universal payment routing (Transfer, x402, Cross-Chain)
  
- **Protocol Adapters**
  - `TransferAdapter`: Direct USDC transfers to blockchain addresses
  - `X402Adapter`: HTTP 402 Payment Required protocol support
  - `GatewayAdapter`: Cross-chain USDC transfers via Circle CCTP V2
  
- **CCTP V2 Fast Transfer**
  - ~2-5 second cross-chain transfers (vs 13-19 minutes standard)
  - Support for 8 networks: Ethereum, Avalanche, Optimism, Arbitrum, Base, Polygon, Arc
  - Automatic attestation polling and mint completion
  
- **Safety Guards**
  - `BudgetGuard`: Daily/hourly/total spending limits
  - `SingleTxGuard`: Per-transaction min/max amount limits
  - `RateLimitGuard`: Transaction velocity protection
  - `RecipientGuard`: Whitelist/blacklist recipient addresses
  - `ConfirmGuard`: Human-in-the-loop approval for high-value transactions
  - Atomic guard execution with concurrent safety guarantees
  
- **Payment Intents**
  - Authorize-then-Capture workflow for multi-agent coordination
  - Budget reservation without immediate execution
  - Intent confirmation and cancellation support
  
- **Observability**
  - Built-in ledger for transaction history
  - Comprehensive logging with DEBUG/INFO/WARNING levels
  - Webhook signature verification for Circle events
  
- **Developer Experience**
  - One-line payment API: `client.pay()`
  - Auto-generated Entity Secrets with recovery files
  - Configuration via environment variables
  - Batch payment processing with concurrency control
  - Simulation mode for testing without spending
  
- **Documentation**
  - 797-line comprehensive README
  - Complete API Reference (33KB)
  - CCTP usage guide with examples
  - Gas requirements documentation
  - 13 working example scripts
  
- **Testing**
  - 233 passing unit tests
  - Full coverage of CCTP, guards, routing, and protocols
  - Mock-based testing strategy

### Notes
- Initial alpha release
- Requires Python 3.10+
- Requires Circle Web3 Services API key

[0.0.2]: https://github.com/omniclaw/omniclaw/releases/tag/v0.0.2
