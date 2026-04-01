import type { SimulatePaymentParams, SimulatePaymentResult } from "./types.js";

import { ConfigurationError } from "./errors.js";

function toMoneyNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new ConfigurationError("amount must be a positive decimal string");
  }
  return parsed;
}

function toFixed(value: number): string {
  return value.toFixed(6);
}

export function simulatePaymentLocally(
  params: SimulatePaymentParams,
  sourceWalletId: string,
  defaultCurrency: string,
  defaultFeeRatePercent: number
): SimulatePaymentResult {
  const amountNumber = toMoneyNumber(params.amount);
  const feeRatePercent = params.feeRatePercent ?? defaultFeeRatePercent;
  const currency = params.currency ?? defaultCurrency;
  const fees = amountNumber * (feeRatePercent / 100);
  const netTransfer = amountNumber - fees;
  const finalSourceWalletId = params.sourceWalletId ?? sourceWalletId;

  return {
    estimatedFees: toFixed(fees),
    netTransfer: toFixed(Math.max(0, netTransfer)),
    transferConfirmationPreview: {
      amount: params.amount,
      currency,
      sourceWalletId: finalSourceWalletId,
      destinationAddress: params.destinationAddress
    },
    readyToExecute: netTransfer > 0
  };
}
