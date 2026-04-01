import type { TrustCheckResult, TrustEvaluator } from "./core/trust.js";
import type { NanopaymentResult } from "./protocols/nanopayments/types.js";

export interface OmniClawConfig {
  circleApiKey?: string;
  circleWalletId?: string;
  circleApiBaseUrl?: string;
  defaultCurrency?: string;
  defaultFeeRatePercent?: number;
  nanopaymentsEnabled?: boolean;
  nanopaymentsEnvironment?: "testnet" | "mainnet";
  gatewayApiBaseUrl?: string;
  entitySecret?: string;
  nanopaymentKeyStorePath?: string;
  strictSettlement?: boolean;
  retryAttempts?: number;
  retryBaseDelayMs?: number;
  circuitBreakerFailureThreshold?: number;
  circuitBreakerRecoveryMs?: number;
  requireTrustGate?: boolean;
  trustEvaluator?: TrustEvaluator;
  fetchImpl?: typeof fetch;
}

export interface Amount {
  amount: string;
  currency: string;
}

export interface CreatePaymentParams {
  amount: string;
  currency?: string;
  sourceWalletId?: string;
  destinationAddress: string;
  idempotencyKey?: string;
  purpose?: string;
  skipGuards?: boolean;
  checkTrust?: boolean;
  confirm?: boolean;
}

export interface CirclePaymentResponse {
  data?: {
    id?: string;
    status?: string;
    createDate?: string;
    updateDate?: string;
    amount?: Amount;
    source?: { type?: string; id?: string };
    destination?: { type?: string; address?: string };
  };
  [key: string]: unknown;
}

export interface CircleWalletResponse {
  data?: {
    walletId?: string;
    id?: string;
    balances?: Array<{ amount?: string; currency?: string }>;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface SimulatePaymentParams {
  amount: string;
  currency?: string;
  sourceWalletId?: string;
  destinationAddress: string;
  feeRatePercent?: number;
}

export interface SimulatePaymentResult {
  estimatedFees: string;
  netTransfer: string;
  transferConfirmationPreview: {
    amount: string;
    currency: string;
    sourceWalletId: string;
    destinationAddress: string;
  };
  readyToExecute: boolean;
}

export interface CreatePaymentIntentParams {
  amount: string;
  currency?: string;
  settlementCurrency?: string;
  paymentMethods?: string[];
  sourceWalletId?: string;
  recipient?: string;
  checkTrust?: boolean;
  confirm?: boolean;
  idempotencyKey?: string;
}

export interface CirclePaymentIntentResponse {
  data?: {
    id?: string;
    status?: string;
    amount?: Amount;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface RoutedPaymentParams {
  walletId?: string;
  recipient: string;
  amount: string;
  currency?: string;
  purpose?: string;
  checkTrust?: boolean;
  skipGuards?: boolean;
  confirm?: boolean;
  nanoKeyAlias?: string;
  network?: string;
}

export interface RoutedPaymentResult {
  route: "circle_transfer" | "x402_nanopayment" | "direct_nanopayment";
  success: boolean;
  trust?: TrustCheckResult;
  simulation?: SimulatePaymentResult;
  ledgerEntryId: string;
  result: CirclePaymentResponse | NanopaymentResult;
}
