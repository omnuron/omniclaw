# OmniClaw: The Payment Infrastructure Layer for AI Agents

> **"Agents think. We handle the money."**
> 
> *The Stripe for AI Agents - Infrastructure that powers the entire agent economy.*

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Market Context: The Protocol Landscape](#market-context)
3. [Our Position: The Execution Layer](#our-position)
4. [Core Architecture](#core-architecture)
5. [Features That Create Magic](#features-that-create-magic)
6. [Phase 1: Hackathon Scope](#phase-1-hackathon)
7. [Future Roadmap](#future-roadmap)
8. [Why We Win](#why-we-win)

---

## Executive Summary

**OmniClaw** is the payment *execution* infrastructure for AI agents. While protocols like x402 define payment standards and Google's AP2 defines authorization frameworks, OmniClaw is the SDK that makes payments actually happen.

**What we are:**
- The Circle/USDC integration layer
- The x402 protocol executor
- The cross-chain payment router
- The spending control system
- The transaction ledger

**What we are NOT:**
- A payment protocol (we implement x402, support AP2)
- An agent framework (we integrate with OmniCoreAgent, LangChain, etc.)
- An application (we're infrastructure for application builders)

---

## Market Context: The Protocol Landscape

```
┌────────────────────────────────────────────────────────────────────────────┐
│                      AI AGENT PAYMENT STACK                                │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ LAYER 4: AUTHORIZATION & TRUST                                       │ │
│  │                                                                       │ │
│  │ Google AP2 (Agent Payments Protocol)                                  │ │
│  │ ├── Mandates (cryptographic authorization)                           │ │
│  │ ├── Real-time approvals                                              │ │
│  │ ├── Delegated transactions                                           │ │
│  │ └── Fraud/accountability framework                                   │ │
│  │                                                                       │ │
│  │ Partners: Coinbase, Mastercard, PayPal, Amex, Salesforce             │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                    │                                       │
│                                    ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ LAYER 3: COMMUNICATION                                               │ │
│  │                                                                       │ │
│  │ Google A2A (Agent-to-Agent Protocol)                                 │ │
│  │ ├── Agent discovery (Agent Cards)                                    │ │
│  │ ├── Task orchestration                                               │ │
│  │ └── Cross-platform messaging                                         │ │
│  │                                                                       │ │
│  │ Anthropic MCP (Model Context Protocol)                                │ │
│  │ ├── Tool access                                                      │ │
│  │ └── Context management                                               │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                    │                                       │
│                                    ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ LAYER 2: PAYMENT STANDARDS                                           │ │
│  │                                                                       │ │
│  │ x402 (HTTP Payment Standard)                                          │ │
│  │ ├── 402 Payment Required responses                                   │ │
│  │ ├── Payment header construction                                      │ │
│  │ └── Facilitator verification/settlement                              │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                    │                                       │
│                                    ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ LAYER 1: EXECUTION INFRASTRUCTURE  ⭐ THIS IS OMNICLAW           │ │
│  │                                                                       │ │
│  │ OmniClaw                                                          │ │
│  │ ├── Wallet management (Circle Wallets)                               │ │
│  │ ├── Payment execution (x402, transfers)                              │ │
│  │ ├── Cross-chain routing (Gateway, CCTP)                              │ │
│  │ ├── Spending controls (guards)                                       │ │
│  │ ├── Transaction ledger                                               │ │
│  │ └── SDK for agent frameworks                                         │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                    │                                       │
│                                    ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ LAYER 0: BLOCKCHAIN & SETTLEMENT                                     │ │
│  │                                                                       │ │
│  │ Arc Blockchain, Circle APIs, USDC, Ethereum, Base, etc.              │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

### How We Relate to Google's Protocols

| Protocol | Purpose | Our Relationship |
|----------|---------|------------------|
| **A2A** | Agent-to-agent communication | We can receive payment requests via A2A tasks |
| **AP2** | Payment authorization (Mandates) | We can validate AP2 Mandates before execution |
| **MCP** | Tool access for agents | We provide MCP-compatible payment tools |
| **x402** | HTTP payment standard | **We implement this** - execute x402 flows |

**Key Insight**: Google's AP2 focuses on *authorization* (who can pay, under what conditions). We focus on *execution* (actually moving the money using USDC/Circle). 

**We complement, not compete.**

---

## Our Position: The Execution Layer

```
Agent says: "Pay $50 to api.example.com"
                    │
                    ▼
            ┌───────────────┐
            │  OmniClaw │
            │               │
            │ 1. Validate   │ ← Could check AP2 Mandate here
            │ 2. Check guards│
            │ 3. Route      │
            │ 4. Execute    │ ← x402 flow, Circle transfer
            │ 5. Record     │
            │ 6. Return     │
            └───────────────┘
                    │
                    ▼
        Payment complete, agent continues
```

---

## Core Architecture

### The Agent Economic Lifecycle

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    THE AGENT ECONOMIC LIFECYCLE                            │
│                                                                            │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│   │ IDENTITY │───►│  TRUST   │───►│ TRANSACT │───►│ SETTLE   │            │
│   │          │    │          │    │          │    │          │            │
│   │ Who is   │    │ Can they │    │ Execute  │    │ Finalize │            │
│   │ this     │    │ be       │    │ payment  │    │ on-chain │            │
│   │ agent?   │    │ trusted? │    │          │    │          │            │
│   └──────────┘    └──────────┘    └──────────┘    └──────────┘            │
│         │               │               │               │                  │
│         ▼               ▼               ▼               ▼                  │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│   │ TRACK    │◄───│ ANALYZE  │◄───│ OPTIMIZE │◄───│ REPORT   │            │
│   │          │    │          │    │          │    │          │            │
│   │ History  │    │ Patterns │    │ Costs    │    │ Audit    │            │
│   │ & state  │    │ & fraud  │    │ & routes │    │ & comply │            │
│   └──────────┘    └──────────┘    └──────────┘    └──────────┘            │
└────────────────────────────────────────────────────────────────────────────┘
```

### System Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            OMNICLAW                                     │
│                    "The Economic OS for AI Agents"                          │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        CLIENT SDK                                    │   │
│  │   Python • TypeScript • Go • Rust • MCP Server                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐ │
│  │                         CORE SERVICES                                 │ │
│  │                                                                       │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │ │
│  │  │ Identity │ │ Wallet   │ │ Payment  │ │ Guard    │ │ Ledger   │   │ │
│  │  │ Service  │ │ Service  │ │ Router   │ │ Chain    │ │ Service  │   │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │ │
│  │                                                                       │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │ │
│  │  │ Intent   │ │ Stream   │ │ A2A      │ │Analytics │ │ Webhook  │   │ │
│  │  │ Service  │ │ Service  │ │ Service  │ │ Engine   │ │ Dispatch │   │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐ │
│  │                      PROTOCOL ADAPTERS                                │ │
│  │                                                                       │ │
│  │   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │ │
│  │   │  x402  │ │Transfer│ │Gateway │ │  CCTP  │ │ Escrow │            │ │
│  │   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘            │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐ │
│  │                    INFRASTRUCTURE                                     │ │
│  │                                                                       │ │
│  │   Circle APIs • Arc Blockchain • x402 Facilitator • CCTP            │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Features That Create Magic

### 1. 🆔 Agent Identity & Reputation

*The problem*: How do you trust an unknown agent? How do agents trust each other?

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AGENT IDENTITY SYSTEM                           │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  Agent: sales_analyst_007                                   │   │
│   │                                                             │   │
│   │  Wallet: 0x742d35Cc...                                      │   │
│   │  Created: 2026-01-10                                        │   │
│   │  Operator: TechCorp Inc.                                    │   │
│   │                                                             │   │
│   │  REPUTATION SCORE: 94/100 ██████████████████░░              │   │
│   │                                                             │   │
│   │  Stats:                                                     │   │
│   │  ├── Transactions: 1,247                                    │   │
│   │  ├── Total Volume: $45,230.00                               │   │
│   │  ├── Failed Payments: 2 (0.16%)                             │   │
│   │  ├── Disputes: 0                                            │   │
│   │  └── Avg Payment Size: $36.27                               │   │
│   │                                                             │   │
│   │  Verified Capabilities:                                     │   │
│   │  ├── ✓ Data Analysis                                        │   │
│   │  ├── ✓ Web Search                                           │   │
│   │  └── ✓ Payment Authorized                                   │   │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# API
identity = client.identity.create(
    agent_name="sales_analyst",
    operator_id="techcorp",
    capabilities=["data_analysis", "web_search", "payment"]
)

# Check another agent before transacting
reputation = client.identity.reputation("agent_xyz")
if reputation.score > 80:
    proceed_with_transaction()
```

---

### 2. 🤝 Agent-to-Agent Payments (A2A)

*The future*: Agents hiring other agents, paying for their services with escrow protection.

```
AGENT A (Research)              OMNICLAW              AGENT B (Analysis)
      │                              │                           │
      │  "I need sentiment analysis" │                           │
      ├─────────────────────────────►│                           │
      │                              │  "Agent A wants service"  │
      │                              ├──────────────────────────►│
      │                              │  "I'll do it for $5"      │
      │                              │◄──────────────────────────┤
      │  "Agree to $5"               │                           │
      ├─────────────────────────────►│                           │
      │                         ┌────┴────┐                      │
      │                         │ ESCROW  │                      │
      │                         │ $5 USDC │                      │
      │                         └────┬────┘                      │
      │                              │  "Funds escrowed, proceed"│
      │                              ├──────────────────────────►│
      │                              │  (Agent B does work)      │
      │                              │  "Work complete"          │
      │                              │◄──────────────────────────┤
      │  "Release payment"           │                           │
      ├─────────────────────────────►│                           │
      │                         ┌────┴────┐                      │
      │                         │ RELEASE │                      │
      │                         │ → B     │                      │
      │                         └─────────┘                      │
```

```python
# Agent A initiates
contract = client.a2a.request_service(
    from_wallet=wallet_a,
    to_agent="agent_b_id",
    service="sentiment_analysis",
    max_price="10.00",
    requirements={"data_size": "1MB", "turnaround": "5min"}
)

# Agent B accepts
client.a2a.accept(contract.id, price="5.00")

# After work complete, Agent A releases
client.a2a.release(contract.id, rating=5)
```

---

### 3. 📜 Payment Intents (2-Phase Commit)

*Like Stripe*: Separate intent from execution for complex approval flows.

```python
# Phase 1: Create intent (can be approved/modified/cancelled)
intent = client.intent.create(
    wallet_id=wallet,
    recipient="https://api.expensive-model.com",
    amount="50.00",
    purpose="Run large language model inference",
    expires_in=300  # 5 minutes
)

print(intent.status)  # "pending_confirmation"

# Phase 2: Confirm when ready
result = client.intent.confirm(intent.id)

# Or cancel
client.intent.cancel(intent.id, reason="User declined")
```

---

### 4. 💧 Streaming Payments (Pay-As-You-Go)

*Real-time billing*: For compute, tokens, API calls that bill continuously.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      STREAMING PAYMENT                              │
│                                                                     │
│   Agent using GPU compute service:                                  │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  Stream: strm_abc123                                        │   │
│   │  Started: 2026-01-10 20:00:00                               │   │
│   │  Rate: $0.001 per second ($3.60/hour)                       │   │
│   │                                                             │   │
│   │  Time elapsed: 00:15:32                                     │   │
│   │  Current charge: $0.932                                     │   │
│   │                                                             │   │
│   │  ████████████████░░░░░░░░░░░░░░ 52% of budget               │   │
│   │                                                             │   │
│   │  Auto-stops at: $2.00 (budget limit)                        │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│   • Payment settles every 60 seconds                               │
│   • Agent can stop stream anytime                                  │
│   • Auto-stops if budget exceeded                                  │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# Start streaming payment
stream = client.stream.start(
    wallet_id=wallet,
    recipient="compute.service.com",
    rate_per_second="0.001",
    max_total="10.00"
)

# Do work while stream is active
result = compute_service.run_job()

# Stop stream
final = client.stream.stop(stream.id)
print(f"Total charged: ${final.total_amount}")
```

---

### 5. 🏦 Multi-Sig Agent Treasury

*Enterprise use*: Multiple agents or humans must approve large payments.

```python
# Create multi-sig wallet
treasury = client.wallet.create_multisig(
    name="Engineering Team Treasury",
    signers=[
        {"id": "agent_1", "type": "agent"},
        {"id": "agent_2", "type": "agent"},
        {"id": "human_admin", "type": "human"}
    ],
    threshold=2  # 2 of 3 must approve
)

# Payment request (any signer can initiate)
request = client.multisig.request(
    treasury_id=treasury.id,
    recipient="0x...",
    amount="500.00",
    purpose="Quarterly API subscription"
)

# Other signers approve
client.multisig.approve(request.id, signer="agent_2")

# Executes automatically when threshold reached
```

---

### 6. 🧪 Payment Simulation (Dry Run)

*Before real money*: Test the entire flow without actual payment.

```python
# Simulate payment (no real money moves)
simulation = client.simulate(
    wallet_id=wallet,
    recipient="https://api.new-service.com",
    amount="25.00"
)

print(simulation.would_succeed)      # True
print(simulation.estimated_gas)      # "0.01"
print(simulation.guards_that_pass)   # ["BudgetGuard", "RateLimitGuard"]
print(simulation.recipient_type)     # "x402_api"
print(simulation.route)              # ["wallet → x402 → settle"]
```

---

### 7. 🔌 MCP (Model Context Protocol) Integration

*Native Claude/AI support*: OmniClaw as an MCP server.

```json
// mcp_config.json
{
  "mcpServers": {
    "omniclaw": {
      "command": "omniclaw-mcp",
      "args": ["--circle-api-key", "sk_..."],
      "tools": ["pay", "check_balance", "check_budget", "transaction_history"]
    }
  }
}
```

Claude can then call: *"Pay $5 to https://api.example.com for data analysis"*
→ Automatically routes to OmniClaw MCP tool

---

### 8. 📊 Payment Analytics & Optimization

*Intelligence*: Understand spending patterns, optimize costs.

```python
analytics = client.analytics.report(wallet_id=wallet, period="last_30_days")

print(analytics.total_spent)           # "$1,234.56"
print(analytics.transaction_count)     # 847
print(analytics.top_recipients)        # ["api.openai.com", "api.anthropic.com"]
print(analytics.avg_transaction)       # "$1.46"
print(analytics.cost_by_category)      # {"llm": 60%, "data": 30%, "compute": 10%}

# Optimization suggestions
print(analytics.suggestions)
# [
#   "Consider batching OpenAI calls - could save 15%",
#   "Peak usage at 2PM causes rate limits - spread load",
#   "3 unused API subscriptions detected"
# ]
```

---

### 9. 💳 Credit Lines & Overdraft

*Business flexibility*: Pre-approved spending beyond current balance.

```python
# Apply for credit line
credit = client.credit.apply(
    wallet_id=wallet,
    requested_amount="500.00",
    collateral_wallet=treasury_wallet
)

print(credit.status)        # "approved"
print(credit.limit)         # "500.00"
print(credit.available)     # "500.00"

# Agent can now spend beyond balance
# Credit automatically used if balance insufficient
```

---

### 10. 📱 Webhook System (Async Notifications)

*Integration*: External systems get notified of events.

```python
# Register webhooks
client.webhooks.register(
    url="https://myapp.com/payment-events",
    events=["payment.completed", "payment.failed", "budget.exceeded"],
    secret="whsec_..."
)

# Your endpoint receives:
{
  "event": "payment.completed",
  "data": {
    "transaction_id": "tx_abc123",
    "wallet_id": "wallet_xyz",
    "amount": "25.00",
    "recipient": "api.example.com",
    "blockchain_tx": "0x..."
  }
}
```

---

## Phase 1: Hackathon Scope

**Timeline**: January 10-24, 2026 (2 weeks)  
**Track**: Best Dev Tools

### Week 1: Infrastructure (Jan 10-17)
- Core SDK structure
- Circle Wallets integration
- x402 protocol executor
- Direct transfer executor
- Gateway integration (cross-chain)
- Spending guards
- Transaction ledger
- Python package

### Week 2: Demo (Jan 17-24)
- OmniCoreAgent integration
- Demo scenario: agent paying for APIs
- Arc testnet transactions
- Video demonstration
- Documentation
- Hackathon submission

---

## Future Roadmap

| Phase | Timeline | Focus |
|-------|----------|-------|
| **Phase 1** | Jan 2026 | Core infrastructure (hackathon) |
| **Phase 2** | Q1 2026 | Payment intents, simulation, webhooks, TypeScript SDK |
| **Phase 3** | Q2 2026 | Agent identity, A2A payments, streaming, AP2 support |
| **Phase 4** | H2 2026 | Multi-chain, enterprise, self-hosted, regulatory |

---

## Why We Win

| Competitor Gap | OmniClaw Solution |
|----------------|----------------------|
| No agent-native payments | Built specifically for AI agents |
| Complex integration | 1-line payment, full control optional |
| No cross-chain | Auto-bridge via Gateway, transparent |
| No spending controls | Guards, budgets, rate limits built-in |
| No context for agent memory | Purpose, metadata stored with each tx |
| No agent-to-agent | Escrow, reputation, A2A payments |
| Single protocol | x402 + direct + Gateway + CCTP |
| No observability | Events, webhooks, analytics |

---

## Get Started

```python
from omniclaw import OmniClaw

client = OmniClaw(circle_api_key="...")
wallet = client.wallet.create(operator_id="my_agent")
result = client.pay(wallet.id, "https://api.example.com", "5.00")
```

**That's it. The agent can now pay.**

---

> **Ready for Implementation?**
> 
> The hackathon scope (Phase 1) is well-defined and achievable in 2 weeks. The vision extends far beyond, but we start with a solid foundation.
