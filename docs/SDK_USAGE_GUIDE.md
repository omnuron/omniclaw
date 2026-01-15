# OmniAgentPay SDK - Complete Usage Guide

**OmniAgentPay** is the payment infrastructure layer for autonomous AI agents. It abstracts blockchain complexity into a unified interface while enforcing strict safety boundaries.

**Key Features:**
*   **Zero Config**: Just provide your Circle API key. Entity Secret is auto-generated.
*   **Agent-Native**: Agents call `pay()`. No private key management needed.
*   **Safety Kernel**: Guards prevent runaway spending with atomic guarantees.
*   **Unified Routing**: One method handles transfers, x402 invoices, and cross-chain.
*   **Full Observability**: DEBUG logs expose every internal decision.

---

## 🚀 1. Getting Started

### Initialize the Client

```python
import logging
from omniagentpay import OmniAgentPay, Network

# Just provide your API key - Entity Secret is auto-generated if missing!
client = OmniAgentPay(
    circle_api_key="YOUR_CIRCLE_API_KEY",  # Or set CIRCLE_API_KEY env var
    network=Network.ARC_TESTNET,            # Recommended: Arc Testnet for hackathon
    log_level=logging.DEBUG                 # Enable full traceability
)

# That's it! Ready to use.
```

### Using Environment Variables (Recommended)

```bash
# .env file
CIRCLE_API_KEY=sk_your_api_key_here
# ENTITY_SECRET is auto-generated if not set!
```

```python
# Client reads from environment automatically
client = OmniAgentPay()  # Zero config!
```

### Async Context Manager

```python
async with OmniAgentPay() as client:
    result = await client.pay(...)
    # Resources cleaned up automatically
```

---

## 🔧 2. Wallet Management

### Create Agent Wallets

```python
# Create/Retrieve identity for "Agent-007"
wallet_set, wallet = client.wallet.create_agent_wallet(agent_name="Agent-007")

print(f"Agent ID: {wallet_set.id}")
print(f"Wallet Address: {wallet.address}")
```

### Create User Wallets

```python
wallet_set, wallet = client.wallet.create_user_wallet(user_id="user_12345")
```

### Other Operations

```python
# Create wallet set and wallets manually
ws = await client.create_wallet_set(name="my-agent-swarm")
w1 = await client.create_wallet(wallet_set_id=ws.id, blockchain=Network.ETH)
w2 = await client.create_wallet(wallet_set_id=ws.id, blockchain=Network.ARC_TESTNET)

# List & Retrieve
all_wallets = await client.list_wallets(wallet_set_id=ws.id)
my_wallet = await client.get_wallet(w1.id)

# Check Balance
balance = await client.get_balance(wallet.id)
print(f"Balance: {balance} USDC")
```

---

## ⚡ 3. The `pay()` Method

### Full Signature

```python
result = await client.pay(
    # === REQUIRED ===
    wallet_id: str,                      # Source wallet ID
    recipient: str,                      # Address OR URL (for x402)
    amount: Decimal | int | float | str, # Amount in USDC
    
    # === ROUTING ===
    destination_chain: Network = None,   # Target chain for cross-chain
    
    # === GUARDS & CONTEXT ===
    wallet_set_id: str = None,           # For wallet-set-level guards
    purpose: str = None,                 # Human-readable purpose (audit)
    skip_guards: bool = False,           # Bypass guards (DANGEROUS!)
    
    # === TRANSACTION CONTROL ===
    idempotency_key: str = None,         # Prevent duplicate payments
    fee_level: FeeLevel = MEDIUM,        # LOW, MEDIUM, HIGH gas fees
    
    # === CUSTOM DATA ===
    metadata: dict = None,               # Custom data stored with payment
    
    # === SYNCHRONOUS MODE ===
    wait_for_completion: bool = False,   # Block until confirmed
    timeout_seconds: float = 30.0,       # Max wait time
)
```

### Automatic Routing

| Recipient Format | Protocol | Description |
| :--- | :--- | :--- |
| `0x742d...` | **Transfer** | Direct USDC transfer |
| `https://api.com` | **x402** | Negotiates 402 invoice, pays, retries |
| Uses `destination_chain` | **Gateway** | Cross-chain via CCTP |

### Examples

**Simple Transfer:**
```python
result = await client.pay(
    wallet_id=wallet.id,
    recipient="0xVendorAddress...",
    amount=25.50,
    purpose="Monthly subscription"
)
```

