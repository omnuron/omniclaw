import { Buffer } from "node:buffer";

import { assertEvmAddress, assertHttpsUrl, assertPositiveDecimal } from "../../core/validation.js";
import { CIRCLE_BATCHING_NAME } from "./constants.js";
import {
  CircuitOpenError,
  InvalidPaymentRequirementsError,
  UnsupportedSchemeError
} from "./errors.js";
import type {
  NanopaymentAdapterOptions,
  NanopaymentResult,
  PaymentRequirements,
  PaymentRequirementsKind,
  PayX402UrlParams
} from "./types.js";
import { NanopaymentClient } from "./client.js";
import { NanoKeyVault } from "./vault.js";

class NanopaymentCircuitBreaker {
  private failures = 0;
  private openedAt = 0;

  constructor(
    private readonly failureThreshold: number,
    private readonly recoveryMs: number
  ) {}

  ensureAvailable(): void {
    if (this.failures < this.failureThreshold) {
      return;
    }
    const elapsed = Date.now() - this.openedAt;
    if (elapsed < this.recoveryMs) {
      throw new CircuitOpenError();
    }
    this.failures = 0;
    this.openedAt = 0;
  }

  recordSuccess(): void {
    this.failures = 0;
    this.openedAt = 0;
  }

  recordFailure(): void {
    this.failures += 1;
    if (this.failures >= this.failureThreshold && this.openedAt === 0) {
      this.openedAt = Date.now();
    }
  }
}

export class NanopaymentAdapter {
  private readonly strictSettlement: boolean;
  private readonly retryAttempts: number;
  private readonly retryBaseDelayMs: number;
  private readonly circuitBreaker: NanopaymentCircuitBreaker;

  constructor(
    private readonly vault: NanoKeyVault,
    private readonly client: NanopaymentClient,
    private readonly fetchImpl: typeof fetch = fetch,
    options: NanopaymentAdapterOptions = {}
  ) {
    this.strictSettlement = options.strictSettlement ?? true;
    this.retryAttempts = options.retryAttempts ?? 3;
    this.retryBaseDelayMs = options.retryBaseDelayMs ?? 250;
    this.circuitBreaker = new NanopaymentCircuitBreaker(
      options.circuitBreakerFailureThreshold ?? 5,
      options.circuitBreakerRecoveryMs ?? 60_000
    );
  }

  async payX402Url(params: PayX402UrlParams): Promise<NanopaymentResult> {
    assertHttpsUrl(params.url, "url");
    this.circuitBreaker.ensureAvailable();

    const initialResp = await this.fetchImpl(params.url, {
      method: (params.method ?? "GET").toUpperCase(),
      headers: params.headers,
      body: params.body
    });

    if (initialResp.status !== 402) {
      return {
        success: initialResp.ok,
        isNanopayment: false,
        payer: "",
        seller: "",
        transaction: "",
        amountAtomic: "0",
        amountUsdc: "0",
        network: "",
        responseStatus: initialResp.status,
        responseData: await initialResp.text()
      };
    }

    const paymentRequiredHeader =
      initialResp.headers.get("payment-required") ?? initialResp.headers.get("PAYMENT-REQUIRED");
    if (!paymentRequiredHeader) {
      throw new UnsupportedSchemeError("402 response missing PAYMENT-REQUIRED header");
    }

    const requirements = parsePaymentRequirements(paymentRequiredHeader);
    const kind = requirements.accepts.find((entry) => entry.extra?.name === CIRCLE_BATCHING_NAME);
    if (!kind) {
      throw new UnsupportedSchemeError();
    }

    const payload = await this.vault.sign(kind, params.keyAlias);
    const paymentSignature = Buffer.from(JSON.stringify(payload), "utf8").toString("base64");

    const retryResp = await this.fetchImpl(params.url, {
      method: (params.method ?? "GET").toUpperCase(),
      headers: {
        ...(params.headers ?? {}),
        "PAYMENT-SIGNATURE": paymentSignature
      },
      body: params.body
    });

    let transaction = "";
    let settlementSuccess = false;
    let settlementError: unknown;
    try {
      const settleResp = await this.settleWithRetry(payload, {
        x402Version: requirements.x402Version,
        accepts: [kind]
      });
      transaction = settleResp.transaction ?? "";
      settlementSuccess = settleResp.success;
      this.circuitBreaker.recordSuccess();
    } catch (error) {
      settlementError = error;
      settlementSuccess = false;
      this.circuitBreaker.recordFailure();
    }

    const amountAtomic = kind.amount;
    const amountUsdc = (Number.parseInt(amountAtomic, 10) / 1_000_000).toString();
    const contentDelivered = retryResp.ok;
    const success = this.strictSettlement
      ? contentDelivered && settlementSuccess
      : contentDelivered || settlementSuccess;
    if (this.strictSettlement && contentDelivered && !settlementSuccess && settlementError) {
      throw settlementError;
    }

    return {
      success,
      isNanopayment: true,
      payer: this.vault.getAddress(params.keyAlias),
      seller: kind.payTo,
      transaction,
      amountAtomic,
      amountUsdc,
      network: kind.network,
      responseStatus: retryResp.status,
      responseData: await retryResp.text()
    };
  }

