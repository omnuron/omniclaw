import { ConfigurationError } from "../errors.js";

const EVM_ADDRESS_REGEX = /^0x[a-fA-F0-9]{40}$/;
const WALLET_ID_REGEX = /^[a-zA-Z0-9-]{3,128}$/;

export function assertPositiveDecimal(value: string, fieldName: string): void {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new ConfigurationError(`${fieldName} must be a positive decimal string`);
  }
}

export function assertEvmAddress(value: string, fieldName: string): void {
  if (!EVM_ADDRESS_REGEX.test(value)) {
    throw new ConfigurationError(`${fieldName} must be a valid EVM address`);
  }
}

export function assertWalletId(value: string, fieldName: string): void {
  if (!WALLET_ID_REGEX.test(value)) {
    throw new ConfigurationError(`${fieldName} is invalid`);
  }
}

export function assertHttpsUrl(value: string, fieldName: string): void {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new ConfigurationError(`${fieldName} must be a valid URL`);
  }
  if (parsed.protocol !== "https:") {
    throw new ConfigurationError(`${fieldName} must use https`);
  }
}
