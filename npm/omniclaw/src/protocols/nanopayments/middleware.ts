import { CIRCLE_BATCHING_NAME, X402_VERSION } from "./constants.js";
import type { PaymentRequirements, SupportedKind } from "./types.js";

export function parsePrice(price: string): string {
  const normalized = price.trim().startsWith("$") ? price.trim().slice(1) : price.trim();
  if (normalized.includes(".")) {
    const decimal = Number.parseFloat(normalized);
    return Math.round(decimal * 1_000_000).toString();
  }
  const asInt = Number.parseInt(normalized, 10);
  if (!Number.isFinite(asInt) || asInt <= 0) {
    throw new Error(`Invalid price: ${price}`);
  }
  return asInt >= 1_000_000 ? String(asInt) : String(asInt * 1_000_000);
}

export class GatewayMiddleware {
  constructor(private readonly sellerAddress: string, private readonly supported: SupportedKind[]) {}

  build402Response(price: string): PaymentRequirements {
    const amount = parsePrice(price);
    const accepts = this.supported
      .filter((kind) => kind.extra?.verifyingContract && kind.extra?.usdcAddress)
      .map((kind) => ({
        scheme: "exact",
        network: kind.network,
        asset: kind.extra?.usdcAddress ?? "",
        amount,
        maxTimeoutSeconds: 345600,
        payTo: this.sellerAddress,
        extra: {
          name: CIRCLE_BATCHING_NAME,
          version: "1",
          verifyingContract: kind.extra?.verifyingContract ?? ""
        }
      }));
    return { x402Version: X402_VERSION, accepts };
  }
}
