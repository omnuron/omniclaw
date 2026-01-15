# OmniAgentPay: The Payment Infrastructure for AI Agents

[![PyPI version](https://badge.fury.io/py/omniagentpay.svg)](https://badge.fury.io/py/omniagentpay)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**OmniAgentPay** is the payment infrastructure layer built specifically for **Autonomous AI Agents**. It abstracts blockchain complexity into a unified interface while enforcing strict safety boundaries through a programmable Safety Kernel.

Traditional blockchain SDKs are designed for humans with screens, private keys, and confirmation buttons. **OmniAgentPay** is designed for code that thinks, reasons, and executes transactions autonomously.

---

## 📚 Table of Contents

1.  [**Why OmniAgentPay?**](#-why-omniagentpay)
2.  [**Core Architecture**](#-core-architecture)
3.  [**Installation**](#-installation)
4.  [**Quick Start**](#-quick-start)
5.  [**Configuration Reference**](#-configuration-reference)
6.  [**Wallet Management**](#-wallet-management)
    *   [Agent Wallets](#agent-wallets)
    *   [User Wallets](#user-wallets)
    *   [Wallet Sets](#wallet-sets)
7.  [**The Payment API**](#-the-payment-api)
    *   [Understanding `pay()`](#understanding-pay)
    *   [Automatic Routing](#automatic-routing)
    *   [Cross-Chain Payments](#cross-chain-payments)
    *   [Simulation](#simulation)
8.  [**The Guard System (Safety Kernel)**](#-the-guard-system-safety-kernel)
    *   [Budget Guard](#budget-guard)
    *   [Rate Limit Guard](#rate-limit-guard)
    *   [Single Transaction Guard](#single-transaction-guard)
    *   [Recipient Guard](#recipient-guard)
    *   [Confirm Guard (Human-in-the-Loop)](#confirm-guard)
    *   [Atomic Guarantees](#atomic-guarantees)
9.  [**Payment Intents (Auth/Capture)**](#-payment-intents-authcapture)
10. [**Batch Payments**](#-batch-payments)
11. [**Webhooks & Events**](#-webhooks--events)
12. [**Observability & Ledger**](#-observability--ledger)
13. [**Security & Best Practices**](#-security--best-practices)
14. [**Error Handling**](#-error-handling)
15. [**Contributing**](#-contributing)

---

## 🚀 Why OmniAgentPay?

### The Problem: AI Agents + Crypto = Risk
When you give an AI agent a private key, you create a risk vector. Hallucinations, prompt injection, or logic bugs can drain a treasury in seconds.

### The Solution: Programmable Safety
OmniAgentPay wraps the wallet in a **Safety Kernel**. Before any transaction is signed:
1.  **Guards** check the request against strict policies (Budget, Velocity, Whitelists).
2.  **Simulation** predicts the outcome and fees.
3.  **Routing** selects the optimal path (Transfer, x402, CCTP).

### Key Features
*   **Zero Config**: Just provide your Circle API key. We handle Entity Secrets, Encryption, and stored credentials managed automatically.
*   **Agent-Native**: Simple `client.pay()` interface that "just works". No dealing with ABIs, gas limits, or nonces.
*   **Safety First**: Embedded Guard System prevents runaway spending with atomic guarantees.
*   **Unified Routing**: One method handles USDC transfers, x402 invoices, and Cross-Chain payments transparently.
*   **Payment Intents**: Support for "Authorize-then-Capture" workflows, essential for multi-agent coordination or DAO approval steps.

---

## 💡 What Can You Build?

OmniAgentPay is the engine for the **Agentic Economy**. Here are the winning use cases:

### 1. Trustless Autonomous Agents (Hackathon Track 🤖)
Build agents that manage their own treasury without human oversight.
*   **How**: Use `BudgetGuard` and `RateLimitGuard` to mathematically guarantee the agent cannot burn its runway.
*   **Example**: An SEO Agent that autonomously buys backlinks and ads, strictly capped at $50/day.
*   **Code**: [View Gemini Agent Example](examples/gemini_agent.py)

### 2. Multi-Agent Commerce Systems
Enable agents to trade services with each other.
*   **How**: Use `PaymentIntents` for "Authorize-then-Capture" flows. Agent A orders data, Agent B delivers, Agent A confirms payment.
*   **Example**: A Supply Chain Swarm where a 'Buyer Agent' approves po's from 'Supplier Agents' autonomously.

### 3. Usage-Based API Services (Hackathon Track 🪙)
Monetize your AI tools per-token or per-request.
*   **How**: Use the `x402` Adapter.
*   **Example**: An LLM wrapper that charges 0.01 USDC per prompt via HTTP 402 headers.
*   **Code**: [View x402 Server Example](examples/x402_server.py)

### 4. Cross-Chain Arbitrage Bots
Agents that move capital instantly between chains.
*   **How**: Use the `GatewayAdapter` (Circle CCTP).
*   **Example**: A Liquidity Agent that rebalances USDC from Ethereum to Base when yields change.

---

## 🏗 Core Architecture

OmniAgentPay follows a **Hub-and-Spoke** architecture tailored for multi-agent systems.

```
[ AI Agent Code ]
       |
       v
[ OmniAgentPay Client ]  <--- (Configuration & Secrets)
       |
       +--- [ Guard Kernel ] (Atomic Policy Enforcement)
       |          |
       |          +--- [ Storage Backend ] (Redis/Memory)
       |
       +--- [ Payment Router ]
       |          |
       |          +--- [ Transfer Adapter ] (Same-Chain)
       |          +--- [ X402 Adapter ]     (Invoices)
       |          +--- [ Gateway Adapter ]  (Cross-Chain)
       |
       v
[ Circle Web3 Services ] ---> [ Blockchain Networks ]
```

---

## 📦 Installation

Install via pip:

```bash
pip install omniagentpay
```

Or using `uv` (recommended for speed):

```bash
uv add omniagentpay
```

**Requirements:**
*   Python 3.10+
*   A Circle Web3 Services API Key ([Get one here](https://console.circle.com))

---

## ⚡ Quick Start

The "Zero to Hero" path to getting your agent paying securely.

### 1. Initialize the Client
The client automatically generates an Entity Secret if one is not provided, making setup frictionless.

```python
import logging
from omniagentpay import OmniAgentPay, Network

# Reads CIRCLE_API_KEY from environment variables automatically
client = OmniAgentPay(
    network=Network.ARC_TESTNET,  # Defaults to ARC_TESTNET
    log_level=logging.INFO        # Use DEBUG for full request tracing
)
```

### 2. Create an Identity
Agents need wallets. In OmniAgentPay, we organize wallets into **Wallet Sets**.

```python
# Create a wallet specifically for "Agent-007"
# This checks if a set exists for this agent, and creates one if not.
wallet_set, wallet = await client.create_agent_wallet(agent_name="Agent-007")

print(f"Agent Wallet Address: {wallet.address}")
print(f"Wallet ID: {wallet.id}")
```

### 3. Add Safety Guards
**CRITICAL**: Never deploy an unguarded agent.

```python
# 1. Budget Guard: Max $100 per day, resetting at midnight UTC
await client.add_budget_guard(
    wallet.id,
    daily_limit="100.00",
    name="safety_budget"
)

# 2. Recipient Guard: Whitelist approved vendors only
await client.add_recipient_guard(
    wallet.id,
    mode="whitelist",
    domains=["api.openai.com", "aws.amazon.com", "anthropic.com"]
)
```

### 4. Execute Payment
The agent simply decides *who* to pay and *how much*.

```python
try:
    result = await client.pay(
        wallet_id=wallet.id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0", 
        amount="10.50",
        purpose="Server costs for Jan 2025"
    )

    if result.success:
        print(f"Payment Confirmed! Tx: {result.blockchain_tx}")
    else:
        print(f"Payment Failed: {result.error}")

except Exception as e:
    print(f"Critical Failure: {e}")
```

---

## ⚙ Configuration Reference

OmniAgentPay can be configured via Environment Variables or direct Constructor Arguments. **Environment Variables are recommended** for security.

### Environment Variables

| Variable | Required | Description | Default |
| :--- | :--- | :--- | :--- |
| `CIRCLE_API_KEY` | **Yes** | Your API Key from Circle Console. | - |
| `ENTITY_SECRET` | No | 32-byte hex secret for transaction signing. | **Auto-Generated** if missing |
| `OMNIAGENT_STORAGE_BACKEND` | No | Persistence layer: `memory` or `redis`. | `memory` |
| `REDIS_URL` | No | Connection string if `redis` backend is used. | `redis://localhost:6379/0` |
| `OMNIAGENT_LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`. | `INFO` |
| `OMNIAGENT_ENV` | No | `production` or `development`. | `development` |

### Constructor Arguments (`OmniAgentPay`)

```python
client = OmniAgentPay(
    circle_api_key="...",       # Optional if Env Var set
    entity_secret="...",        # Optional if Env Var set
    network=Network.ARC_TESTNET, # Target Blockchain Network
    log_level=logging.DEBUG     # Override logging
)
```

---

## 🔧 Wallet Management

OmniAgentPay abstracts the concept of "Wallet Sets" to help you organize agent swarms.

### Agent Wallets
Best for autonomous agents. Creates a Wallet Set named `agent-{name}` and a wallet within it.

```python
wallet_set, wallet = await client.create_agent_wallet(
    agent_name="ShoppingBot-1",
    blockchain=Network.BASE     # Optional: Specify chain
)
```

### User Wallets
Best for end-users of your application. Creates a Wallet Set with `custody_type=ENDUSER` (if supported).

```python
wallet_set, wallet = await client.create_user_wallet(
    user_id="user_88123",
    blockchain=Network.SOLANA   # Optional
)
```

### Wallet Sets
A **Wallet Set** is a container for multiple wallets. Guards can be applied to an entire set.

```python
# Create a set for a team of agents
marketing_swarm = await client.create_wallet_set(name="marketing-swarm")

# Create wallets in that set
agent_a = await client.create_wallet(
    wallet_set_id=marketing_swarm.id, 
    blockchain=Network.ETH
)
agent_b = await client.create_wallet(
    wallet_set_id=marketing_swarm.id, 
    blockchain=Network.BASE
)
```

---

## 💳 The Payment API

The `pay()` method is the heart of the SDK. It uses an intelligent routing engine to determine the best way to execute a transaction.

### Understanding `pay()`

```python
async def pay(
    self,
    # --- REQUIRED ---
    wallet_id: str,                      # Source of funds
    recipient: str,                      # Destination (Address, URL, or Domain)
    amount: Decimal | str | float,       # Amount in USDC
    
    # --- ROUTING & TOPOLOGY ---
    destination_chain: Network = None,   # Target network (for Cross-Chain)
    
    # --- CONTEXT ---
    purpose: str = None,                 # Audit trail description
    metadata: dict = None,               # Custom JSON data
    idempotency_key: str = None,         # Prevent duplicates
    
    # --- EXECUTION CONTROL ---
    fee_level: FeeLevel = MEDIUM,        # LOW, MEDIUM, HIGH
    wait_for_completion: bool = False,   # If True, blocks until on-chain confirmation
    timeout_seconds: float = 30.0,       # Max wait time if blocking
    skip_guards: bool = False,           # DANGEROUS: Bypass safety checks
) -> PaymentResult
```

### Automatic Routing

The `PaymentRouter` inspects the `recipient` format to choose an adapter:

1.  **Transfer Adapter**: If `recipient` is a valid blockchain address (0x... or Base58).
    *   *Action*: Direct on-chain USDC transfer.
2.  **x402 Adapter**: If `recipient` is an HTTP(S) URL.
    *   *Action*: Performs the x402 handshake (Ask for price -> Pay -> Get Token).
3.  **Gateway Adapter**: If `destination_chain` differs from the wallet's chain.
    *   *Action*: Uses Circle CCTP (Cross-Chain Transfer Protocol) to burn/mint USDC across chains.

### Cross-Chain Payments

To move USDC from Ethereum to Base, simply specify the destination chain.

```python
result = await client.pay(
    wallet_id=eth_wallet.id,
    recipient="0xBaseAddress...",
    amount="50.00",
    destination_chain=Network.BASE  # This triggers the Gateway Adapter
)
```

### Simulation
You can check if a payment *would* succeed without spending money. This runs the full logic stack: Guards -> Routing -> Fee Estimation.

```python
sim = await client.simulate(
    wallet_id=wallet.id,
    recipient="0x...",
    amount="1000000.00"  # Huge amount
)

if not sim.would_succeed:
    print(f"Simulation failed: {sim.reason}")
    # Output: "Simulation failed: Would be blocked by guard: Budget limit exceeded"
```

---

## 🛡 The Guard System (Safety Kernel)

The **Guard System** is what makes OmniAgentPay unique. It is a programmable firewall for your agent's money.

Guards are checked **Atomically**. This means checking a limit and updating the usage happens in a single, locked operation (using Redis Lua scripts or atomic memory locks), preventing race conditions even with high-concurrency agents.

### Budget Guard
Enforces spending limits over time windows.

**Parameters:**
*   `daily_limit`: Max spend per 24h rolling window.
*   `hourly_limit`: Max spend per 1h rolling window.
*   `total_limit`: Lifetime spend limit.

```python
await client.add_budget_guard(
    wallet.id,
    daily_limit="50.00",   # $50 / day
    hourly_limit="10.00",  # $10 / hour (velocity check)
    total_limit="1000.00"  # Lifespan budget
)
```

### Rate Limit Guard
Protects against "looping" bugs where an agent sends thousands of micro-transactions.

**Parameters:**
*   `max_per_minute`: Tx/min.
*   `max_per_hour`: Tx/hour.

```python
await client.add_rate_limit_guard(
    wallet.id,
    max_per_minute=5,      # Stop infinite loops
    max_per_hour=20
)
```

### Single Transaction Guard
Prevents "fat finger" errors or massive hallucinations.

**Parameters:**
*   `max_amount`: Hard cap on any single tx.
*   `min_amount`: Dust protection.

```python
await client.add_single_tx_guard(
    wallet.id,
    max_amount="100.00",    # Allow nothing over $100
    min_amount="0.50"       # Prevent dust spam
)
```

### Recipient Guard
Restricts **WHO** the agent can pay. Essential for closed-loop systems.

**Parameters:**
*   `mode`: "whitelist" (allow only listed) or "blacklist" (block listed).
*   `addresses`: List of exact blockchain addresses.
*   `domains`: List of DNS domains (for x402 payments).
*   `patterns`: List of Regex patterns.

```python
await client.add_recipient_guard(
    wallet.id,
    mode="whitelist",
    addresses=["0xEmployee1...", "0xEmployee2..."],
    domains=["internal-service.corp"]
)
```

### Confirm Guard
Implements "Human-in-the-Loop". Payments over a threshold are **PAUSED** until approved via webhook/API.

**Parameters:**
*   `threshold`: Amount above which confirmation is needed.
*   `callback`: Async function (for local testing) or Webhook URL.

```python
await client.add_confirm_guard(
    wallet.id,
    threshold="500.00"  # Payments > $500 require approval
)
```

### Atomic Guarantees
OmniAgentPay guarantees that **Checks** and **Effects** are atomic.
*   *Scenario*: 10 parallel requests of $10 arrive against a $50 budget.
*   *Result*: Exactly 5 succeed. 5 fail with `BudgetExceeded`.
*   *Mechanism*: Reservation tokens are issued during the check phase and committed only upon success. Failed transactions release the reservation.

---

## 🧠 Payment Intents (Auth/Capture)

Payment Intents separate "Authorization" (Reservation) from "Capture" (Execution). This is crucial for:
1.  **Multi-Agent Consensus**: Agent A proposes, Agent B reviews, Agent C executes.
2.  **Human Review**: Agent proposes a $5000 purchase, Human approves it later.
3.  **Future Scheduling**: Plan now, execute later.

### 1. Create Intent
Logic runs, Guards check, Budget is **Reserved**, but no blockchain tx is sent.

```python
intent = await client.create_payment_intent(
    wallet_id=wallet.id,
    recipient="0xSupplier...",
    amount="2000.00",
    purpose="Q1 Supply Restock"
)

print(f"Intent ID: {intent.id} - Status: {intent.status}")
# Status: requires_confirmation
```

### 2. Confirm Intent
Executes the pre-authorized plan.

```python
result = await client.confirm_payment_intent(intent.id)
# Status: succeeded
```

### 3. Cancel Intent
Releases the reserved budget back to the pool.

```python
await client.cancel_payment_intent(intent.id)
# Status: canceled
```

---

## 🏎 Batch Payments

Sending funds to 100 workers? Use `batch_pay`. It manages concurrency and result aggregation.

```python
from omniagentpay import PaymentRequest

# Build the manifest
batch = [
    PaymentRequest(wallet_id=w.id, recipient="0xA...", amount=10),
    PaymentRequest(wallet_id=w.id, recipient="0xB...", amount=15),
    PaymentRequest(wallet_id=w.id, recipient="0xC...", amount=20),
    # ... 100 more
]

# Execute with controlled concurrency
batch_result = await client.batch_pay(batch, concurrency=10)

print(f"Success: {batch_result.success_count}")
print(f"Failed: {batch_result.failed_count}")

# Inspect failures
for res in batch_result.results:
    if not res.success:
        print(f"Failed to pay {res.recipient}: {res.error}")
```

---

## 🎣 Webhooks & Events

OmniAgentPay includes a **verifiable webhook parser**. If you use Circle's Notification Service, you can forward events to your agent securely.

### Supported Events
*   `payment.received`: Funds landed in wallet.
*   `payment.sent`: Transaction confirmed.
*   `transaction.failed`: Reverted on-chain.

### Verifying Signatures
We implement Ed25519 signature verification compatible with Circle's standard.

```python
# In your FastAPI / Flask / Django handler
@app.post("/webhooks/circle")
async def handle_webhook(request: Request):
    # 1. Get raw bytes and headers
    body = await request.body()
    headers = request.headers
    
    try:
        # 2. Verify & Parse (Throws on invalid signature)
        event = client.webhooks.handle(body, headers)
        
        # 3. Handle Business Logic
        if event.type == "payment.received":
             print(f"Received {event.data.amount} USDC!")
             
    except Exception as e:
        return Response(status_code=400)
```

---

## 📊 Observability & Ledger

Every transaction—whether successful, failed, or blocked by a guard—is recorded in the **OmniAgentPay Ledger**.

### The Ledger Schema
The local ledger (Memory or Redis) acts as the "source of truth" for the agent's history, separate from the blockchain.

```json
{
  "id": "entry_123...",
  "status": "completed",
  "amount": "10.00",
  "recipient": "0x...",
  "timestamp": "2025-01-14T10:00:00Z",
  "blockchain_tx": "0xabc...",
  "metadata": {
    "purpose": "Coffee",
    "provider_id": "cctp_uuid_..."
  }
}
```

### Accessing History

```python
# Get full history for a wallet
history = await client.ledger.get_history(wallet_id=wallet.id)

# Sync a specific entry with the Blockchain (Update status)
updated_entry = await client.sync_transaction(entry_id="entry_123")
```

---

## 🔐 Security & Best Practices

1.  **Environment Variables**: Never hardcode API keys or Entity Secrets. Use `.env`.
2.  **Least Privilege**: Give agents only the budget they need for the task.
3.  **Strict Recipient Guards**: If an agent only buys valid server time, whitelist AWS/GCP addresses.
4.  **Use Intents for High Value**: Requiring a second step for >$1000 eliminates 99% of "catastrophic" AI errors.
5.  **Monitor Logs**: Run with `log_level=logging.WARNING` in prod, but check alerts on `BLOCKED` payment status.

---

## ⚠️ Error Handling

OmniAgentPay uses a typed exception hierarchy rooted in `OmniAgentPayError`.

*   `OmniAgentPayError` (Base)
    *   `ConfigurationError`: Missing keys, bad config.
    *   `WalletError`: Wallet not found, invalid state.
    *   `PaymentError` transformation logic failure.
        *   `InsufficientBalanceError`: Not enough USDC.
        *   `GuardError`: Blocked by policy.
        *   `TransactionTimeoutError`: Took too long.
    *   `NetworkError`: API unreachable.

**Retry Strategy:**
*   `Client` automatically retries `NetworkError` and `5xx` responses.
*   **DO NOT** retry `GuardError` or `InsufficientBalanceError` without human intervention.

---

## 🤝 Contributing

We welcome contributions from the community!

1.  **Fork** the repository.
2.  **Install Dev Deps**: `pip install -e ".[dev]"`
3.  **Run Tests**: `pytest`
4.  **Submit PR**: Describe your changes and add tests.

License: **MIT**