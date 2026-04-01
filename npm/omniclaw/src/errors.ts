export class OmniClawError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OmniClawError";
  }
}

export class ConfigurationError extends OmniClawError {
  constructor(message: string) {
    super(message);
    this.name = "ConfigurationError";
  }
}

export class CircleApiError extends OmniClawError {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "CircleApiError";
    this.status = status;
    this.payload = payload;
  }
}
