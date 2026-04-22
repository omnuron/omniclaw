# OmniClaw Agent Getting Started

This guide walks you through setting up an OmniClaw agent for policy-controlled payments.

OmniClaw is the **Economic Execution and Control Layer for Agentic Systems**.
In that system:

- the owner runs the **Financial Policy Engine**
- the agent uses `omniclaw-cli` as the **zero-trust execution layer**
- buyers pay with `omniclaw-cli pay`
- agents can expose paid services for other agents or automation with `omniclaw-cli serve`

For vendor, SaaS, or enterprise APIs embedded directly in an application, use the Python SDK seller middleware instead of `omniclaw-cli serve`. See the [Developer Guide](developer-guide.md).

---

## Prerequisites

- Python 3.10+
- Circle API key
- Circle Entity Secret if your Circle account/API key already has one
- USDC on the target network (testnet or mainnet)
- A private key for your agent

---

## Step 1: Create Policy.json

Create a `policy.json` file that defines your agent:

```json
{
  "version": "2.0",
  "tokens": {
    "my-agent-token": {
      "wallet_alias": "primary",
      "active": true,
      "label": "My Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Primary Wallet",
      "limits": {
        "daily_max": "100.00",
        "per_tx_max": "50.00"
      },
      "recipients": {
        "mode": "allow_all"
      }
    }
  }
}
```

On startup, the server will auto-generate and persist `wallet_id` and `address`
inside each wallet entry if they are missing.

You can copy the default from `examples/default-policy.json` and edit it.

The server validates policy.json on startup and will refuse to boot if it is invalid.

---

## Step 2: Set Environment Variables

```bash
# Required
export OMNICLAW_PRIVATE_KEY="0x..."           # Your agent's private key
export OMNICLAW_AGENT_TOKEN="my-agent-token"   # Must match policy.json token key
export OMNICLAW_AGENT_POLICY_PATH="/path/to/policy.json"
export CIRCLE_API_KEY="your-circle-api-key"

# Required when your Circle account/API key already has an Entity Secret.
# If omitted, OmniClaw only auto-generates one when no existing local secret is found.
export ENTITY_SECRET="your-existing-64-char-hex-entity-secret"

# Network (testnet or mainnet)
export OMNICLAW_NETWORK="ETH-SEPOLIA"         # or ETH-MAINNET for production

# Set production for mainnet usage
export OMNICLAW_ENV="production"              # optional - for mainnet

# RPC for on-chain operations
export OMNICLAW_RPC_URL="https://..."
export OMNICLAW_OWNER_TOKEN="your-owner-token" # Required for approvals
export OMNICLAW_POLICY_RELOAD_INTERVAL="5"     # Hot reload interval (seconds)
```

---

## Step 3: Start the Financial Policy Engine

```bash
omniclaw server --port 8080
```

The Financial Policy Engine runs at `http://localhost:8080`.

---

## Step 4: Configure the CLI

For agents, use environment variables (no interactive setup required):

```bash
export OMNICLAW_SERVER_URL="http://localhost:8080"
export OMNICLAW_TOKEN="my-agent-token"
```

Optional: persist config locally for dev workflows:

```bash
omniclaw-cli configure --server-url http://localhost:8080 --token my-agent-token --wallet primary
```

CLI output is agent-first (JSON, no banner). For human-friendly output set:

```bash
export OMNICLAW_CLI_HUMAN=1
```

---

## Step 5: Use the CLI

### Check Your Address
```bash
omniclaw-cli address
```

### Check Balance
```bash
omniclaw-cli balance

# Or detailed view
omniclaw-cli balance_detail
```

### Deposit USDC to Gateway
```bash
omniclaw-cli deposit --amount 10
```
This moves USDC from your EOA to the Circle Gateway contract. It is required for `GatewayWalletBatched` nanopayments. It is not required for standard x402 `exact` payments that spend from the buyer signer directly.

### Withdraw to Circle Wallet
```bash
omniclaw-cli withdraw --amount 5
```
This moves USDC from Gateway to your Circle Developer Wallet.

### Buyer Flow For x402 Services

