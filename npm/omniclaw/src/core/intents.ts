import { randomUUID } from "node:crypto";

export type PaymentIntentStatus =
  | "pending"
  | "requires_review"
  | "confirmed"
  | "cancelled"
  | "failed";

export interface PaymentIntentRecord {
  id: string;
  walletId: string;
  recipient: string;
  amount: string;
  currency: string;
  status: PaymentIntentStatus;
  idempotencyKey: string;
  createdAt: string;
}

export class PaymentIntentService {
  private readonly intents = new Map<string, PaymentIntentRecord>();
  private readonly byIdempotency = new Map<string, string>();

  createIntent(input: {
    walletId: string;
    recipient: string;
    amount: string;
    currency: string;
    idempotencyKey: string;
    requiresReview?: boolean;
  }): PaymentIntentRecord {
    const existingId = this.byIdempotency.get(input.idempotencyKey);
    if (existingId) {
      const existing = this.intents.get(existingId);
      if (existing) {
        return existing;
      }
    }

    const intent: PaymentIntentRecord = {
      id: randomUUID(),
      walletId: input.walletId,
      recipient: input.recipient,
      amount: input.amount,
      currency: input.currency,
      status: input.requiresReview ? "requires_review" : "pending",
      idempotencyKey: input.idempotencyKey,
      createdAt: new Date().toISOString()
    };
    this.intents.set(intent.id, intent);
    this.byIdempotency.set(intent.idempotencyKey, intent.id);
    return intent;
  }

  getIntent(intentId: string): PaymentIntentRecord | null {
    return this.intents.get(intentId) ?? null;
  }

  updateStatus(intentId: string, status: PaymentIntentStatus): PaymentIntentRecord | null {
    const intent = this.intents.get(intentId);
    if (!intent) {
      return null;
    }
    const next = { ...intent, status };
    this.intents.set(intentId, next);
    return next;
  }
}
