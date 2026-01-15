# OmniAgentPay: MCP Server Architecture

> **Model Context Protocol Integration for AI-Native Payments**
> 
> "Enabling Claude and AI models to execute payments directly"

---

## Overview

The MCP (Model Context Protocol) Server exposes OmniAgentPay functionality as **tools that AI models can call directly**. This allows Claude, GPT, Gemini, and other models to autonomously manage wallets and execute payments.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI MODEL (Claude, etc.)                            │
│                                                                              │
│   "I need to pay for this API to complete the user's task"                  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ MCP Tool Call
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MCP SERVER (omniagentpay-mcp)                        │
│                                                                              │
│   Exposed Tools:                                                             │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │ pay │ check_balance │ simulate │ bridge │ unified_balance │ history │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│   Resources:                                                                 │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │ wallet://{id}/balance │ wallet://{id}/history │ config://guards     │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OMNIAGENTPAY SDK                                     │
│                                                                              │
│   OmniAgentPayClient → WalletService, PaymentRouter, Guards                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## System Architecture

### MCP Server Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP SERVER                                          │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Server Core                                   │    │
│  │  • Initializes with OmniAgentPayClient                              │    │
│  │  • Handles MCP protocol communication                               │    │
│  │  • Manages tool/resource registration                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Tool Handlers                                 │    │
│  │                                                                      │    │
│  │  pay_tool()             → client.pay()                              │    │
│  │  check_balance_tool()   → client.wallet.balance()                   │    │
│  │  simulate_tool()        → client.simulate()                         │    │
│  │  bridge_tool()          → client.crosschain.bridge()                │    │
│  │  unified_balance_tool() → client.crosschain.gateway_balance()       │    │
│  │  list_wallets_tool()    → client.wallet.list()                      │    │
│  │  history_tool()         → client.history()                          │    │
│  │  create_wallet_tool()   → client.wallet.create()                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      Resource Handlers                               │    │
│  │                                                                      │    │
│  │  wallet://{id}/balance  → Real-time balance                         │    │
│  │  wallet://{id}/history  → Transaction history                       │    │
│  │  config://guards        → Active guard configuration                │    │
│  │  config://network       → Network information                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      Prompt Templates                                │    │
│  │                                                                      │    │
│  │  payment-guide    → How to use payment tools                        │    │
│  │  error-handling   → How to handle payment errors                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tool Definitions

### 1. pay
```yaml
name: pay
description: Execute a payment to a recipient (URL for x402, address for transfer)
inputSchema:
  type: object
  properties:
    recipient:
      type: string
      description: URL (for x402 payment) or wallet address (for direct transfer)
    amount:
      type: string
      description: Amount in USDC (e.g., "5.00")
    purpose:
      type: string
      description: Human-readable purpose for the payment
    wallet_id:
      type: string
      description: Optional wallet ID (uses default if not provided)
  required: [recipient, amount]

response:
  success: boolean
  transaction_id: string
  blockchain_tx: string
  remaining_balance: string
  error: string | null
```

### 2. check_balance
```yaml
name: check_balance
description: Get the current USDC balance of a wallet
inputSchema:
  type: object
  properties:
    wallet_id:
      type: string
      description: Wallet ID (optional, uses default)
  required: []

response:
  balance: string
  currency: "USDC"
  network: string
```

### 3. simulate
```yaml
name: simulate
description: Simulate a payment without executing (dry run)
inputSchema:
  type: object
  properties:
    recipient:
      type: string
    amount:
      type: string
  required: [recipient, amount]

response:
  would_succeed: boolean
  route: string  # "x402" | "transfer" | "gateway"
  guards_that_pass: array[string]
  guards_that_fail: array[string]
  reason: string | null
```

### 4. list_wallets
```yaml
name: list_wallets
description: List all available wallets
inputSchema:
  type: object
  properties: {}

response:
  wallets:
    - id: string
      address: string
      balance: string
```

### 5. history
```yaml
name: history
description: Get recent transaction history
inputSchema:
  type: object
  properties:
    wallet_id:
      type: string
    limit:
      type: integer
      default: 10
  required: []

response:
  transactions:
    - id: string
      recipient: string
      amount: string
      status: string
      timestamp: string
```

### 6. create_wallet
```yaml
name: create_wallet
description: Create a new wallet for the agent
inputSchema:
  type: object
  properties:
    name:
      type: string
      description: Human-readable name for the wallet
  required: [name]

response:
  wallet_id: string
  address: string
  network: string
```

