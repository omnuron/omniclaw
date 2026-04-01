import { createHash, randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { verifyTypedData } from "ethers";

import { assertEvmAddress, assertPositiveDecimal } from "../core/validation.js";
import { CIRCLE_BATCHING_NAME } from "../protocols/nanopayments/constants.js";
import type { BaseFacilitator } from "./facilitator.js";
import type {
  EndpointConfig,
  PaymentRecord,
  PaymentScheme,
  SellerConfig,
  SettleResult,
  VerifyResult
} from "./types.js";

interface ParsedPaymentSignature {
  x402Version: number;
  scheme: string;
  network: string;
  payload: {
    authorization: {
      from: string;
      to: string;
      value: string;
      validAfter: string;
      validBefore: string;
      nonce: string;
    };
    signature: string;
  };
}

export class Seller {
  private readonly config: SellerConfig;
  private readonly endpoints = new Map<string, EndpointConfig>();
  private readonly payments = new Map<string, PaymentRecord>();
  private readonly usedNonces = new Set<string>();
  private readonly facilitator?: BaseFacilitator;

  constructor(config: SellerConfig, facilitator?: BaseFacilitator) {
    assertEvmAddress(config.sellerAddress, "sellerAddress");
    this.config = { ...config };
    this.facilitator = facilitator;
    this.loadNonceStore();
  }

  addEndpoint(endpoint: EndpointConfig): void {
    assertPositiveDecimal(endpoint.priceUsd, "priceUsd");
    this.endpoints.set(endpoint.path, {
      ...endpoint,
      schemes: endpoint.schemes ?? ["exact", "GatewayWalletBatched"]
    });
  }

  buildPaymentRequired(path: string): { status: number; body: Record<string, unknown> } {
    const endpoint = this.endpoints.get(path);
    if (!endpoint) {
      throw new Error(`Endpoint not configured: ${path}`);
    }
    const amountAtomic = toAtomic(endpoint.priceUsd);
    const accepts = (endpoint.schemes ?? ["exact", "GatewayWalletBatched"]).map((scheme) => {
      if (scheme === "GatewayWalletBatched") {
        if (this.config.strictGatewayContract && !this.config.gatewayContract) {
          throw new Error(
            "GatewayWalletBatched enabled but gatewayContract missing in strict mode"
          );
        }
      }
      return {
        scheme: "exact",
        network: this.config.network,
        asset: this.config.usdcContract,
        amount: amountAtomic,
        payTo: this.config.sellerAddress,
        maxTimeoutSeconds: 345600,
        extra:
          scheme === "GatewayWalletBatched"
            ? {
                name: CIRCLE_BATCHING_NAME,
                version: "1",
                verifyingContract: this.config.gatewayContract ?? ""
              }
            : { name: "USDC", version: "2" }
      };
    });
    return { status: 402, body: { x402Version: 2, accepts } };
  }

  async verifyPayment(input: {
    paymentSignatureHeader: string;
    paymentRequiredBody: Record<string, unknown>;
  }): Promise<VerifyResult> {
    const signaturePayload = parsePaymentSignature(input.paymentSignatureHeader);
    const accepted = findAcceptedKind(input.paymentRequiredBody, signaturePayload);
    if (!accepted) {
      return { isValid: false, invalidReason: "no matching accepted payment scheme" };
    }
    if (signaturePayload.payload.authorization.to.toLowerCase() !== this.config.sellerAddress.toLowerCase()) {
      return { isValid: false, invalidReason: "payTo does not match seller address" };
    }
    if (signaturePayload.payload.authorization.value !== String(accepted.amount)) {
      return { isValid: false, invalidReason: "amount mismatch" };
    }

    const nonceKey = nonceFingerprint(signaturePayload.payload.authorization);
    if (this.usedNonces.has(nonceKey)) {
      return { isValid: false, invalidReason: "nonce already used" };
    }

    const recovered = verifyTypedData(
      {
        name: accepted.extra?.name || "USDC",
        version: accepted.extra?.version || "2",
        chainId: parseChainId(signaturePayload.network),
        verifyingContract: accepted.extra?.verifyingContract || this.config.usdcContract
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
      signaturePayload.payload.authorization,
      signaturePayload.payload.signature
    );

    if (
      recovered.toLowerCase() !== signaturePayload.payload.authorization.from.toLowerCase()
    ) {
      return { isValid: false, invalidReason: "signature recovery mismatch" };
    }

    this.usedNonces.add(nonceKey);
    this.persistNonceStore();
    return { isValid: true, payer: recovered };
  }

  async settlePayment(input: {
    paymentSignatureHeader: string;
    paymentRequiredBody: Record<string, unknown>;
    endpointPath: string;
  }): Promise<SettleResult> {
    const parsed = parsePaymentSignature(input.paymentSignatureHeader);
    const verification = await this.verifyPayment({
      paymentSignatureHeader: input.paymentSignatureHeader,
      paymentRequiredBody: input.paymentRequiredBody
    });
    if (!verification.isValid) {
      return { success: false, errorReason: verification.invalidReason };
    }

    let settlement: SettleResult = {
      success: true,
      transaction: randomUUID(),
      network: parsed.network,
      payer: verification.payer
    };
    if (this.facilitator) {
      settlement = await this.facilitator.settle(parsed, input.paymentRequiredBody);
    }

    const accepted = findAcceptedKind(input.paymentRequiredBody, parsed);
    const amountAtomic = String(accepted?.amount ?? "0");
    const record: PaymentRecord = {
      id: settlement.transaction ?? randomUUID(),
      endpointPath: input.endpointPath,
      scheme: accepted?.extra?.name === CIRCLE_BATCHING_NAME ? "GatewayWalletBatched" : "exact",
      buyerAddress: verification.payer ?? parsed.payload.authorization.from,
      sellerAddress: this.config.sellerAddress,
      amountAtomic,
      amountUsd: fromAtomic(amountAtomic),
      status: settlement.success ? "settled" : "failed",
      createdAt: new Date().toISOString(),
      transaction: settlement.transaction
    };
    this.payments.set(record.id, record);
    return settlement;
  }

  listPayments(): PaymentRecord[] {
    return [...this.payments.values()];
  }

  private loadNonceStore(): void {
    if (!this.config.nonceStorePath) return;
    try {
      const raw = readFileSync(this.config.nonceStorePath, { encoding: "utf8" });
      const parsed = JSON.parse(raw) as string[];
      parsed.forEach((value) => this.usedNonces.add(value));
    } catch {
      // no-op on first run
    }
  }

  private persistNonceStore(): void {
    if (!this.config.nonceStorePath) return;
    writeFileSync(this.config.nonceStorePath, JSON.stringify([...this.usedNonces]), {
      encoding: "utf8"
    });
  }
}

export function createSeller(config: SellerConfig, facilitator?: BaseFacilitator): Seller {
  return new Seller(config, facilitator);
}

function parsePaymentSignature(header: string): ParsedPaymentSignature {
  const raw = Buffer.from(header, "base64").toString("utf8");
  return JSON.parse(raw) as ParsedPaymentSignature;
}

function parseChainId(network: string): number {
  const parts = network.split(":");
  return Number.parseInt(parts[1] ?? "0", 10);
}

function toAtomic(priceUsd: string): string {
  const amount = Number.parseFloat(priceUsd.replace("$", ""));
  return Math.round(amount * 1_000_000).toString();
}

function fromAtomic(amountAtomic: string): string {
  return (Number.parseInt(amountAtomic, 10) / 1_000_000).toString();
}

function nonceFingerprint(auth: ParsedPaymentSignature["payload"]["authorization"]): string {
  return createHash("sha256")
    .update(`${auth.from}|${auth.to}|${auth.value}|${auth.nonce}|${auth.validBefore}`)
    .digest("hex");
}

function findAcceptedKind(
  paymentRequiredBody: Record<string, unknown>,
  parsed: ParsedPaymentSignature
):
  | {
      scheme: string;
      network: string;
      amount: string;
      payTo: string;
      extra?: { name?: string; version?: string; verifyingContract?: string };
    }
  | undefined {
  const accepts = Array.isArray(paymentRequiredBody.accepts) ? paymentRequiredBody.accepts : [];
  return accepts.find((accept) => {
    if (typeof accept !== "object" || accept === null) {
      return false;
    }
    const record = accept as Record<string, unknown>;
    return record.network === parsed.network && record.scheme === parsed.scheme;
  }) as
    | {
        scheme: string;
        network: string;
        amount: string;
        payTo: string;
        extra?: { name?: string; version?: string; verifyingContract?: string };
      }
    | undefined;
}
