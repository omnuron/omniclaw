export class NanopaymentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NanopaymentError";
  }
}

export class UnsupportedSchemeError extends NanopaymentError {
  constructor(message = "GatewayWalletBatched scheme not found in payment requirements") {
    super(message);
    this.name = "UnsupportedSchemeError";
  }
}

export class GatewayApiError extends NanopaymentError {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "GatewayApiError";
    this.status = status;
    this.payload = payload;
  }
}

export class KeyNotFoundError extends NanopaymentError {
  constructor(alias: string) {
    super(`No nanopayment key found for alias: ${alias}`);
    this.name = "KeyNotFoundError";
  }
}

export class NoDefaultKeyError extends NanopaymentError {
  constructor() {
    super("No default nanopayment key is set");
    this.name = "NoDefaultKeyError";
  }
}

export class CircuitOpenError extends NanopaymentError {
  constructor() {
    super("Nanopayment circuit is open; retry later");
    this.name = "CircuitOpenError";
  }
}

export class InvalidPaymentRequirementsError extends NanopaymentError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidPaymentRequirementsError";
  }
}