For a new paid URL, use this order:

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/premium
omniclaw-cli inspect-x402 --recipient https://seller.example.com/premium
omniclaw-cli pay --recipient https://seller.example.com/premium --idempotency-key job-123
```

What this tells you:

- `can-pay` confirms policy allow or deny
- `inspect-x402` shows whether the seller is paywalled, what schemes it advertises, and whether OmniClaw will use `gateway_balance` or `direct_wallet`
- `pay` executes through the single `/api/v1/pay` buyer route

For x402 URLs, OmniClaw chooses the route from the seller's advertised requirements:

- `GatewayWalletBatched` when the seller advertises Circle Gateway nanopayments and the buyer is actually Gateway-ready
- `exact` when the seller advertises a standard x402 payment flow

If the seller advertises both and the buyer has no Gateway balance, OmniClaw uses `exact`.

If the seller is exact-only, OmniClaw routes directly to the x402 exact path.

---

## Confirmations (High-Value Policy Thresholds)

If a policy requires confirmation, `/pay` will return:

- `requires_confirmation: true`
- `confirmation_id: <id>`

Approve with the owner token:

```bash
omniclaw-cli configure --owner-token YOUR_OWNER_TOKEN
omniclaw-cli confirmations approve --id <confirmation_id>
```

Then retry the payment with the same `confirmation_id` in metadata:

```json
{
  "recipient": "0xRecipient",
  "amount": "50.00",
  "metadata": {
    "confirmation_id": "<confirmation_id>"
  }
}
```

---

## Agent-to-Agent Selling (Local Data)

If an agent wants to temporarily sell access to a local Python script or data file to another agent, they can use the CLI to spin up a fast payment gate:

```bash
omniclaw-cli serve \
  --price 0.01 \
  --endpoint /api/data \
  --exec "python safe_readonly_service.py" \
  --port 8000
```

This opens `http://localhost:8000/api/data` that requires a USDC payment to execute the approved command and return its output.

`serve` binds to all interfaces and `--exec` runs a host command. Use it only when the owner explicitly wants an agent-run seller endpoint, and prefer an isolated container or private development network.

> **Web developer or vendor:** If the paid route lives inside your application, use the Python SDK inside your FastAPI application instead of `omniclaw-cli serve`. Use `serve` when the seller surface itself is agent-run. See the [Developer Guide](developer-guide.md).

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `omniclaw-cli address` | Get your wallet address |
| `omniclaw-cli balance` | Check balance |
| `omniclaw-cli deposit --amount X` | Deposit to Gateway |
| `omniclaw-cli withdraw --amount X` | Withdraw to Circle wallet |
| `omniclaw-cli withdraw_trustless --amount X` | Trustless withdraw (~7-day delay) |
| `omniclaw-cli withdraw_trustless_complete` | Complete trustless withdraw after delay |
| `omniclaw-cli inspect-x402 --recipient URL` | Inspect seller requirements and buyer readiness |
| `omniclaw-cli pay --recipient 0x... --amount X` | Pay another agent |
| `omniclaw-cli pay --recipient URL` | Pay a seller x402 endpoint |
| `omniclaw-cli serve --price X --endpoint /api --exec "cmd"` | Start an owner-approved agent-run payment gate |

---

## Network Switching

To switch from testnet to mainnet:

```bash
export OMNICLAW_NETWORK="ETH-MAINNET"
export OMNICLAW_ENV="production"
```

Everything automatically switches to mainnet URLs.

---

## Troubleshooting

### "Wallet is currently initializing"
Wait a few seconds and retry. The agent is setting up.

### "Invalid token"
Check that `OMNICLAW_AGENT_TOKEN` matches a key in your policy.json's `tokens` section.

### "Insufficient balance"
Check which route the seller requires:

```bash
omniclaw-cli inspect-x402 --recipient https://seller.example.com/premium
```

If the route is `GatewayWalletBatched`, deposit to Gateway first:

```bash
omniclaw-cli deposit --amount 10
```

If the route is `exact`, fund the buyer signer wallet on the required chain instead.
