import { createHash } from "node:crypto";

export function deriveIdempotencyKey(parts: Array<string | number | undefined | null>): string {
  const normalized = parts
    .map((part) => String(part ?? "").trim().toLowerCase())
    .join("|");
  return createHash("sha256").update(normalized).digest("hex");
}
