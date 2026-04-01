export type PaymentScheme = "exact" | "GatewayWalletBatched";
export type PaymentStatus = "pending" | "verified" | "settled" | "failed";

export interface EndpointConfig {
  path: string;
  priceUsd: string;
  description?: string;
  schemes?: PaymentScheme[];
}

export interface SellerConfig {
  sellerAddress: string;
  name: string;
  network: string;
  usdcContract: string;
  gatewayContract?: string;
  webhookUrl?: string;
  webhookSecret?: string;
  strictGatewayContract?: boolean;
  nonceStorePath?: string;
}

export interface VerifyResult {
  isValid: boolean;
  payer?: string;
  invalidReason?: string;
}

export interface SettleResult {
  success: boolean;
  transaction?: string;
  network?: string;
  payer?: string;
  errorReason?: string;
}

export interface PaymentRecord {
  id: string;
  endpointPath: string;
  scheme: PaymentScheme;
  buyerAddress: string;
  sellerAddress: string;
  amountAtomic: string;
  amountUsd: string;
  status: PaymentStatus;
  createdAt: string;
  transaction?: string;
}
