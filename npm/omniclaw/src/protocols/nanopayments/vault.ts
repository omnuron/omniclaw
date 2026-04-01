import { readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { Wallet } from "ethers";

import {
  CIRCLE_BATCHING_NAME,
  CIRCLE_BATCHING_SCHEME,
  CIRCLE_BATCHING_VERSION,
  DEFAULT_VALID_BEFORE_SECONDS,
  X402_VERSION,
  parseCaip2ChainId,
  MIN_VALID_BEFORE_SECONDS
} from "./constants.js";
import {
  InvalidPaymentRequirementsError,
  KeyNotFoundError,
  NoDefaultKeyError
} from "./errors.js";
import { decryptPrivateKey, encryptPrivateKey } from "./crypto.js";
import type { PaymentPayload, PaymentRequirementsKind } from "./types.js";

interface StoredKey {
  encryptedPrivateKey: ReturnType<typeof encryptPrivateKey>;
  address: string;
}

interface PersistedState {
  defaultAlias: string | null;
  keys: Record<string, StoredKey>;
}

export interface NanoKeyVaultOptions {
  entitySecret: string;
  keyStorePath?: string;
}

export class NanoKeyVault {
  private readonly keyStore = new Map<string, StoredKey>();
  private readonly entitySecret: string;
  private readonly keyStorePath?: string;
  private defaultAlias: string | null = null;

  constructor(options: NanoKeyVaultOptions) {
    if (!options.entitySecret || options.entitySecret.length < 16) {
      throw new InvalidPaymentRequirementsError(
        "entitySecret is required and must be at least 16 characters for nanopayment key encryption"
      );
    }
    this.entitySecret = options.entitySecret;
    this.keyStorePath = options.keyStorePath;
    this.loadFromDiskIfAvailable();
  }

  addKey(alias: string, privateKey: string): string {
    const wallet = new Wallet(privateKey);
    this.keyStore.set(alias, {
      encryptedPrivateKey: encryptPrivateKey(wallet.privateKey, this.entitySecret),
      address: wallet.address
    });
    if (!this.defaultAlias) this.defaultAlias = alias;
    this.persistToDisk();
    return wallet.address;
  }

  generateKey(alias: string): string {
    const wallet = Wallet.createRandom();
    this.keyStore.set(alias, {
      encryptedPrivateKey: encryptPrivateKey(wallet.privateKey, this.entitySecret),
      address: wallet.address
    });
    if (!this.defaultAlias) this.defaultAlias = alias;
    this.persistToDisk();
    return wallet.address;
  }

  setDefaultKey(alias: string): void {
    if (!this.keyStore.has(alias)) {
      throw new KeyNotFoundError(alias);
    }
    this.defaultAlias = alias;
    this.persistToDisk();
  }

  listKeys(): string[] {
    return [...this.keyStore.keys()];
  }

  getAddress(alias?: string): string {
    const resolvedAlias = alias ?? this.defaultAlias;
    if (!resolvedAlias) throw new NoDefaultKeyError();
    const key = this.keyStore.get(resolvedAlias);
    if (!key) throw new KeyNotFoundError(resolvedAlias);
    return key.address;
  }

  async sign(kind: PaymentRequirementsKind, alias?: string): Promise<PaymentPayload> {
    const resolvedAlias = alias ?? this.defaultAlias;
    if (!resolvedAlias) throw new NoDefaultKeyError();
    const key = this.keyStore.get(resolvedAlias);
    if (!key) throw new KeyNotFoundError(resolvedAlias);

    validateRequirements(kind);
    const wallet = new Wallet(decryptPrivateKey(key.encryptedPrivateKey, this.entitySecret));
    const chainId = parseCaip2ChainId(kind.network);
    const now = Math.floor(Date.now() / 1000);
    const validBefore = now + DEFAULT_VALID_BEFORE_SECONDS;
    const authorization = {
      from: wallet.address,
      to: kind.payTo,
      value: kind.amount,
      validAfter: "0",
      validBefore: String(validBefore),
      nonce: `0x${randomBytes(32).toString("hex")}`
    };

    const domain = {
      name: kind.extra?.name || CIRCLE_BATCHING_NAME,
      version: kind.extra?.version || CIRCLE_BATCHING_VERSION,
      chainId,
      verifyingContract: kind.extra?.verifyingContract
    };
    const types = {
      TransferWithAuthorization: [
        { name: "from", type: "address" },
        { name: "to", type: "address" },
        { name: "value", type: "uint256" },
        { name: "validAfter", type: "uint256" },
        { name: "validBefore", type: "uint256" },
        { name: "nonce", type: "bytes32" }
      ]
    };

    const signature = await wallet.signTypedData(domain, types, authorization);
    return {
      x402Version: X402_VERSION,
      scheme: kind.scheme || CIRCLE_BATCHING_SCHEME,
      network: kind.network,
      payload: { authorization, signature }
    };
  }

  private persistToDisk(): void {
    if (!this.keyStorePath) {
      return;
    }
    const payload: PersistedState = {
      defaultAlias: this.defaultAlias,
      keys: Object.fromEntries(this.keyStore.entries())
    };
    writeFileSync(this.keyStorePath, JSON.stringify(payload, null, 2), { encoding: "utf8" });
  }

  private loadFromDiskIfAvailable(): void {
    if (!this.keyStorePath) {
      return;
    }
    try {
      const raw = readFileSync(this.keyStorePath, { encoding: "utf8" });
      const parsed = JSON.parse(raw) as PersistedState;
      this.defaultAlias = parsed.defaultAlias ?? null;
      for (const [alias, value] of Object.entries(parsed.keys ?? {})) {
        this.keyStore.set(alias, value);
      }
    } catch {
      // First-run or corrupted keystore: continue with empty in-memory store.
    }
  }
}

function validateRequirements(kind: PaymentRequirementsKind): void {
  if (kind.extra?.name !== CIRCLE_BATCHING_NAME) {
    throw new InvalidPaymentRequirementsError("Expected GatewayWalletBatched payment scheme");
  }
  if (!kind.extra?.verifyingContract) {
    throw new InvalidPaymentRequirementsError("Missing verifyingContract in payment requirements");
  }
  if (parseCaip2ChainId(kind.network) <= 0) {
    throw new InvalidPaymentRequirementsError("Network must be CAIP-2 eip155:<chainId>");
  }
  const amountAtomic = Number.parseInt(kind.amount, 10);
  if (!Number.isFinite(amountAtomic) || amountAtomic <= 0) {
    throw new InvalidPaymentRequirementsError("Amount must be a positive atomic integer");
  }
  const validitySeconds = DEFAULT_VALID_BEFORE_SECONDS;
  if (validitySeconds < MIN_VALID_BEFORE_SECONDS) {
    throw new InvalidPaymentRequirementsError(
      "validBefore window is below minimum required threshold"
    );
  }
}
