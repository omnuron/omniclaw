# OmniClaw

> **The Payment Execution Infrastructure for AI Agents**

[![PyPI version](https://badge.fury.io/py/omniclaw.svg)](https://badge.fury.io/py/omniclaw)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-100%25%20passing-brightgreen)]()
[![ERC-8004](https://img.shields.io/badge/ERC--8004-Compliant-blue)]()

**OmniClaw** gives AI agents the ability to autonomously spend money—safely, instantly, and across any blockchain. It's the first SDK to combine **payment execution**, **agent identity verification** (ERC-8004), and **enterprise-grade resilience** in a single library.

> 💡 *Think of it as Stripe for AI agents—except instead of helping merchants accept payments, we help agents make payments, verify trust, and coordinate safely.*

📖 **[Full Feature Reference →](docs/FEATURES.md)** — Detailed API docs, mermaid diagrams, execution pipeline, and 281-test coverage breakdown.

---

## 🔑 What is OmniClaw?

OmniClaw is a **developer SDK** that provides the complete payment infrastructure layer for autonomous AI agents:

| Capability | Description |
|:-----------|:------------|
| 💳 **Developer-Controlled Wallets** | USDC wallets powered by Circle with full programmatic control |
| 🛡️ **Safety Kernel** | Budget, rate, transaction, and recipient guards with atomic guarantees |
| 🌐 **Universal Payment Routing** | Seamless routing across x402 APIs, direct transfers, and cross-chain (CCTP) |
| 🔐 **ERC-8004 Trust Gate** | On-chain agent identity verification + reputation scoring |
| 🔒 **2-Phase Commit & Fund Locking** | Distributed mutex locks prevent double-spending across agent swarms |
| ⚡ **Circuit Breaker & Retry** | Distributed resilience layer with exponential backoff |
| 📊 **Complete Observability** | Built-in ledger, webhooks, and analytics for every transaction |
| 🔌 **Framework Agnostic** | Works with LangChain, OmniCoreAgent, AutoGPT, or any custom agent |

---

## ⚡ Get Started in 3 Lines

```python
from omniclaw import OmniClaw

client = OmniClaw()  # Reads CIRCLE_API_KEY from env
result = await client.pay(wallet_id="...", recipient="0x...", amount=10.00)
```

**Zero blockchain complexity. Zero private key management. One `pay()` call.**

---

## 📚 Table of Contents

1.  [**Core Architecture**](#-core-architecture)
2.  [**Installation**](#-installation)
3.  [**Quick Start**](#-quick-start)
4.  [**Payment Routing**](#-payment-routing)
5.  [**The Guard System (Safety Kernel)**](#-the-guard-system-safety-kernel)
6.  [**ERC-8004 Trust Gate**](#-erc-8004-trust-gate)
7.  [**2-Phase Commit & Fund Locking**](#-2-phase-commit--fund-locking)
8.  [**Circuit Breaker & Resilience**](#-circuit-breaker--resilience)
9.  [**Payment Intents (Auth/Capture)**](#-payment-intents-authcapture)
10. [**Agent Identity & Resolution**](#-agent-identity--resolution)
11. [**Wallet Management**](#-wallet-management)
12. [**Configuration Reference**](#-configuration-reference)
13. [**Observability & Ledger**](#-observability--ledger)
14. [**Webhooks & Events**](#-webhooks--events)
15. [**Testing**](#-testing)
16. [**Security & Best Practices**](#-security--best-practices)
17. [**Error Handling**](#-error-handling)
18. [**Contributing**](#-contributing)

---

## 🏗️ Core Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                             │
│  Research Agent │ Trading Bot │ HR Agent │ Agent Swarms         │
│  Built with: LangChain, OmniCoreAgent, AutoGPT, etc.          │
└──────────────────────────┬─────────────────────────────────────┘
                           │ uses
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  🎯 OMNICLAW SDK                                               │
│                                                                │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Trust Gate  │  │ Safety Kernel│  │  Payment Router      │  │
│  │  (ERC-8004)  │  │  (5 Guards)  │  │  Transfer│x402│CCTP  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────┐  │
│  │   Identity   │  │  Fund Lock   │  │     Resilience       │  │
│  │   Resolver   │  │  (2PC/Mutex) │  │  Circuit│Retry│Backoff│  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Intents   │  │    Ledger    │  │     Webhooks         │  │
│  │ Auth/Capture│  │  Audit Trail │  │  Event Processing    │  │
│  └─────────────┘  └──────────────┘  └──────────────────────┘  │
└──────────────────────────┬─────────────────────────────────────┘
                           │ implements
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  PROTOCOL LAYER                                                │
│  x402 │ ERC-8004 │ CCTP │ UCP │ AP2                            │
└──────────────────────────┬─────────────────────────────────────┘
                           │ settles on
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  BLOCKCHAIN LAYER                                              │
│  Ethereum │ Base │ Arbitrum │ Optimism │ Polygon │ Solana      │
└────────────────────────────────────────────────────────────────┘
```

### Module Map

| Module | Path | Purpose |
|:-------|:-----|:--------|
| **Client** | `omniclaw/client.py` | Main SDK entry point — `OmniClaw` class |
| **Trust Gate** | `omniclaw/trust/` | ERC-8004 trust evaluation pipeline |
| **Identity** | `omniclaw/identity/` | Agent identity resolution & types |
| **Guards** | `omniclaw/guards/` | 5 safety guards with atomic guarantees |
| **Payment Router** | `omniclaw/payment/` | Intelligent routing (Transfer, x402, CCTP) |
| **Protocols** | `omniclaw/protocols/` | x402, CCTP adapter implementations |
| **Intents** | `omniclaw/intents/` | Auth/Capture workflows + fund reservation |
| **Ledger** | `omniclaw/ledger/` | Transaction audit trail + fund locking (2PC) |
| **Resilience** | `omniclaw/resilience/` | Circuit breaker + retry with backoff |
| **Storage** | `omniclaw/storage/` | Memory & Redis backends |
| **Core** | `omniclaw/core/` | Types, exceptions, ERC-8004 ABIs, config |
| **Webhooks** | `omniclaw/webhooks/` | Ed25519 signature verification |
| **Wallet** | `omniclaw/wallet/` | Circle wallet management |

---

## 📦 Installation

```bash
pip install omniclaw
```

Or using `uv` (recommended for speed):

```bash
uv add omniclaw
```

**Requirements:**
*   Python 3.10+
*   A Circle Web3 Services API Key ([Get one here](https://console.circle.com))

---

## ⚡ Quick Start

### 1. Initialize the Client

```python
import logging
from omniclaw import OmniClaw, Network

client = OmniClaw(
    network=Network.ARC_TESTNET,
    log_level=logging.INFO,
    trust_policy="standard",              # ERC-8004: "permissive" | "standard" | "strict"
    rpc_url="https://eth.llamarpc.com",    # RPC for on-chain identity reads
)
```

### 2. Create a Wallet

```python
wallet_set, wallet = await client.create_agent_wallet(agent_name="Agent-007")
print(f"Agent Wallet Address: {wallet.address}")
```

### 3. Add Safety Guards

```python
await client.add_budget_guard(wallet.id, daily_limit="100.00")
await client.add_recipient_guard(wallet.id, mode="whitelist",
    domains=["api.openai.com", "anthropic.com"])
```

### 4. Execute Payment

```python
result = await client.pay(
    wallet_id=wallet.id,
    recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
    amount="10.50",
    purpose="Server costs for Jan 2025",
    strategy="retry_then_fail",  # "fail_fast" | "retry_then_fail" | "queue_background"
    check_trust=True,            # ERC-8004 check: True | False | None (auto)
)
if result.success:
    print(f"Payment Confirmed! Tx: {result.blockchain_tx}")
    print(f"Trust Score: {result.metadata['trust']['wts']}")  # ERC-8004 WTS
```

The `pay()` pipeline runs **10 steps** automatically:

1. **Trust Gate** (ERC-8004) → identity check + reputation scoring → `APPROVED` / `HELD` / `BLOCKED`
2. **Ledger entry** → audit trail created
3. **Guard chain** → budget, rate, recipient, confirm checks (atomic reserve)
4. **Fund lock** → distributed mutex acquired
5. **Balance check** → available = balance − reservations
6. **Circuit breaker** → check upstream health
7. **Router** → select adapter (Transfer / x402 / CCTP)
8. **Execute** → with retry strategy
9. **Commit/release** → guards finalized or rolled back
10. **Unlock** → mutex released

---

## 🔌 Payment Routing

OmniClaw automatically routes payments through the right protocol. You just call `pay()`.

### Transfer Adapter — Direct USDC Transfers
**When**: Recipient is a blockchain address (`0x...`)

```python
result = await client.pay(wallet_id=wallet.id,
    recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0", amount="25.00")
```

### x402 Adapter — Pay-Per-Use APIs
**When**: Recipient is an HTTP URL (`https://...`)

```python
result = await client.pay(wallet_id=wallet.id,
    recipient="https://api.premium-data.com/resource", amount="0.10")
```

The [x402 protocol](https://x402.org) enables `HTTP 402 Payment Required` flows — your agent pays for API access automatically.

### Gateway Adapter — Cross-Chain Transfers
**When**: `destination_chain` is specified

```python
result = await client.pay(wallet_id=wallet.id,
    recipient="0xRecipientOnBase...", amount="100.00",
    destination_chain=Network.BASE)
```

Uses Circle's CCTP to move USDC between chains without bridges.

### Simulation

```python
sim = await client.simulate(wallet_id=wallet.id, recipient="0x...", amount="1000000.00")
if not sim.would_succeed:
    print(f"Blocked: {sim.reason}")
```

---

## 🛡 The Guard System (Safety Kernel)

The Guard System is a programmable firewall for your agent's money. Guards are checked **atomically** — using Redis Lua scripts or memory locks — preventing race conditions even under concurrent load.

| Guard | Purpose | Key Parameters |
|:------|:--------|:--------------|
| **BudgetGuard** | Spending limits over time | `daily_limit`, `hourly_limit`, `total_limit` |
| **RateLimitGuard** | Prevent tx flooding | `max_per_minute`, `max_per_hour` |
| **SingleTxGuard** | Cap individual payments | `max_amount`, `min_amount` |
| **RecipientGuard** | Control who gets paid | `mode`, `addresses`, `domains`, `patterns` |
| **ConfirmGuard** | Human-in-the-loop | `threshold`, `callback` |

```python
# Budget: $50/day, $10/hour, $1000 lifetime
await client.add_budget_guard(wallet.id,
    daily_limit="50.00", hourly_limit="10.00", total_limit="1000.00")

# Rate: Max 5 tx/min
await client.add_rate_limit_guard(wallet.id, max_per_minute=5, max_per_hour=20)

# Transaction size: $0.50 - $100
await client.add_single_tx_guard(wallet.id, max_amount="100.00", min_amount="0.50")

# Whitelist recipients
await client.add_recipient_guard(wallet.id, mode="whitelist",
    addresses=["0xVendor1...", "0xVendor2..."])

# Human approval for >$500
await client.add_confirm_guard(wallet.id, threshold="500.00")
```

### Atomic Guarantees

> 10 parallel requests of $10 against a $50 budget → **Exactly 5 succeed. 5 fail with `BudgetExceeded`.**

Reservation tokens are issued during the check phase and committed only upon success. Failed transactions release reservations.

---

## 🔐 ERC-8004 Trust Gate

OmniClaw implements the [ERC-8004 Trustless Agents](https://eips.ethereum.org/EIPS/eip-8004) standard for on-chain agent identity verification and reputation scoring.

### What It Does

Before executing a payment, the Trust Gate evaluates the recipient against on-chain data:

```
Payment Request → Trust Gate → Identity Registry → Reputation Registry → Policy Engine → Verdict
                                    │                      │
                                    ▼                      ▼
                              Agent Identity         Reputation Score
                              (ERC-721 token)        (WTS algorithm)
```

### Per-Payment Trust Control

The `check_trust` parameter lets you control ERC-8004 checks per payment, independently from safety guards:

```python
# Auto (default): check trust if trust_gate configured and guards not skipped
await client.pay(wallet_id=w, recipient="0x...", amount="10.00")

# Force trust check even with skip_guards=True
await client.pay(wallet_id=w, recipient="0x...", amount="10.00",
    skip_guards=True, check_trust=True)

# Skip trust check but keep safety guards active
await client.pay(wallet_id=w, recipient="0x...", amount="10.00",
    check_trust=False)

# Simulate also supports check_trust
sim = await client.simulate(wallet_id=w, recipient="0x...", amount="10.00",
    check_trust=False)
```

| `check_trust` | `skip_guards` | Trust Gate Runs? |
|:-------------|:-------------|:----------------|
| `None` (default) | `False` | ✅ Yes |
| `None` (default) | `True` | ❌ No |
| `True` | `True` | ✅ Yes |
| `False` | `False` | ❌ No |

### Verdicts

| Verdict | Meaning | Action |
|:--------|:--------|:-------|
| ✅ `APPROVED` | Trusted agent, good reputation | Payment proceeds |
| ⏸️ `HELD` | New/unverified agent | Queued for human review |
| 🚫 `BLOCKED` | Fraud flag, blocklisted, or failed policy | Payment rejected |

### 10-Check Policy Engine

The Trust Gate applies checks in strict priority order:

1. **Blocklist** — Address blocked? → `BLOCKED`
2. **Whitelist** — Org-whitelisted? → Skip remaining checks
3. **Identity Required** — Is registration on-chain?
4. **Fraud Tag** — `fraud`, `scam`, `phishing` detected?
5. **New Agent** — Too few feedback signals?
6. **Min Feedback Count** — Enough data points?
7. **Min WTS** — Weighted Trust Score above threshold?
8. **High-Value WTS** — Extra scrutiny for large payments
9. **Attestations** — Required certs (e.g., `kyb`) present?
10. **All Pass** → `APPROVED`

### Policy Presets

```python
from omniclaw.identity.types import TrustPolicy

# Use presets
permissive = TrustPolicy.permissive()  # Pass most, block known fraud
standard   = TrustPolicy.standard()    # Hold new agents, min WTS=50
strict     = TrustPolicy.strict()      # Enterprise: WTS≥70, KYB required
```

### ERC-8004 Registry Coverage

| Registry | Functions | Status |
|:---------|:---------|:-------|
| Identity (ERC-721 + extensions) | 13 functions | ✅ Complete |
| Reputation (Feedback + Scoring) | 10 functions | ✅ Complete |
| Validation (Request/Response) | 5 functions | ✅ ABI ready (awaiting mainnet deployment) |

**28 total function selectors** — all keccak256-verified against the official spec.

### Deployed Contract Addresses

| Network | Identity Registry | Reputation Registry |
|:--------|:-----------------|:-------------------|
| ETH Mainnet | `0x8004A169FB4a3325...` | `0x8004BAa17C55a881...` |
| Base Sepolia | `0x8004A818BFB912...` | `0x8004B663056A597D...` |
| ETH Sepolia | `0x8004A818BFB912...` | `0x8004B663056A597D...` |

### Weighted Trust Score (WTS) Algorithm

The scoring engine computes a 0-100 reputation score:

1. **Filter self-reviews** — Agent's own feedback excluded
2. **Recency decay** — Recent feedback weighted higher (1.0x → 0.5x → 0.2x)
3. **Verified submitter boost** — 1.5x weight for registered agents
4. **Fraud tag detection** — Flags `fraud`, `scam`, `malicious`, `spam`, `phishing`
5. **Weighted average** — normalized_score × weight / total_weight
6. **Min sample guard** — <3 signals → `new_agent` flag

### Cache TTLs

| Data Type | TTL | Purpose |
|:----------|:----|:--------|
| Identity | 5 min | On-chain agent registration |
| Reputation | 2 min | Feedback signals (changes frequently) |
| Metadata | 10 min | Off-chain registration file |
| Policy | 60 min | Policy config (rarely changes) |

---

## 🔒 2-Phase Commit & Fund Locking

OmniClaw prevents double-spending across concurrent agents with a **distributed 2-Phase Commit** system.

### How It Works

```
Phase 1 (Prepare):
  Agent A wants to pay $50
  → FundLockService.acquire(wallet_id, $50)
  → Distributed mutex acquired (Redis/Memory)
  → Guards check + budget reservation

Phase 2 (Commit/Rollback):
  Success → Execute payment → Release lock
  Failure → Rollback reservation → Release lock
```

### Fund Lock Service

```python
from omniclaw.ledger.lock import FundLockService

lock_service = FundLockService(storage=redis_backend)

# Acquire: Returns a lock token (or None if contention)
token = await lock_service.acquire(
    wallet_id="wallet_123",
    amount=Decimal("50.00"),
    ttl=30,          # Lock expires after 30s (deadlock protection)
    retry_count=3,   # Retry 3 times if wallet is locked
    retry_delay=0.5  # Wait 500ms between retries
)

# Release after payment
await lock_service.release_with_key("wallet_123", token)
```

### Fund Reservation Service

Used by the Intent system to reserve funds across multiple pending intents:

```python
from omniclaw.intents.reservation import ReservationService

reservations = ReservationService(storage=redis_backend)
await reservations.reserve("wallet_123", Decimal("200.00"), intent_id="intent_abc")

# Check total reserved for a wallet
total = await reservations.get_reserved_total("wallet_123")

# Release when intent completes or cancels
await reservations.release("intent_abc")
```

---

## ⚡ Circuit Breaker & Resilience

OmniClaw includes a **distributed circuit breaker** and **retry engine** to handle upstream failures gracefully.

### Circuit Breaker

Wraps critical external calls (Circle API, RPC providers). If failures exceed a threshold, the circuit **trips** and blocks further calls until recovery.

```
CLOSED (normal) → 5 failures → OPEN (blocking) → 30s timeout → HALF_OPEN (test) → success → CLOSED
                                                                                   → failure → OPEN
```

```python
from omniclaw.resilience.circuit import CircuitBreaker

breaker = CircuitBreaker(
    service_name="circle_api",
    storage=redis_backend,
    failure_threshold=5,    # Trip after 5 failures
    recovery_timeout=30,    # Block for 30 seconds
    cleanup_window=60       # Rolling failure window
)

# Use as async context manager
async with breaker:
    result = await circle_client.create_transfer(...)
# Failures auto-recorded; successes heal the circuit
```

### Retry Policy

Exponential backoff (1s → 2s → 4s → 8s → 16s) with smart transient error detection:

```python
from omniclaw.resilience.retry import execute_with_retry

result = await execute_with_retry(
    client.pay, wallet_id=wallet.id, recipient="0x...", amount="10.00"
)
# Only retries on: timeout, 500/502/503/504, connection refused, rate limit
# Never retries on: GuardError, InsufficientBalanceError, ValidationError
```

---

## 🧠 Payment Intents (Auth/Capture)

Payment Intents separate **Authorization** from **Capture** for multi-agent coordination, human review, and scheduled execution.

```python
# 1. Create: Guard check + budget reservation (no blockchain tx)
intent = await client.create_payment_intent(
    wallet_id=wallet.id, recipient="0xSupplier...",
    amount="2000.00", purpose="Q1 Supply Restock"
)
# Status: requires_confirmation

# 2. Confirm: Execute the pre-authorized payment
result = await client.confirm_payment_intent(intent.id)
# Status: succeeded

# 3. Cancel (releases reserved budget)
await client.cancel_payment_intent(intent.id)
# Status: canceled
```

---

## 🆔 Agent Identity & Resolution

The Identity Resolver fetches on-chain agent data from ERC-8004 registries and retrieves off-chain registration files.

### Supported URI Schemes

| Scheme | Example | Method |
|:-------|:--------|:-------|
| HTTPS | `https://agent.com/registration.json` | `httpx` fetch |
| IPFS | `ipfs://QmXyz...` | Gateway fallback (3 gateways) |
| Data URI | `data:application/json;base64,...` | Base64 decode |

### Registration File Schema (ERC-8004)

```json
{
  "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
  "name": "MyAgent",
  "description": "Autonomous trading bot",
  "services": [
    {"name": "A2A", "endpoint": "https://agent.example.com/a2a", "version": "1.0"}
  ],
  "registrations": [
    {"agentId": 42, "agentRegistry": "eip155:1:0x8004A169..."}
  ],
  "supportedTrust": ["reputation", "crypto-economic"]
}
```

### Endpoint Domain Verification (EIP-8004 §5)

Optionally verify that HTTPS endpoints are controlled by the agent owner:

```python
from omniclaw.identity.resolver import IdentityResolver

resolver = IdentityResolver()
verified = await resolver.verify_all_endpoints(identity)
# Returns: ["a2a.agent.com", "mcp.agent.com"]
```

Checks `https://{domain}/.well-known/agent-registration.json` for a matching `agentId` and `agentRegistry`.

---

## Wallet Management

### Agent Wallets

```python
wallet_set, wallet = await client.create_agent_wallet(
    agent_name="ShoppingBot-1",
    blockchain=Network.ARC
)
```

### User Wallets

```python
wallet_set, wallet = await client.create_user_wallet(
    user_id="user_88123",
    blockchain=Network.SOLANA
)
```

### Wallet Sets

```python
marketing_swarm = await client.create_wallet_set(name="marketing-swarm")
agent_a = await client.create_wallet(wallet_set_id=marketing_swarm.id, blockchain=Network.ETH)
agent_b = await client.create_wallet(wallet_set_id=marketing_swarm.id, blockchain=Network.ARC)
```

---

## ⚙ Configuration Reference

### Environment Variables

| Variable | Required | Description | Default |
|:---------|:---------|:------------|:--------|
| `CIRCLE_API_KEY` | **Yes** | Circle Console API key | — |
| `ENTITY_SECRET` | No | 32-byte hex secret for signing | **Auto-Generated** |
| `OMNICLAW_RPC_URL` | No | Ethereum RPC endpoint for ERC-8004 | — |
| `OMNICLAW_STORAGE_BACKEND` | No | `memory` or `redis` | `memory` |
| `OMNICLAW_REDIS_URL` | No | Redis connection string | `redis://localhost:6379/0` |
| `OMNICLAW_LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `OMNICLAW_ENV` | No | `production` or `development` | `development` |

### Constructor

```python
client = OmniClaw(
    circle_api_key="...",         # Or from CIRCLE_API_KEY env
    entity_secret="...",          # Or from ENTITY_SECRET env
    network=Network.ARC_TESTNET,  # Target blockchain
    log_level=logging.DEBUG,      # Logging verbosity
    trust_policy="standard",      # ERC-8004 trust preset (or TrustPolicy object)
    rpc_url="https://eth.llamarpc.com",  # RPC for on-chain reads (comma-separated for fallback)
)
```

### Entity Secret Auto-Setup

When you initialize without an `ENTITY_SECRET`:
1. SDK generates a new 32-byte secret
2. Registers it with Circle API
3. Saves a recovery file to `~/.config/omniclaw/`
4. Appends the secret to your `.env` file

---

## 📊 Observability & Ledger

Every transaction — successful, failed, or blocked — is recorded in the OmniClaw Ledger.

```python
# Get full history
history = await client.ledger.get_history(wallet_id=wallet.id)

# Sync with blockchain
updated = await client.sync_transaction(entry_id="entry_123")
```

---

## 🎣 Webhooks & Events

Verifiable webhook parser with Ed25519 signature verification:

```python
@app.post("/webhooks/circle")
async def handle_webhook(request: Request):
    body = await request.body()
    event = client.webhooks.handle(body, request.headers)

    if event.type == "payment.received":
        print(f"Received {event.data.amount} USDC!")
```

**Supported Events:** `payment.received`, `payment.sent`, `transaction.failed`

---

## 🧪 Testing

OmniClaw has a comprehensive test suite with **25 test files** covering all modules.

```bash
# Run all trust gate tests (100 tests)
uv run pytest tests/test_trust_gate.py tests/test_trust_gate_integration.py -v

# Run all tests
uv run pytest tests/ -v
```

### Test Coverage

| Area | Test File | Tests |
|:-----|:---------|:------|
| Trust Gate | `test_trust_gate.py` | Policy, scoring, cache, identity, ABI |
| Trust Gate Integration | `test_trust_gate_integration.py` | 11 real-world scenarios |
| Guards | `test_guards.py`, `test_guard_edge_cases.py` | All 5 guard types |
| Circuit Breaker | `test_circuit_breaker.py` | State transitions |
| Fund Locking | `test_fund_lock.py` | 2PC, mutex, deadlock |
| Payment Intents | `test_payment_intents.py`, `test_intent_lifecycle.py` | Auth/capture/cancel lifecycle |
| Concurrency | `test_payment_concurrency.py` | Race conditions |
| Payment Router | `test_payment_router.py` | Adapter selection |
| x402 Protocol | `test_x402.py` | HTTP 402 handshake |
| CCTP/Gateway | `test_gateway.py`, `test_cctp_*.py` | Cross-chain |
| Simulation | `test_simulation.py` | Dry-run predictions |
| Webhooks | `test_webhook_verification.py` | Ed25519 signatures |
| Client | `test_client.py` | SDK entry point |
| Types | `test_types.py` | Data structures |
| Ledger | `test_ledger.py` | Audit trail |

---

## 🔐 Security & Best Practices

1.  **Environment Variables** — Never hardcode API keys or Entity Secrets
2.  **Least Privilege** — Give agents only the budget they need
3.  **Strict Recipient Guards** — Whitelist known vendor addresses
4.  **Use Intents for High Value** — Require 2-step confirmation for >$1000
5.  **ERC-8004 Trust Gate** — Enable on-chain identity checks for unknown recipients
6.  **Circuit Breakers** — Wrap all external API calls to prevent cascade failures
7.  **Monitor Logs** — Run with `WARNING` in prod, alert on `BLOCKED` payments
8.  **Use Redis in Production** — Memory backend is for development only

---

## ⚠️ Error Handling

OmniClaw uses a typed exception hierarchy:

```
OmniClawError (Base)
├── ConfigurationError     — Missing keys, bad config
├── WalletError            — Wallet not found, invalid state
├── PaymentError           — Payment execution failure
│   ├── InsufficientBalanceError
│   ├── GuardError         — Blocked by safety policy
│   └── TransactionTimeoutError
├── NetworkError           — API unreachable
├── ValidationError        — Invalid input
└── CircuitOpenError       — Service circuit tripped
```

**Retry Rules:**
*   ✅ **Auto-retry**: `NetworkError`, `5xx` responses, timeouts
*   ❌ **Never retry**: `GuardError`, `InsufficientBalanceError`, `ValidationError`

---

## 🤝 Contributing

1.  **Fork** the repository
2.  **Install**: `pip install -e ".[dev]"`
3.  **Test**: `uv run pytest tests/ -v`
4.  **Submit PR** with tests

License: **MIT**