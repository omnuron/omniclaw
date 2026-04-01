import { CircleGatewayFacilitator, type BaseFacilitator } from "./facilitator.js";
import type { SettleResult, VerifyResult } from "./types.js";

class GenericHttpFacilitator implements BaseFacilitator {
  readonly name: string;
  readonly environment: "testnet" | "mainnet";
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: {
    name: string;
    environment?: "testnet" | "mainnet";
    baseUrl: string;
    apiKey: string;
    fetchImpl?: typeof fetch;
  }) {
    this.name = options.name;
    this.environment = options.environment ?? "testnet";
    this.baseUrl = options.baseUrl;
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async verify(paymentPayload: unknown, paymentRequirements: unknown): Promise<VerifyResult> {
    const payload = await this.request("/v2/x402/verify", { paymentPayload, paymentRequirements });
    return {
      isValid: Boolean(payload.isValid),
      payer: asOptionalString(payload.payer),
      invalidReason: asOptionalString(payload.invalidReason)
    };
  }

  async settle(paymentPayload: unknown, paymentRequirements: unknown): Promise<SettleResult> {
    const payload = await this.request("/v2/x402/settle", { paymentPayload, paymentRequirements });
    return {
      success: Boolean(payload.success),
      transaction: asOptionalString(payload.transaction),
      network: asOptionalString(payload.network),
      payer: asOptionalString(payload.payer),
      errorReason: asOptionalString(payload.errorReason)
    };
  }

  async getSupportedNetworks(): Promise<Array<Record<string, unknown>>> {
    const response = await this.fetchImpl(`${this.baseUrl}/v2/x402/supported`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        Accept: "application/json"
      }
    });
    const text = await response.text();
    const parsed = text ? safeJsonParse(text) : {};
    if (!response.ok) {
      throw new Error(`Failed to fetch supported networks for facilitator ${this.name}`);
    }
    if (Array.isArray(parsed)) {
      return parsed as Array<Record<string, unknown>>;
    }
    if (isRecord(parsed) && Array.isArray(parsed.kinds)) {
      return parsed.kinds as Array<Record<string, unknown>>;
    }
    if (isRecord(parsed) && Array.isArray(parsed.networks)) {
      return parsed.networks as Array<Record<string, unknown>>;
    }
    return [];
  }

  private async request(endpoint: string, body: unknown): Promise<Record<string, unknown>> {
    const response = await this.fetchImpl(`${this.baseUrl}${endpoint}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    });
    const text = await response.text();
    const parsed = text ? safeJsonParse(text) : {};
    if (!response.ok) {
      return { success: false, errorReason: `HTTP ${response.status}` };
    }
    return parsed as Record<string, unknown>;
  }
}

const DEFAULT_BASE_URLS: Record<string, string> = {
  coinbase: "https://api.cdp.coinbase.com/platform",
  ordern: "https://gateway.ordern.ai",
  rbx: "https://x402.rbx.com",
  thirdweb: "https://x402.thirdweb.com"
};

export const SUPPORTED_FACILITATORS = [
  "circle",
  "coinbase",
  "ordern",
  "rbx",
  "thirdweb"
] as const;

export type FacilitatorName = (typeof SUPPORTED_FACILITATORS)[number];

export function createFacilitator(options: {
  provider: FacilitatorName;
  apiKey: string;
  environment?: "testnet" | "mainnet";
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}): BaseFacilitator {
  if (options.provider === "circle") {
    return new CircleGatewayFacilitator({
      circleApiKey: options.apiKey,
      environment: options.environment,
      baseUrl: options.baseUrl,
      fetchImpl: options.fetchImpl
    });
  }
  return new GenericHttpFacilitator({
    name: options.provider,
    apiKey: options.apiKey,
    environment: options.environment,
    baseUrl: options.baseUrl ?? DEFAULT_BASE_URLS[options.provider],
    fetchImpl: options.fetchImpl
  });
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return { raw: value };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
