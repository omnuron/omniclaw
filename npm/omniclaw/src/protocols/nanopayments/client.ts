import {
  CAIP2_TO_CIRCLE_DOMAIN,
  GATEWAY_API_MAINNET,
  GATEWAY_API_TESTNET,
  GATEWAY_BALANCES_PATH,
  GATEWAY_X402_SETTLE_PATH,
  GATEWAY_X402_SUPPORTED_PATH,
  GATEWAY_X402_VERIFY_PATH
} from "./constants.js";
import { GatewayApiError } from "./errors.js";
import type {
  GatewayBalance,
  PaymentPayload,
  PaymentRequirements,
  SettleResponse,
  SupportedKind
} from "./types.js";

export interface NanopaymentClientOptions {
  apiKey: string;
  environment?: "testnet" | "mainnet";
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

export class NanopaymentClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: NanopaymentClientOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl =
      options.baseUrl ??
      (options.environment === "mainnet" ? GATEWAY_API_MAINNET : GATEWAY_API_TESTNET);
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async getSupported(forceRefresh = false): Promise<SupportedKind[]> {
    const suffix = forceRefresh ? `?t=${Date.now()}` : "";
    const payload = await this.request<{ kinds?: SupportedKind[] }>(
      `${GATEWAY_X402_SUPPORTED_PATH}${suffix}`,
      { method: "GET" }
    );
    return payload.kinds ?? [];
  }

  async getBalance(depositor: string, network: string): Promise<GatewayBalance[]> {
    const domain = CAIP2_TO_CIRCLE_DOMAIN[network] ?? 26;
    const payload = await this.request<{ balances?: GatewayBalance[] }>(GATEWAY_BALANCES_PATH, {
      method: "POST",
      body: JSON.stringify({
        token: "USDC",
        sources: [{ domain, depositor }]
      })
    });
    return payload.balances ?? [];
  }

  async settle(payload: PaymentPayload, requirements: PaymentRequirements): Promise<SettleResponse> {
    return this.request<SettleResponse>(GATEWAY_X402_SETTLE_PATH, {
      method: "POST",
      body: JSON.stringify({
        x402Version: payload.x402Version,
        accepted: requirements,
        payload: payload.payload,
        scheme: payload.scheme,
        network: payload.network
      })
    });
  }

  async verify(payload: PaymentPayload, requirements: PaymentRequirements): Promise<SettleResponse> {
    return this.request<SettleResponse>(GATEWAY_X402_VERIFY_PATH, {
      method: "POST",
      body: JSON.stringify({
        x402Version: payload.x402Version,
        accepted: requirements,
        payload: payload.payload,
        scheme: payload.scheme,
        network: payload.network
      })
    });
  }

  private async request<T>(
    endpoint: string,
    init: { method: string; body?: string }
  ): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${endpoint}`, {
      method: init.method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json"
      },
      body: init.body
    });

    const text = await response.text();
    const parsed = text ? safeJsonParse(text) : {};
    if (!response.ok) {
      throw new GatewayApiError(
        `Gateway request failed (${response.status}) for ${endpoint}`,
        response.status,
        parsed
      );
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