  async payDirect(params: {
    sellerAddress: string;
    amountUsdc: string;
    network: string;
    keyAlias?: string;
  }): Promise<NanopaymentResult> {
    this.circuitBreaker.ensureAvailable();
    assertEvmAddress(params.sellerAddress, "sellerAddress");
    assertPositiveDecimal(params.amountUsdc, "amountUsdc");
    assertCaip2Network(params.network);

    const supported = await this.client.getSupported();
    const match = supported.find((entry) => entry.network === params.network);
    if (!match?.extra?.verifyingContract || !match.extra.usdcAddress) {
      throw new UnsupportedSchemeError(`No supported Gateway contract for network ${params.network}`);
    }

    const amountAtomic = Math.round(Number.parseFloat(params.amountUsdc) * 1_000_000).toString();
    const kind: PaymentRequirementsKind = {
      scheme: "exact",
      network: params.network,
      asset: match.extra.usdcAddress,
      amount: amountAtomic,
      maxTimeoutSeconds: 345600,
      payTo: params.sellerAddress,
      extra: {
        name: CIRCLE_BATCHING_NAME,
        version: "1",
        verifyingContract: match.extra.verifyingContract
      }
    };

    const payload = await this.vault.sign(kind, params.keyAlias);
    const settleResp = await this.settleWithRetry(payload, { x402Version: 2, accepts: [kind] });
    this.circuitBreaker.recordSuccess();

    return {
      success: settleResp.success,
      isNanopayment: true,
      payer: this.vault.getAddress(params.keyAlias),
      seller: params.sellerAddress,
      transaction: settleResp.transaction ?? "",
      amountAtomic,
      amountUsdc: params.amountUsdc,
      network: params.network
    };
  }

  private async settleWithRetry(
    payload: Parameters<NanopaymentClient["settle"]>[0],
    requirements: Parameters<NanopaymentClient["settle"]>[1]
  ) {
    let lastError: unknown = null;
    for (let attempt = 0; attempt <= this.retryAttempts; attempt += 1) {
      try {
        return await this.client.settle(payload, requirements);
      } catch (error) {
        lastError = error;
        if (attempt >= this.retryAttempts) {
          break;
        }
        const delay = this.retryBaseDelayMs * 2 ** attempt;
        await sleep(delay);
      }
    }
    throw lastError;
  }
}

function parsePaymentRequirements(base64Header: string): PaymentRequirements {
  try {
    const raw = Buffer.from(base64Header, "base64").toString("utf8");
    const parsed = JSON.parse(raw) as PaymentRequirements;
    if (!Array.isArray(parsed.accepts) || parsed.accepts.length === 0) {
      throw new InvalidPaymentRequirementsError("No accepted payment kinds in 402 requirements");
    }
    for (const kind of parsed.accepts) {
      validatePaymentRequirementKind(kind);
    }
    return parsed;
  } catch (error) {
    if (error instanceof InvalidPaymentRequirementsError) {
      throw error;
    }
    throw new InvalidPaymentRequirementsError("Invalid PAYMENT-REQUIRED header payload");
  }
}

function validatePaymentRequirementKind(kind: PaymentRequirementsKind): void {
  if (!kind.scheme || !kind.network || !kind.amount || !kind.payTo) {
    throw new InvalidPaymentRequirementsError("Payment requirement kind is missing required fields");
  }
  if (kind.extra?.name === CIRCLE_BATCHING_NAME && !kind.extra.verifyingContract) {
    throw new InvalidPaymentRequirementsError(
      "GatewayWalletBatched requirement must include verifyingContract"
    );
  }
}

function assertCaip2Network(network: string): void {
  if (!/^eip155:\d+$/.test(network)) {
    throw new InvalidPaymentRequirementsError("network must be in CAIP-2 format eip155:<chainId>");
  }
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
