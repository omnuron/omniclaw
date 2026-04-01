import { ConfigurationError } from "../errors.js";

export interface PaymentContext {
  walletId: string;
  recipient: string;
  amount: string;
  currency: string;
  purpose?: string;
  confirm?: boolean;
}

export interface GuardResult {
  allowed: boolean;
  reason?: string;
}

export interface Guard {
  readonly name: string;
  evaluate(context: PaymentContext): Promise<GuardResult> | GuardResult;
}

export class BudgetGuard implements Guard {
  readonly name = "budget";
  private spent = 0;

  constructor(private readonly maxBudget: number) {}

  evaluate(context: PaymentContext): GuardResult {
    const amount = Number.parseFloat(context.amount);
    if (this.spent + amount > this.maxBudget) {
      return { allowed: false, reason: `budget exceeded (${this.maxBudget})` };
    }
    this.spent += amount;
    return { allowed: true };
  }
}

export class SingleTxGuard implements Guard {
  readonly name = "single_tx";

  constructor(private readonly maxAmount: number) {}

  evaluate(context: PaymentContext): GuardResult {
    const amount = Number.parseFloat(context.amount);
    return amount <= this.maxAmount
      ? { allowed: true }
      : { allowed: false, reason: `single transaction limit exceeded (${this.maxAmount})` };
  }
}

export class RateLimitGuard implements Guard {
  readonly name = "rate_limit";
  private calls: number[] = [];

  constructor(
    private readonly maxCalls: number,
    private readonly windowMs: number
  ) {}

  evaluate(): GuardResult {
    const now = Date.now();
    this.calls = this.calls.filter((ts) => now - ts <= this.windowMs);
    if (this.calls.length >= this.maxCalls) {
      return { allowed: false, reason: "rate limit exceeded" };
    }
    this.calls.push(now);
    return { allowed: true };
  }
}

export class RecipientGuard implements Guard {
  readonly name = "recipient";
  private readonly whitelist = new Set<string>();

  constructor(recipients: string[]) {
    recipients.forEach((recipient) => this.whitelist.add(recipient.toLowerCase()));
  }

  evaluate(context: PaymentContext): GuardResult {
    if (this.whitelist.size === 0) {
      return { allowed: true };
    }
    return this.whitelist.has(context.recipient.toLowerCase())
      ? { allowed: true }
      : { allowed: false, reason: "recipient is not whitelisted" };
  }
}

export class ConfirmGuard implements Guard {
  readonly name = "confirm";

  constructor(private readonly threshold: number) {}

  evaluate(context: PaymentContext): GuardResult {
    const amount = Number.parseFloat(context.amount);
    if (amount < this.threshold) {
      return { allowed: true };
    }
    return context.confirm
      ? { allowed: true }
      : { allowed: false, reason: `confirmation required for amount >= ${this.threshold}` };
  }
}

export class GuardManager {
  private readonly guardsByWallet = new Map<string, Guard[]>();

  addGuard(walletId: string, guard: Guard): void {
    const existing = this.guardsByWallet.get(walletId) ?? [];
    existing.push(guard);
    this.guardsByWallet.set(walletId, existing);
  }

  listGuards(walletId: string): string[] {
    return (this.guardsByWallet.get(walletId) ?? []).map((guard) => guard.name);
  }

  async evaluate(walletId: string, context: PaymentContext, skipGuards = false): Promise<void> {
    if (skipGuards) {
      return;
    }
    const guards = this.guardsByWallet.get(walletId) ?? [];
    for (const guard of guards) {
      const result = await guard.evaluate(context);
      if (!result.allowed) {
        throw new ConfigurationError(result.reason ?? `Guard ${guard.name} blocked payment`);
      }
    }
  }
}
