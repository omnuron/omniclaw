export type TrustVerdict = "allow" | "hold" | "block";

export interface TrustCheckResult {
  verdict: TrustVerdict;
  reason?: string;
  score?: number;
}

export type TrustEvaluator = (recipient: string) => Promise<TrustCheckResult>;

export class TrustGate {
  constructor(private readonly evaluator?: TrustEvaluator) {}

  async check(recipient: string): Promise<TrustCheckResult> {
    if (!this.evaluator) {
      return { verdict: "allow", reason: "trust evaluator not configured" };
    }
    return this.evaluator(recipient);
  }

  isConfigured(): boolean {
    return Boolean(this.evaluator);
  }
}
