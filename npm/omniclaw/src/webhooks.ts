import { verify as verifySignature, createPublicKey } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

import { ConfigurationError } from "./errors.js";

export interface WebhookVerifierOptions {
  verificationKey: string;
  maxReplayAgeSeconds?: number;
  maxFutureSkewSeconds?: number;
  dedupEnabled?: boolean;
  dedupStorePath?: string;
}

export interface VerifiedWebhook {
  notificationId: string;
  notificationType: string;
  createDate?: string;
  payload: Record<string, unknown>;
}

const DEFAULT_MAX_REPLAY_AGE_SECONDS = 43_200;
const DEFAULT_MAX_FUTURE_SKEW_SECONDS = 300;

export class WebhookVerifier {
  private readonly verificationKey: string;
  private readonly maxReplayAgeSeconds: number;
  private readonly maxFutureSkewSeconds: number;
  private readonly dedupEnabled: boolean;
  private readonly dedupStorePath?: string;
  private readonly seenNotificationIds = new Set<string>();

  constructor(options: WebhookVerifierOptions) {
    if (!options.verificationKey) {
      throw new ConfigurationError("verificationKey is required");
    }
    this.verificationKey = options.verificationKey;
    this.maxReplayAgeSeconds = options.maxReplayAgeSeconds ?? DEFAULT_MAX_REPLAY_AGE_SECONDS;
    this.maxFutureSkewSeconds = options.maxFutureSkewSeconds ?? DEFAULT_MAX_FUTURE_SKEW_SECONDS;
    this.dedupEnabled = options.dedupEnabled ?? true;
    this.dedupStorePath = options.dedupStorePath;
    this.loadDedupStore();
  }

  verify(rawBody: string, headers: Record<string, string | undefined>): VerifiedWebhook {
    const signatureHeader = headers["x-circle-signature"] ?? headers["circle-signature"];
    if (!signatureHeader) {
      throw new ConfigurationError("Missing Circle signature header");
    }
    const timestampHeader = headers["x-circle-timestamp"] ?? headers["circle-timestamp"];
    this.verifyTimestamp(timestampHeader);
    this.verifySignature(rawBody, signatureHeader);

    const payload = JSON.parse(rawBody) as Record<string, unknown>;
    const notificationId = stringField(payload, "notificationId");
    const notificationType = stringField(payload, "notificationType");
    if (this.dedupEnabled) {
      if (this.seenNotificationIds.has(notificationId)) {
        throw new ConfigurationError(`Duplicate webhook notificationId: ${notificationId}`);
      }
      this.seenNotificationIds.add(notificationId);
      this.persistDedupStore();
    }

    return {
      notificationId,
      notificationType,
      createDate: stringOptionalField(payload, "createDate"),
      payload
    };
  }

  private verifyTimestamp(timestamp?: string): void {
    if (!timestamp) {
      return;
    }
    const ts = Number.parseInt(timestamp, 10);
    if (!Number.isFinite(ts)) {
      throw new ConfigurationError("Invalid webhook timestamp header");
    }
    const now = Math.floor(Date.now() / 1000);
    if (now - ts > this.maxReplayAgeSeconds) {
      throw new ConfigurationError("Webhook timestamp is too old");
    }
    if (ts - now > this.maxFutureSkewSeconds) {
      throw new ConfigurationError("Webhook timestamp is too far in the future");
    }
  }

  private verifySignature(rawBody: string, signatureHeader: string): void {
    const sigBuffer = parseSignature(signatureHeader);
    const key = createPublicKey(this.verificationKey);

    let valid = false;
    try {
      valid = verifySignature(null, Buffer.from(rawBody, "utf8"), key, sigBuffer);
    } catch {
      try {
        valid = verifySignature("sha256", Buffer.from(rawBody, "utf8"), key, sigBuffer);
      } catch {
        valid = false;
      }
    }
    if (!valid) {
      throw new ConfigurationError("Invalid webhook signature");
    }
  }

  private loadDedupStore(): void {
    if (!this.dedupStorePath) {
      return;
    }
    try {
      const raw = readFileSync(this.dedupStorePath, { encoding: "utf8" });
      const parsed = JSON.parse(raw) as string[];
      for (const id of parsed) {
        if (typeof id === "string" && id.length > 0) {
          this.seenNotificationIds.add(id);
        }
      }
    } catch {
      // no-op on first run
    }
  }

  private persistDedupStore(): void {
    if (!this.dedupStorePath) {
      return;
    }
    writeFileSync(this.dedupStorePath, JSON.stringify([...this.seenNotificationIds]), {
      encoding: "utf8"
    });
  }
}

function parseSignature(value: string): Buffer {
  const trimmed = value.trim();
  if (/^[0-9a-fA-F]+$/.test(trimmed)) {
    return Buffer.from(trimmed, "hex");
  }
  return Buffer.from(trimmed, "base64");
}

function stringField(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new ConfigurationError(`Missing required webhook field: ${key}`);
  }
  return value;
}

function stringOptionalField(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