**Cross-Chain Transfer:**
```python
result = await client.pay(
    wallet_id=wallet.id,
    recipient="0xRecipientOnBase...",
    amount=10.00,
    destination_chain=Network.BASE  # Explicit target chain (e.g. cross-chain to Base)
)
```

**Synchronous with Metadata:**
```python
result = await client.pay(
    wallet_id=wallet.id,
    recipient="0xVendor...",
    amount=100.00,
    metadata={"invoice_id": "INV-2026-001"},
    wait_for_completion=True,
    timeout_seconds=60.0
)

if result.success:
    print(f"Confirmed! Tx: {result.blockchain_tx}")
```

---

## 🛡️ 4. Guard System

Guards enforce rules **atomically before any transaction is signed**.

### Budget Guard

```python
await client.add_budget_guard(
    wallet.id,
    daily_limit="100.00",
    hourly_limit="20.00",
    total_limit="1000.00",
    name="budget_limit"
)
```

### Rate Limit Guard

```python
await client.add_rate_limit_guard(
    wallet.id,
    max_per_minute=5,
    max_per_hour=100,
    name="velocity_check"
)
```

### Single Transaction Guard

```python
await client.add_single_tx_guard(
    wallet.id,
    max_amount="50.00",
    min_amount="0.01"
)
```

### Recipient Guard

**Whitelist:**
```python
await client.add_recipient_guard(
    wallet.id,
    mode="whitelist",
    addresses=["0xTrusted...", "0xPartner..."],
    domains=["api.openai.com", "aws.amazon.com"],
    patterns=[r"^0x[a-fA-F0-9]{40}$"]
)
```

**Blacklist:**
```python
await client.add_recipient_guard(
    wallet.id,
    mode="blacklist",
    domains=["malicious-site.com"],
    patterns=[r".*casino.*"]
)
```

---

## 🏢 5. Wallet-Set Guards

Apply guards to **ALL wallets** in a set:

```python
await client.add_budget_guard_for_set(wallet_set.id, daily_limit="1000.00")
await client.add_rate_limit_guard_for_set(wallet_set.id, max_per_hour=100)
await client.add_recipient_guard_for_set(wallet_set.id, mode="whitelist", addresses=[...])
```

### List Guards

```python
wallet_guards = await client.list_guards(wallet.id)
set_guards = await client.list_guards_for_set(wallet_set.id)
```

---

## 🧠 6. Payment Intents (Authorize → Capture)

For high-value transactions requiring approval:

```python
# 1. Create Intent (no funds move)
intent = await client.create_payment_intent(
    wallet_id=wallet.id,
    recipient="0x...",
    amount=1000.00,
    purpose="Large purchase"
)

# 2. After human approval...
result = await client.confirm_payment_intent(intent.id)

# 3. Or cancel
await client.cancel_payment_intent(intent.id)
```

---

## 🚀 7. Batch Payments

```python
from omniagentpay import PaymentRequest

requests = [
    PaymentRequest(wallet_id=w1.id, recipient="0xA...", amount=10),
    PaymentRequest(wallet_id=w1.id, recipient="0xB...", amount=20),
    PaymentRequest(wallet_id=w2.id, recipient="0xC...", amount=15, destination_chain=Network.ARC_TESTNET),
]

batch_result = await client.batch_pay(requests, concurrency=5)
print(f"Success: {batch_result.success_count}/{batch_result.total_count}")
```

---

## 🔍 8. Observability

### Logging

```python
client = OmniAgentPay(log_level=logging.DEBUG)  # See everything
client = OmniAgentPay(log_level=logging.INFO)   # High-level flow
client = OmniAgentPay(log_level=logging.WARNING) # Only issues
```

### Ledger

```python
history = await client.ledger.get_history(wallet.id)
updated = await client.sync_transaction(entry_id)
```

### Webhooks

```python
@app.post("/webhooks/circle")
async def handle(request: Request):
    event = client.webhooks.handle(await request.body(), request.headers)
    if event.type == NotificationType.PAYMENT_COMPLETED:
        print(f"Payment confirmed: {event.data.get('id')}")
    return {"status": "ok"}
```

---

## 🎯 Best Practices

1. **Always Guard**: Never deploy without a `BudgetGuard`
2. **Use Intents**: For amounts > $100, use human-in-the-loop
3. **Enable DEBUG**: See the matrix in development
4. **Use `destination_chain`**: Be explicit for cross-chain
5. **Store in `metadata`**: Link to your external systems

---

**Go build the Agent Economy!** 🚀
