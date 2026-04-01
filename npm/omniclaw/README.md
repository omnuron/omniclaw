# OmniClaw Node.js SDK

Node.js/TypeScript SDK for OmniClaw payment workflows backed by Circle APIs. It is designed for production Node services and agents: typed APIs, async-first I/O, and optional x402 nanopayments through Circle Gateway.

Typical flow:

1. Configure the client (API key, wallet, optional nanopayment settings).
2. Run a local simulation before spending funds.
3. Execute payments or route by recipient and amount.
4. Inspect wallet balance and payment intents.
5. Route nanopayments through Circle Gateway (x402) when URLs or micro-amounts require it.
6. Apply guardrails, trust checks, and ledger tracking where you need operational safety.
7. Run seller-side x402 flows with facilitator support when you are the resource owner.

## Install

```bash
npm install omniclaw
```

## Environment variables

Required:

- `CIRCLE_API_KEY`
- `ENTITY_SECRET` (required when nanopayments are enabled)

Recommended:

- `CIRCLE_WALLET_ID`
- `CIRCLE_API_BASE_URL` (default: `https://api.circle.com`)
- `CIRCLE_GATEWAY_API_BASE_URL` (optional; defaults by environment)

## Quick start

```ts
import { OmniClaw } from "omniclaw";

const client = new OmniClaw();

const preview = client.simulatePayment({
  amount: "10.00",
  destinationAddress: "0x742d35cc6634c0532925a3b844bc9e7595f5e4a0"
});

if (preview.readyToExecute) {
  const payment = await client.createPayment({
    amount: "10.00",
    destinationAddress: "0x742d35cc6634c0532925a3b844bc9e7595f5e4a0"
  });

  console.log(payment.data?.id, payment.data?.status);
}
```

## Nanopayments quick start (x402)

```ts
import { OmniClaw } from "omniclaw";

const client = new OmniClaw({
  nanopaymentsEnabled: true,
  nanopaymentsEnvironment: "testnet",
  entitySecret: process.env.ENTITY_SECRET
});

// 1) create or import key used for EIP-3009 authorization signing
const buyerAddress = client.generateNanoKey("buyer-1");
client.setDefaultNanoKey("buyer-1");

// 2) pay an x402 endpoint (auto-detects GatewayWalletBatched in 402 response)
const result = await client.payX402Url({
  url: "https://your-paid-endpoint.example/premium"
});

console.log({ buyerAddress, result });
```

## API

### `new OmniClaw(config?)`

Config keys:

- `circleApiKey`
- `circleWalletId`
- `circleApiBaseUrl`
- `defaultCurrency` (default: `USD`)
- `defaultFeeRatePercent` (default: `0.2`)
- `nanopaymentsEnabled` (default: `true`)
- `nanopaymentsEnvironment` (`testnet` or `mainnet`, default: `testnet`)
- `gatewayApiBaseUrl` (optional override)
- `entitySecret` (required for encrypted nanopayment key storage)
- `nanopaymentKeyStorePath` (optional encrypted keystore JSON file path)
- `strictSettlement` (default `true`)
- `retryAttempts`, `retryBaseDelayMs`
- `circuitBreakerFailureThreshold`, `circuitBreakerRecoveryMs`
- `trustEvaluator`, `requireTrustGate`

Production behavior:

- if `OMNICLAW_ENV` is `prod`/`production`/`mainnet`, `strictSettlement` must remain `true`
- when nanopayments are enabled in production, set `ENTITY_SECRET` and `nanopaymentKeyStorePath`

### `simulatePayment(params)`

Local-only simulation output:

- `estimatedFees`
- `netTransfer`
- `transferConfirmationPreview`
- `readyToExecute`

### `payWithRouting(params)`

Unified routing by recipient and amount:

- routes `https://...` recipients through x402 nanopayments
- routes micro direct payments (`amount < 1`) through direct nanopayments
- routes larger direct transfers through Circle `POST /v1/payments`
- always runs simulation first
- supports trust checks and guardrails before execution

