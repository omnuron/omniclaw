import type { SettleResult, VerifyResult } from "./types.js";

export interface BaseFacilitator {
  readonly name: string;
  readonly environment: "testnet" | "mainnet";
  verify(paymentPayload: unknown, paymentRequirements: unknown): Promise<VerifyResult>;
  settle(paymentPayload: unknown, paymentRequirements: unknown): Promise<SettleResult>;
  getSupportedNetworks(): Promise<Array<Record<string, unknown>>>;
}

export class CircleGatewayFacilitator implements BaseFacilitator {
  readonly name = "circle";
  readonly environment: "testnet" | "mainnet";
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly headers: Record<string, string>;

  constructor(options: {
    circleApiKey: string;
    environment?: "testnet" | "mainnet";
    baseUrl?: string;
    fetchImpl?: typeof fetch;
  }) {
    this.environment = options.environment ?? "testnet";
    this.baseUrl =
      options.baseUrl ??
      (this.environment === "mainnet"
        ? "https://gateway-api.circle.com"
        : "https://gateway-api-testnet.circle.com");
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.headers = {
      Authorization: `Bearer ${options.circleApiKey}`,
      "Content-Type": "application/json"
    };
  }

  async verify(paymentPayload: unknown, paymentRequirements: unknown): Promise<VerifyResult> {
    const payload = await this.request<{ isValid?: boolean; payer?: string; invalidReason?: string }>(
      "/v1/x402/verify",
      {
        paymentPayload,
        paymentRequirements
      }
    );
    return {
      isValid: payload.isValid ?? false,
      payer: payload.payer,
      invalidReason: payload.invalidReason
    };
  }

  async settle(paymentPayload: unknown, paymentRequirements: unknown): Promise<SettleResult> {
    const payload = await this.request<{
      success?: boolean;
      transaction?: string;
      network?: string;
      payer?: string;
      errorReason?: string;
    }>("/v1/x402/settle", {
      paymentPayload,
      paymentRequirements
    });
    return {
      success: payload.success ?? false,
      transaction: payload.transaction,
      network: payload.network,
      payer: payload.payer,
      errorReason: payload.errorReason
    };
  }

  async getSupportedNetworks(): Promise<Array<Record<string, unknown>>> {
    const payload = await this.request<{ kinds?: Array<Record<string, unknown>> }>(
      "/v1/x402/supported",
      undefined,
      "GET"
    );
    return payload.kinds ?? [];
  }

  private async request<T>(
    endpoint: string,
    body?: unknown,
    method: "GET" | "POST" = "POST"
  ): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${endpoint}`, {
      method,
      headers: this.headers,
      body: body ? JSON.stringify(body) : undefined
    });
    const text = await response.text();
    const parsed = text ? safeJsonParse(text) : {};
    if (!response.ok) {
      throw new Error(`Facilitator ${this.name} request failed (${response.status}): ${endpoint}`);
    }
    return parsed as T;
  }
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return { raw: value };
  }
}
