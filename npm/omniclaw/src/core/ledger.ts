export type LedgerEntryStatus = "pending" | "confirmed" | "failed" | "cancelled";

export interface LedgerEntry {
  id: string;
  walletId: string;
  recipient: string;
  amount: string;
  currency: string;
  status: LedgerEntryStatus;
  createdAt: string;
  metadata?: Record<string, unknown>;
}

export class Ledger {
  private readonly entries = new Map<string, LedgerEntry>();

  create(entry: Omit<LedgerEntry, "createdAt">): LedgerEntry {
    const full: LedgerEntry = { ...entry, createdAt: new Date().toISOString() };
    this.entries.set(full.id, full);
    return full;
  }

  updateStatus(id: string, status: LedgerEntryStatus): LedgerEntry | null {
    const current = this.entries.get(id);
    if (!current) {
      return null;
    }
    const updated: LedgerEntry = { ...current, status };
    this.entries.set(id, updated);
    return updated;
  }

  get(id: string): LedgerEntry | null {
    return this.entries.get(id) ?? null;
  }

  list(): LedgerEntry[] {
    return [...this.entries.values()];
  }
}
