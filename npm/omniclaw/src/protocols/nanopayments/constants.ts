export const GATEWAY_API_TESTNET = "https://gateway-api-testnet.circle.com";
export const GATEWAY_API_MAINNET = "https://gateway-api.circle.com";

export const GATEWAY_X402_SUPPORTED_PATH = "/v1/x402/supported";
export const GATEWAY_X402_SETTLE_PATH = "/v1/x402/settle";
export const GATEWAY_X402_VERIFY_PATH = "/v1/x402/verify";
export const GATEWAY_BALANCES_PATH = "/v1/balances";

export const CIRCLE_BATCHING_NAME = "GatewayWalletBatched";
export const CIRCLE_BATCHING_VERSION = "1";
export const CIRCLE_BATCHING_SCHEME = "exact";
export const X402_VERSION = 2;
export const DEFAULT_VALID_BEFORE_SECONDS = 345600;
export const MIN_VALID_BEFORE_SECONDS = 259200;
export const DEFAULT_MICRO_PAYMENT_THRESHOLD_USDC = "1.00";

export const CIRCLE_DOMAIN_TO_CAIP2: Record<number, string> = {
  0: "eip155:1",
  1: "eip155:43114",
  2: "eip155:10",
  3: "eip155:42161",
  6: "eip155:8453",
  7: "eip155:137",
  26: "eip155:5042002"
};

export const CAIP2_TO_CIRCLE_DOMAIN: Record<string, number> = Object.entries(
  CIRCLE_DOMAIN_TO_CAIP2
).reduce<Record<string, number>>((acc, [domain, caip2]) => {
  acc[caip2] = Number(domain);
  return acc;
}, {});

export function parseCaip2ChainId(network: string): number {
  if (!network.includes(":")) return 0;
  const chainId = Number.parseInt(network.split(":")[1] ?? "", 10);
  return Number.isFinite(chainId) ? chainId : 0;
}
