import { generateKeyPairSync, sign as signPayload } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Wallet } from "ethers";

import {
  OmniClaw,
  WebhookVerifier,
  createSeller,
  quick_setup
} from "../index.js";

type FetchFn = typeof fetch;
const SELLER_ADDR = "0x742d35cc6634c0532925a3b844bc9e7595f5e4a0";

function assert(condition: unknown, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function buildPaymentRequiredHeader(): string {
  const requirements = {
    x402Version: 2,
    accepts: [
      {
        scheme: "exact",
        network: "eip155:5042002",
        asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        amount: "1000",
        payTo: SELLER_ADDR,
        maxTimeoutSeconds: 345600,
        extra: {
          name: "GatewayWalletBatched",
          version: "1",
          verifyingContract: "0x1111111111111111111111111111111111111111"
        }
      }
    ]
  };
  return Buffer.from(JSON.stringify(requirements), "utf8").toString("base64");
}

function createMockFetch(): FetchFn {
  const paymentRequiredHeader = buildPaymentRequiredHeader();

  return (async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const headers = new Headers(init?.headers);

    if (url.includes("/v1/payments") && method === "POST") {
      return jsonResponse({
        data: { id: "pay_123", status: "pending", amount: { amount: "2.00", currency: "USD" } }
      });
    }
    if (url.includes("/v1/wallets/") && method === "GET") {
      return jsonResponse({
        data: { walletId: "wallet-123", balances: [{ amount: "12.500000", currency: "USD" }] }
      });
    }
    if (url.endsWith("/v1/walletSets") && method === "POST") {
      return jsonResponse({ data: { id: "ws_1", walletSetId: "ws_1" } });
    }
    if (url.includes("/v1/wallets") && method === "POST") {
      return jsonResponse({ data: { id: "w_1", walletId: "w_1", address: "0xabc" } });
    }
    if (url.includes("/v1/walletSets") && method === "GET") {
      return jsonResponse({ data: [{ id: "ws_1" }] });
    }
    if (url.match(/\/v1\/wallets(\?|$)/) && method === "GET") {
      return jsonResponse({ data: [{ id: "w_1", walletId: "w_1", address: "0xabc" }] });
    }
    if (url.endsWith("/v1/paymentIntents") && method === "POST") {
      return jsonResponse({
        data: { id: "intent_1", status: "pending", amount: { amount: "1.00", currency: "USD" } }
      });
    }
    if (url.includes("/v1/paymentIntents/") && method === "GET") {
      return jsonResponse({
        data: { id: "intent_1", status: "pending", amount: { amount: "1.00", currency: "USD" } }
      });
    }
    if (url.includes("/v1/paymentIntents/") && method === "POST") {
      return jsonResponse({
        data: { id: "intent_1", status: "confirmed", amount: { amount: "1.00", currency: "USD" } }
      });
    }
    if (url.endsWith("/v1/x402/supported") && method === "GET") {
      return jsonResponse({
        kinds: [
          {
            x402Version: 2,
            scheme: "exact",
            network: "eip155:5042002",
            extra: {
              verifyingContract: "0x1111111111111111111111111111111111111111",
              usdcAddress: "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
            }
          }
        ]
      });
    }
    if (url.endsWith("/v1/balances") && method === "POST") {
      return jsonResponse({
        balances: [{ amount: "10.000000", token: "USDC", network: "eip155:5042002" }]
      });
    }
    if (url.endsWith("/v1/x402/settle") && method === "POST") {
      return jsonResponse({
        success: true,
        transaction: "settle_tx_1",
        network: "eip155:5042002"
      });
    }
    if (url === "https://your-paid-endpoint.example/premium") {
      if (!headers.get("PAYMENT-SIGNATURE")) {
        return new Response(JSON.stringify({ error: "payment required" }), {
          status: 402,
          headers: {
            "content-type": "application/json",
            "payment-required": paymentRequiredHeader
          }
        });
      }
      return new Response(JSON.stringify({ ok: true, data: "paid content" }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    }

    return new Response(JSON.stringify({ error: `unhandled mock: ${method} ${url}` }), {
      status: 500,
      headers: { "content-type": "application/json" }
    });
  }) as FetchFn;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

async function run(): Promise<void> {
  const mockFetch = createMockFetch();
  const tempRoot = mkdtempSync(join(tmpdir(), "omniclaw-smoke-"));
  const keyStorePath = join(tempRoot, "nano-keys.json");
  const nonceStorePath = join(tempRoot, "seller-nonces.json");

  try {
    const env = quick_setup("test_circle_key", "test_entity_secret_1234567890");
    assert(Boolean(env.CIRCLE_API_KEY), "quick_setup should return api key");

    const client = new OmniClaw({
      circleApiKey: "test_circle_key",
      circleWalletId: "wallet-123",
      entitySecret: "test_entity_secret_1234567890",
      nanopaymentKeyStorePath: keyStorePath,
      fetchImpl: mockFetch,
      trustEvaluator: async (recipient) =>
        recipient.includes("blocked")
          ? { verdict: "block", reason: "blocked recipient" }
          : { verdict: "allow", score: 0.9 }
    });

    const nanoAddress = client.generateNanoKey("buyer-1");
    client.setDefaultNanoKey("buyer-1");
    assert(nanoAddress.startsWith("0x"), "generated nano address must be an EVM address");

    const sim = client.simulatePayment({
      amount: "2.00",
      destinationAddress: SELLER_ADDR
    });
    assert(sim.readyToExecute, "simulation should succeed");

    client.addRecipientGuard("wallet-123", [SELLER_ADDR]);
    const routed = await client.payWithRouting({
      walletId: "wallet-123",
      recipient: SELLER_ADDR,
      amount: "2.00",
      checkTrust: true
    });
    assert(routed.success, "direct routed payment should succeed");
    assert(routed.route === "circle_transfer", "route should be circle_transfer");

    const x402 = await client.payX402Url({
      url: "https://your-paid-endpoint.example/premium"
    });
    assert(x402.success, "x402 nanopayment should settle");
    assert(x402.isNanopayment, "x402 result should be nanopayment");

    const paymentIntent = await client.createPaymentIntent({
      amount: "1.00",
      recipient: SELLER_ADDR,
      sourceWalletId: "wallet-123",
      idempotencyKey: "intent-test-key"
    });
    assert(Boolean(paymentIntent.data?.id), "payment intent should be created");

    const balance = await client.getWalletBalance("wallet-123");
    assert(balance.data?.balances?.[0]?.amount === "12.500000", "wallet balance should be mocked");

    // Webhook verification test (Ed25519)
    const { publicKey, privateKey } = generateKeyPairSync("ed25519");
    const publicKeyPem = publicKey.export({ format: "pem", type: "spki" }).toString();
    const payload = JSON.stringify({
      notificationType: "payments",
      notificationId: "notif-1",
      createDate: new Date().toISOString()
    });
    const signature = signPayload(null, Buffer.from(payload, "utf8"), privateKey).toString("base64");
    const verifier = new WebhookVerifier({
      verificationKey: publicKeyPem,
      dedupStorePath: join(tempRoot, "webhook-dedup.json")
    });
    const verified = verifier.verify(payload, {
      "x-circle-signature": signature,
      "x-circle-timestamp": String(Math.floor(Date.now() / 1000))
    });
    assert(verified.notificationId === "notif-1", "webhook should verify");

    // Seller flow with local settlement and nonce replay protection.
    const seller = createSeller({
      sellerAddress: SELLER_ADDR,
      name: "Weather API",
      network: "eip155:5042002",
      usdcContract: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
      gatewayContract: "0x1111111111111111111111111111111111111111",
      strictGatewayContract: true,
      nonceStorePath
    });
    seller.addEndpoint({
      path: "/weather",
      priceUsd: "0.001",
      schemes: ["GatewayWalletBatched"]
    });
    const paymentRequired = seller.buildPaymentRequired("/weather");

    const buyerWallet = Wallet.createRandom();
    const accepted = (paymentRequired.body.accepts as Array<Record<string, unknown>>)[0];
    const auth = {
      from: buyerWallet.address,
      to: String(accepted.payTo),
      value: String(accepted.amount),
      validAfter: "0",
      validBefore: String(Math.floor(Date.now() / 1000) + 345600),
      nonce: `0x${Buffer.from("n".repeat(32)).toString("hex").slice(0, 64)}`
    };
    const sig = await buyerWallet.signTypedData(
      {
        name: String((accepted.extra as Record<string, unknown>).name),
        version: String((accepted.extra as Record<string, unknown>).version),
        chainId: 5042002,
        verifyingContract: String((accepted.extra as Record<string, unknown>).verifyingContract)
      },
      {
        TransferWithAuthorization: [
          { name: "from", type: "address" },
          { name: "to", type: "address" },
          { name: "value", type: "uint256" },
          { name: "validAfter", type: "uint256" },
          { name: "validBefore", type: "uint256" },
          { name: "nonce", type: "bytes32" }
        ]
      },
      auth
    );
    const signatureHeader = Buffer.from(
      JSON.stringify({
        x402Version: 2,
        scheme: "exact",
        network: "eip155:5042002",
        payload: { authorization: auth, signature: sig }
      }),
      "utf8"
    ).toString("base64");

    const settled = await seller.settlePayment({
      paymentSignatureHeader: signatureHeader,
      paymentRequiredBody: paymentRequired.body,
      endpointPath: "/weather"
    });
    assert(settled.success, "seller settlement should succeed");

    const replayAttempt = await seller.verifyPayment({
      paymentSignatureHeader: signatureHeader,
      paymentRequiredBody: paymentRequired.body
    });
    assert(!replayAttempt.isValid, "seller should reject nonce replay");

    // eslint-disable-next-line no-console
    console.log("Integration smoke test passed.");
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

run().catch((error) => {
  // eslint-disable-next-line no-console
  console.error("Integration smoke test failed:", error);
  process.exitCode = 1;
});
