export interface PaymentRequirementsExtra {
  name: string;
  version: string;
  verifyingContract: string;
}

export interface PaymentRequirementsKind {
  scheme: string;
  network: string;
  asset: string;
  amount: string;
  maxTimeoutSeconds: number;
  payTo: string;
  extra: PaymentRequirementsExtra;
}

export interface PaymentRequirements {
  x402Version: number;
  accepts: PaymentRequirementsKind[];
}

export interface EIP3009Authorization {
  from: string;
  to: string;
  value: string;
  validAfter: string;
  validBefore: string;
  nonce: string;
}

export interface PaymentPayloadInner {
  authorization: EIP3009Authorization;
  signature: string;
}

export interface PaymentPayload {
  x402Version: number;
  scheme: string;
  network: string;
  payload: PaymentPayloadInner;
}

export interface SupportedKind {
  x402Version: number;
  scheme: string;
  network: string;
  extra?: {
    verifyingContract?: string;
    usdcAddress?: string;
    [key: string]: unknown;
  };
}

export interface SettleResponse {
  success: boolean;
  transaction?: string;
  payer?: string;
  network?: string;
  [key: string]: unknown;
}

export interface GatewayBalance {
  amount: string;
  token: string;
  network?: string;
}

export interface NanopaymentResult {
  success: boolean;
  isNanopayment: boolean;
  payer: string;
  seller: string;
  transaction: string;
  amountAtomic: string;
  amountUsdc: string;
  network: string;
  responseStatus?: number;
  responseData?: string;
}

export interface PayX402UrlParams {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  keyAlias?: string;
}

export interface NanopaymentAdapterOptions {
  strictSettlement?: boolean;
  retryAttempts?: number;
  retryBaseDelayMs?: number;
  circuitBreakerFailureThreshold?: number;
  circuitBreakerRecoveryMs?: number;
}