### 7. bridge (Crosschain Transfer)
```yaml
name: bridge
description: Transfer USDC across blockchains using Bridge Kit, CCTP, or Gateway
inputSchema:
  type: object
  properties:
    source_chain:
      type: string
      description: Source blockchain (e.g., "arc", "ethereum", "base", "solana")
    destination_chain:
      type: string
      description: Destination blockchain
    amount:
      type: string
      description: Amount in USDC (e.g., "10.00")
    destination_address:
      type: string
      description: Recipient address on destination chain (optional, defaults to same owner)
    method:
      type: string
      enum: ["auto", "bridge_kit", "cctp", "gateway"]
      description: Transfer method (auto selects optimal)
  required: [source_chain, destination_chain, amount]

response:
  success: boolean
  source_tx: string
  destination_tx: string
  method_used: string
  estimated_time: string
  error: string | null
```

### 8. unified_balance (Gateway)
```yaml
name: unified_balance
description: Get or manage unified USDC balance across chains via Circle Gateway
inputSchema:
  type: object
  properties:
    action:
      type: string
      enum: ["check", "deposit", "mint"]
      description: "check: view balance, deposit: add to unified, mint: withdraw to chain"
    chain:
      type: string
      description: Target chain for deposit/mint operations
    amount:
      type: string
      description: Amount for deposit/mint operations
  required: [action]

response:
  unified_balance: string
  chain_balances:
    - chain: string
      balance: string
  transaction_id: string | null
  error: string | null
```

---

## Deployment Options

### Option 1: Standalone Server
```bash
# Run as standalone MCP server
$ omniagentpay-mcp --port 8402

# Or with stdio transport
$ omniagentpay-mcp --transport stdio
```

### Option 2: Claude Desktop Integration
```json
// ~/.config/claude/mcp_servers.json
{
  "omniagentpay": {
    "command": "omniagentpay-mcp",
    "args": ["--transport", "stdio"],
    "env": {
      "CIRCLE_API_KEY": "sk_...",
      "WALLET_ID": "wallet_..."
    }
  }
}
```

### Option 3: Programmatic
```python
from omniagentpay.mcp import create_mcp_server
from omniagentpay import OmniAgentPay

client = OmniAgentPay(circle_api_key="...")
server = create_mcp_server(client, default_wallet_id="...")

# Run with your preferred transport
server.run()
```

---

## Security Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SECURITY LAYERS                                     │
│                                                                              │
│  1. Authentication (MCP Server Level)                                        │
│     • API key required in environment                                        │
│     • No secrets exposed to AI model                                        │
│                                                                              │
│  2. Authorization (SDK Guard Level)                                          │
│     • BudgetGuard limits total spending                                     │
│     • RateLimitGuard prevents spam                                          │
│     • SingleTxGuard caps individual payments                                │
│     • RecipientGuard whitelists allowed recipients                          │
│                                                                              │
│  3. Confirmation (Optional)                                                  │
│     • High-value payments can require human confirmation                    │
│     • Configurable threshold                                                │
│                                                                              │
│  AI Model can:                                                               │
│  ✓ Execute payments within guard limits                                     │
│  ✓ Check balances                                                           │
│  ✓ View transaction history                                                 │
│  ✗ Cannot bypass guards                                                     │
│  ✗ Cannot access API keys                                                   │
│  ✗ Cannot modify guard configuration                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Example AI Model Interaction

```
User: "Purchase the premium data analysis from the API"

AI Model (Claude):
1. [Thinking] I need to pay for the premium API
2. [Tool Call] simulate(recipient="https://analytics.api/premium", amount="10.00")
3. [Response] { would_succeed: true, route: "x402", guards_that_pass: ["BudgetGuard", "RateLimitGuard"] }
4. [Tool Call] pay(recipient="https://analytics.api/premium", amount="10.00", purpose="Premium data analysis")
5. [Response] { success: true, blockchain_tx: "0x8a3d...", remaining_balance: "90.00" }
6. [To User] "I've purchased the premium data analysis for 10.00 USDC. 
              Transaction: 0x8a3d... 
              Remaining balance: 90.00 USDC"
```

---

## Project Structure

```
omniagentpay/
├── src/omniagentpay/
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py          # MCP server creation
│   │   ├── tools.py           # Tool definitions
│   │   ├── resources.py       # Resource handlers
│   │   └── prompts.py         # Prompt templates
│   └── ...
│
└── scripts/
    └── omniagentpay-mcp       # CLI entry point
```

---

## Implementation Notes

### Dependencies
```toml
[project.optional-dependencies]
mcp = [
    "mcp>=1.0.0",  # Model Context Protocol SDK
]
```

### Entry Point
```toml
[project.scripts]
omniagentpay-mcp = "omniagentpay.mcp:main"
```

---

> **Why MCP Matters**: Judges using Claude can test the SDK directly during evaluation. This is a powerful differentiator.