### `createPayment(params)` / `pay(params)`

Calls:

- `POST /v1/payments`

### `getWalletBalance(walletId?)`

Calls:

- `GET /v1/wallets/:walletId`

### `createPaymentIntent(params)`

Calls:

- `POST /v1/paymentIntents`

### `getPaymentIntent(intentId)`

Calls:

- `GET /v1/paymentIntents/:intentId`

### `confirmPaymentIntent(intentId)`

Calls:

- `POST /v1/paymentIntents/:intentId/confirm`

### Nanopayment methods (Circle Gateway x402)

- `generateNanoKey(alias)` / `addNanoKey(alias, privateKey)`
- `setDefaultNanoKey(alias)` / `listNanoKeys()` / `getNanoAddress(alias?)`
- `getGatewaySupportedNetworks()`
- `getGatewayBalance(alias?, network?)`
- `payX402Url({ url, method?, headers?, body?, keyAlias? })`
- `payDirectNano({ sellerAddress, amountUsdc, network, keyAlias? })`

### Guardrail methods

- `addBudgetGuard(walletId, maxBudget)`
- `addRateLimitGuard(walletId, maxCalls, windowMs)`
- `addRecipientGuard(walletId, allowedRecipients)`
- `addSingleTxGuard(walletId, maxAmount)`
- `addConfirmGuard(walletId, threshold)`
- `listGuards(walletId?)`

### Ledger and intents

- `listLedgerEntries()` returns in-memory payment ledger entries with status transitions.
- `createPaymentIntent(...)` creates idempotent local intent state and includes metadata when calling Circle.
- `cancelPaymentIntent(intentId)` updates local intent state.

### Exported nanopayment classes

- `NanopaymentClient`
- `NanoKeyVault`
- `NanopaymentAdapter`
- `GatewayMiddleware`
- `parsePrice`

### Seller SDK

- `Seller`, `createSeller`
- `CircleGatewayFacilitator`
- `createFacilitator` for `circle`, `coinbase`, `ordern`, `rbx`, `thirdweb`
- `SUPPORTED_FACILITATORS`

Seller usage:

```ts
import { createFacilitator, createSeller } from "omniclaw";

const facilitator = createFacilitator({
  provider: "circle",
  apiKey: process.env.CIRCLE_API_KEY!,
  environment: "testnet"
});

const seller = createSeller(
  {
    sellerAddress: "0x742d35cc6634c0532925a3b844bc9e7595f5e4a0",
    name: "Weather API",
    network: "eip155:5042002",
    usdcContract: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    gatewayContract: "0xGatewayContract",
    strictGatewayContract: true,
    nonceStorePath: ".omniclaw-seller-nonces.json"
  },
  facilitator
);

seller.addEndpoint({ path: "/weather", priceUsd: "0.001", description: "Current weather" });
const paymentRequired = seller.buildPaymentRequired("/weather");
```

### Webhook verification

- `WebhookVerifier` verifies Circle webhook signatures and replay windows.
- Supports signature headers: `x-circle-signature` / `circle-signature`.
- Supports timestamp headers: `x-circle-timestamp` / `circle-timestamp`.
- Rejects duplicate `notificationId` values while the verifier instance is alive.
- Optional dedup persistence: `dedupStorePath` in `WebhookVerifierOptions`.

## Design notes

- Nanopayments cover key management, x402 URL payments, direct nano transfers, and gateway balance and network discovery.
- Private keys are encrypted with PBKDF2 + AES-256-GCM before persistence.
- x402 flows use CAIP-2 validation, strict-settlement mode, retry with backoff, and a circuit breaker.
- Guardrails, trust-gate hooks, local intents, and ledger tracking support auditable runtime behavior.
- Seller x402 flows include endpoint protection, nonce replay prevention, and facilitator-based settlement.

## Build and package

```bash
npm install
npm run release:check
```

Optional offline integration smoke test (mocked HTTP, no live Circle calls):

```bash
npm run smoke:validate
```
