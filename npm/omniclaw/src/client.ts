import { CircleApiError, ConfigurationError } from "./errors.js";
import { deriveIdempotencyKey } from "./core/idempotency.js";
import {
  BudgetGuard,
  ConfirmGuard,
  GuardManager,
  RateLimitGuard,
  RecipientGuard,
  SingleTxGuard
} from "./core/guards.js";
import { Ledger } from "./core/ledger.js";
import { PaymentIntentService } from "./core/intents.js";
import { TrustGate } from "./core/trust.js";
import {
  assertEvmAddress,
  assertPositiveDecimal,
  assertWalletId
} from "./core/validation.js";
import { NanopaymentAdapter } from "./protocols/nanopayments/adapter.js";
import { NanopaymentClient } from "./protocols/nanopayments/client.js";
import { NanoKeyVault } from "./protocols/nanopayments/vault.js";
import { simulatePaymentLocally } from "./simulate.js";
import type {
  CirclePaymentIntentResponse,
  CirclePaymentResponse,
  CircleWalletResponse,
  CreatePaymentIntentParams,
  CreatePaymentParams,
  OmniClawConfig,
  RoutedPaymentParams,
  RoutedPaymentResult,
  SimulatePaymentParams,
  SimulatePaymentResult
} from "./types.js";
import type {
  NanopaymentResult,
  PayX402UrlParams
} from "./protocols/nanopayments/types.js";

const DEFAULT_BASE_URL = "https://api.circle.com";
const DEFAULT_CURRENCY = "USD";
const DEFAULT_FEE_RATE_PERCENT = 0.2;

export class OmniClaw {
  private readonly apiKey: string;
  private readonly defaultWalletId: string;
  private readonly baseUrl: string;
  private readonly defaultCurrency: string;
  private readonly defaultFeeRatePercent: number;
  private readonly fetchImpl: typeof fetch;
  private readonly nanopaymentsEnabled: boolean;
  private readonly nanoClient: NanopaymentClient | null;
  private readonly nanoVault: NanoKeyVault | null;
  private readonly nanoAdapter: NanopaymentAdapter | null;
  private readonly requireTrustGate: boolean;
  private readonly guardManager: GuardManager;
  private readonly ledger: Ledger;
  private readonly intents: PaymentIntentService;
  private readonly trustGate: TrustGate;

  constructor(config: OmniClawConfig = {}) {
    this.apiKey = config.circleApiKey ?? process.env.CIRCLE_API_KEY ?? "";
    this.defaultWalletId = config.circleWalletId ?? process.env.CIRCLE_WALLET_ID ?? "";
    this.baseUrl =
      config.circleApiBaseUrl ?? process.env.CIRCLE_API_BASE_URL ?? DEFAULT_BASE_URL;
    this.defaultCurrency = config.defaultCurrency ?? DEFAULT_CURRENCY;
    this.defaultFeeRatePercent = config.defaultFeeRatePercent ?? DEFAULT_FEE_RATE_PERCENT;
    this.fetchImpl = config.fetchImpl ?? fetch;
    this.nanopaymentsEnabled = config.nanopaymentsEnabled ?? true;
    this.requireTrustGate = config.requireTrustGate ?? false;
    this.guardManager = new GuardManager();
    this.ledger = new Ledger();
    this.intents = new PaymentIntentService();
    this.trustGate = new TrustGate(config.trustEvaluator);

    if (!this.apiKey) {
      throw new ConfigurationError("CIRCLE_API_KEY is required");
    }

    if (this.nanopaymentsEnabled) {
      const entitySecret = config.entitySecret ?? process.env.ENTITY_SECRET ?? "";
      this.nanoClient = new NanopaymentClient({
        apiKey: this.apiKey,
        environment: config.nanopaymentsEnvironment ?? "testnet",
        baseUrl: config.gatewayApiBaseUrl,
        fetchImpl: this.fetchImpl
      });
      this.nanoVault = new NanoKeyVault({
        entitySecret,
        keyStorePath: config.nanopaymentKeyStorePath
      });
      this.nanoAdapter = new NanopaymentAdapter(this.nanoVault, this.nanoClient, this.fetchImpl, {
        strictSettlement: config.strictSettlement ?? true,
        retryAttempts: config.retryAttempts,
        retryBaseDelayMs: config.retryBaseDelayMs,
        circuitBreakerFailureThreshold: config.circuitBreakerFailureThreshold,
        circuitBreakerRecoveryMs: config.circuitBreakerRecoveryMs
      });
    } else {
      this.nanoClient = null;
      this.nanoVault = null;
      this.nanoAdapter = null;
    }

    this.enforceProductionStartupRequirements(config);

    if (this.requireTrustGate && !this.trustGate.isConfigured()) {
      throw new ConfigurationError(
        "Trust gate is required but no trustEvaluator was provided in OmniClawConfig"
      );
    }
  }

  private enforceProductionStartupRequirements(config: OmniClawConfig): void {
    const env = String(process.env.OMNICLAW_ENV ?? "").toLowerCase();
    if (!["prod", "production", "mainnet"].includes(env)) {
      return;
    }

    if ((config.strictSettlement ?? true) !== true) {
      throw new ConfigurationError("strictSettlement must remain true in production-like environments");
    }
    if (this.nanopaymentsEnabled) {
      const entitySecret = config.entitySecret ?? process.env.ENTITY_SECRET ?? "";
      if (!entitySecret) {
        throw new ConfigurationError("ENTITY_SECRET is required when nanopayments are enabled");
      }
      if (!config.nanopaymentKeyStorePath) {
        throw new ConfigurationError(
          "nanopaymentKeyStorePath is required in production-like environments"
        );
      }
    }
  }

  async createPayment(params: CreatePaymentParams): Promise<CirclePaymentResponse> {
    const sourceWalletId = params.sourceWalletId ?? this.defaultWalletId;
    if (!sourceWalletId) {
      throw new ConfigurationError("sourceWalletId is required (or set CIRCLE_WALLET_ID)");
    }
    assertWalletId(sourceWalletId, "sourceWalletId");
    assertPositiveDecimal(params.amount, "amount");
    assertEvmAddress(params.destinationAddress, "destinationAddress");
    const idempotencyKey =
      params.idempotencyKey ??
      deriveIdempotencyKey([
        sourceWalletId,
        params.destinationAddress,
        params.amount,
        params.currency ?? this.defaultCurrency
      ]);

    const body = {
      amount: {
        amount: params.amount,
        currency: params.currency ?? this.defaultCurrency
      },
      source: {
        type: "wallet",
        id: sourceWalletId
      },
      destination: {
        type: "blockchain",
        address: params.destinationAddress
      }
    };

    return this.request<CirclePaymentResponse>("/v1/payments", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey }
    });
  }

  async getWalletBalance(walletId?: string): Promise<CircleWalletResponse> {
    const targetWalletId = walletId ?? this.defaultWalletId;
    if (!targetWalletId) {
      throw new ConfigurationError("walletId is required (or set CIRCLE_WALLET_ID)");
    }
    assertWalletId(targetWalletId, "walletId");
    return this.request<CircleWalletResponse>(`/v1/wallets/${targetWalletId}`, {
      method: "GET"
    });
  }

  simulatePayment(params: SimulatePaymentParams): SimulatePaymentResult {
    if (!params.destinationAddress) {
      throw new ConfigurationError("destinationAddress is required");
    }
    assertPositiveDecimal(params.amount, "amount");
    assertEvmAddress(params.destinationAddress, "destinationAddress");
    return simulatePaymentLocally(
      params,
      this.defaultWalletId,
      this.defaultCurrency,
      this.defaultFeeRatePercent
    );
  }

  async pay(params: CreatePaymentParams): Promise<CirclePaymentResponse> {
    const sourceWalletId = params.sourceWalletId ?? this.defaultWalletId;
    if (!sourceWalletId) {
      throw new ConfigurationError("sourceWalletId is required (or set CIRCLE_WALLET_ID)");
    }
    await this.guardManager.evaluate(
      sourceWalletId,
      {
        walletId: sourceWalletId,
        recipient: params.destinationAddress,
        amount: params.amount,
        currency: params.currency ?? this.defaultCurrency,
        purpose: params.purpose,
        confirm: params.confirm
      },
      params.skipGuards ?? false
    );
    if (params.checkTrust ?? false) {
      const trust = await this.trustGate.check(params.destinationAddress);
      if (trust.verdict === "block") {
        throw new ConfigurationError(`Trust gate blocked payment: ${trust.reason ?? "blocked"}`);
      }
      if (trust.verdict === "hold") {
        throw new ConfigurationError(`Trust gate held payment: ${trust.reason ?? "requires review"}`);
      }
    }
    return this.createPayment(params);
  }

  async createPaymentIntent(
    params: CreatePaymentIntentParams
  ): Promise<CirclePaymentIntentResponse> {
    assertPositiveDecimal(params.amount, "amount");
    const walletId = params.sourceWalletId ?? this.defaultWalletId;
    if (!walletId) {
      throw new ConfigurationError("sourceWalletId is required (or set CIRCLE_WALLET_ID)");
    }
    const recipient = params.recipient ?? "payment-intent";
    const idempotencyKey =
      params.idempotencyKey ?? deriveIdempotencyKey([walletId, recipient, params.amount, "intent"]);
    let requiresReview = false;
    if (params.checkTrust ?? false) {
      const trust = await this.trustGate.check(recipient);
      if (trust.verdict === "block") {
        throw new ConfigurationError(`Trust gate blocked intent: ${trust.reason ?? "blocked"}`);
      }
      requiresReview = trust.verdict === "hold";
    }
    const localIntent = this.intents.createIntent({
      walletId,
      recipient,
      amount: params.amount,
      currency: params.currency ?? this.defaultCurrency,
      idempotencyKey,
      requiresReview
    });

    const body = {
      amount: {
        amount: params.amount,
        currency: params.currency ?? this.defaultCurrency
      },
      settlementCurrency: params.settlementCurrency ?? this.defaultCurrency,
      paymentMethods: params.paymentMethods ?? ["card", "wire", "ach", "crypto"],
      metadata: {
        localIntentId: localIntent.id,
        idempotencyKey
      }
    };

    return this.request<CirclePaymentIntentResponse>("/v1/paymentIntents", {
      method: "POST",
      body: JSON.stringify(body)
    });
  }

  async getPaymentIntent(intentId: string): Promise<CirclePaymentIntentResponse> {
    const remote = await this.request<CirclePaymentIntentResponse>(`/v1/paymentIntents/${intentId}`, {
      method: "GET"
    });
    const local = this.intents.getIntent(intentId);
    if (!local) {
      return remote;
    }
    return {
      ...remote,
      data: {
        ...(remote.data ?? {}),
        localStatus: local.status
      }
    };
  }

  async confirmPaymentIntent(intentId: string): Promise<CirclePaymentIntentResponse> {
    const updated = this.intents.updateStatus(intentId, "confirmed");
    if (!updated) {
      return this.request<CirclePaymentIntentResponse>(
        `/v1/paymentIntents/${intentId}/confirm`,
        { method: "POST", body: "{}" }
      );
    }
    return this.request<CirclePaymentIntentResponse>(
      `/v1/paymentIntents/${intentId}/confirm`,
      { method: "POST", body: "{}" }
    );
  }

  async cancelPaymentIntent(intentId: string): Promise<void> {
    const updated = this.intents.updateStatus(intentId, "cancelled");
    if (!updated) {
      throw new ConfigurationError(`Unknown intentId: ${intentId}`);
    }
  }

  // Snake_case helpers for teams migrating from other OmniClaw client bindings
  async get_balance(wallet_id: string): Promise<number> {
    const balance = await this.getWalletBalance(wallet_id);
    const amount = balance.data?.balances?.[0]?.amount ?? "0";
    return Number.parseFloat(amount);
  }

  async create_wallet_set(name?: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/v1/walletSets", {
      method: "POST",
      body: JSON.stringify({ name: name ?? `wallet-set-${Date.now()}` })
    });
  }

  async create_wallet(params: {
    wallet_set_id?: string;
    blockchain?: string;
    account_type?: string;
  } = {}): Promise<Record<string, unknown>> {
    const walletSetId = params.wallet_set_id;
    if (!walletSetId) {
      throw new ConfigurationError("wallet_set_id is required");
    }
    return this.request<Record<string, unknown>>("/v1/wallets", {
      method: "POST",
      body: JSON.stringify({
        walletSetId,
        blockchains: [params.blockchain ?? "ETH-SEPOLIA"],
        accountType: params.account_type ?? "SCA"
      })
    });
  }

  async create_agent_wallet(name: string): Promise<Record<string, unknown>> {
    const walletSet = await this.create_wallet_set(name);
    const walletSetId = String(
      (walletSet.data as Record<string, unknown> | undefined)?.walletSetId ??
        (walletSet.data as Record<string, unknown> | undefined)?.id ??
        ""
    );
    if (!walletSetId) {
      throw new ConfigurationError("Unable to resolve wallet set id from Circle response");
    }
    const wallet = await this.create_wallet({ wallet_set_id: walletSetId });
    return { wallet_set: walletSet, wallet };
  }

  async list_wallet_sets(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/v1/walletSets", { method: "GET" });
  }

  async list_wallets(wallet_set_id?: string): Promise<Record<string, unknown>> {
    const endpoint = wallet_set_id
      ? `/v1/wallets?walletSetId=${encodeURIComponent(wallet_set_id)}`
      : "/v1/wallets";
    return this.request<Record<string, unknown>>(endpoint, { method: "GET" });
  }

  async get_wallet(wallet_id: string): Promise<CircleWalletResponse> {
    return this.getWalletBalance(wallet_id);
  }

  async get_wallet_set(wallet_set_id: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(`/v1/walletSets/${wallet_set_id}`, {
      method: "GET"
    });
  }

  async get_payment_address(wallet_id: string): Promise<string> {
    const wallet = await this.get_wallet(wallet_id);
    const address = (wallet.data as Record<string, unknown> | undefined)?.address;
    return typeof address === "string" ? address : "";
  }

  async add_budget_guard_for_set(wallet_set_id: string, max_budget: number): Promise<void> {
    const wallets = await this.list_wallets(wallet_set_id);
    const rows = (wallets.data as Array<Record<string, unknown>> | undefined) ?? [];
    rows.forEach((entry) => {
      const id = entry.walletId ?? entry.id;
      if (typeof id === "string") {
        this.addBudgetGuard(id, max_budget);
      }
    });
  }

  async add_confirm_guard_for_set(wallet_set_id: string, threshold: number): Promise<void> {
    const wallets = await this.list_wallets(wallet_set_id);
    const rows = (wallets.data as Array<Record<string, unknown>> | undefined) ?? [];
    rows.forEach((entry) => {
      const id = entry.walletId ?? entry.id;
      if (typeof id === "string") {
        this.addConfirmGuard(id, threshold);
      }
    });
  }

  async add_rate_limit_guard_for_set(
    wallet_set_id: string,
    max_calls: number,
    window_ms: number
  ): Promise<void> {
    const wallets = await this.list_wallets(wallet_set_id);
    const rows = (wallets.data as Array<Record<string, unknown>> | undefined) ?? [];
    rows.forEach((entry) => {
      const id = entry.walletId ?? entry.id;
      if (typeof id === "string") {
        this.addRateLimitGuard(id, max_calls, window_ms);
      }
    });
  }

  async add_recipient_guard_for_set(wallet_set_id: string, recipients: string[]): Promise<void> {
    const wallets = await this.list_wallets(wallet_set_id);
    const rows = (wallets.data as Array<Record<string, unknown>> | undefined) ?? [];
    rows.forEach((entry) => {
      const id = entry.walletId ?? entry.id;
      if (typeof id === "string") {
        this.addRecipientGuard(id, recipients);
      }
    });
  }

  async batch_pay(
    requests: Array<{
      wallet_id?: string;
      recipient: string;
      amount: string;
      currency?: string;
      purpose?: string;
    }>
  ): Promise<Array<RoutedPaymentResult>> {
    const results: Array<RoutedPaymentResult> = [];
    for (const request of requests) {
      const result = await this.payWithRouting({
        walletId: request.wallet_id,
        recipient: request.recipient,
        amount: request.amount,
        currency: request.currency,
        purpose: request.purpose
      });
      results.push(result);
    }
    return results;
  }

  async sync_transaction(entry_id: string) {
    return this.ledger.get(entry_id);
  }

  async list_pending_settlements() {
    return this.ledger.list().filter((entry) => entry.status === "pending");
  }

  async finalize_pending_settlement(entry_id: string, success = true) {
    return this.ledger.updateStatus(entry_id, success ? "confirmed" : "failed");
  }

  async reconcile_pending_settlements() {
    const pending = await this.list_pending_settlements();
    return pending.map((entry) => this.ledger.updateStatus(entry.id, "failed"));
  }

  async list_guards_for_set(wallet_set_id: string): Promise<string[]> {
    const wallets = await this.list_wallets(wallet_set_id);
    const rows = (wallets.data as Array<Record<string, unknown>> | undefined) ?? [];
    const all: string[] = [];
    rows.forEach((entry) => {
      const id = entry.walletId ?? entry.id;
      if (typeof id === "string") {
        all.push(...this.listGuards(id));
      }
    });
    return [...new Set(all)];
  }

  listLedgerEntries() {
    return this.ledger.list();
  }

  listGuards(walletId?: string): string[] {
    const targetWalletId = walletId ?? this.defaultWalletId;
    if (!targetWalletId) {
      return [];
    }
    return this.guardManager.listGuards(targetWalletId);
  }

  addBudgetGuard(walletId: string, maxBudget: number): void {
    assertWalletId(walletId, "walletId");
    this.guardManager.addGuard(walletId, new BudgetGuard(maxBudget));
  }

  async add_budget_guard(wallet_id: string, max_budget: number): Promise<void> {
    this.addBudgetGuard(wallet_id, max_budget);
  }

  addRateLimitGuard(walletId: string, maxCalls: number, windowMs: number): void {
    assertWalletId(walletId, "walletId");
    this.guardManager.addGuard(walletId, new RateLimitGuard(maxCalls, windowMs));
  }

  async add_rate_limit_guard(
    wallet_id: string,
    max_calls: number,
    window_ms: number
  ): Promise<void> {
    this.addRateLimitGuard(wallet_id, max_calls, window_ms);
  }

  addRecipientGuard(walletId: string, allowedRecipients: string[]): void {
    assertWalletId(walletId, "walletId");
    this.guardManager.addGuard(walletId, new RecipientGuard(allowedRecipients));
  }

  async add_recipient_guard(wallet_id: string, recipients: string[]): Promise<void> {
    this.addRecipientGuard(wallet_id, recipients);
  }

  addSingleTxGuard(walletId: string, maxAmount: number): void {
    assertWalletId(walletId, "walletId");
    this.guardManager.addGuard(walletId, new SingleTxGuard(maxAmount));
  }

  async add_single_tx_guard(wallet_id: string, max_amount: number): Promise<void> {
    this.addSingleTxGuard(wallet_id, max_amount);
  }

  addConfirmGuard(walletId: string, threshold: number): void {
    assertWalletId(walletId, "walletId");
    this.guardManager.addGuard(walletId, new ConfirmGuard(threshold));
  }

  async add_confirm_guard(wallet_id: string, threshold: number): Promise<void> {
    this.addConfirmGuard(wallet_id, threshold);
  }

  async payWithRouting(params: RoutedPaymentParams): Promise<RoutedPaymentResult> {
    const walletId = params.walletId ?? this.defaultWalletId;
    if (!walletId) {
      throw new ConfigurationError("walletId is required (or set CIRCLE_WALLET_ID)");
    }
    assertWalletId(walletId, "walletId");
    assertPositiveDecimal(params.amount, "amount");
    const currency = params.currency ?? this.defaultCurrency;

    const simulation = simulatePaymentLocally(
      {
        amount: params.amount,
        currency,
        sourceWalletId: walletId,
        destinationAddress: params.recipient
      },
      walletId,
      currency,
      this.defaultFeeRatePercent
    );
    if (!simulation.readyToExecute) {
      throw new ConfigurationError("Simulation failed: payment not ready to execute");
    }

    await this.guardManager.evaluate(
      walletId,
      {
        walletId,
        recipient: params.recipient,
        amount: params.amount,
        currency,
        purpose: params.purpose,
        confirm: params.confirm
      },
      params.skipGuards ?? false
    );

    let trustResult;
    if (params.checkTrust ?? false) {
      trustResult = await this.trustGate.check(params.recipient);
      if (trustResult.verdict === "block") {
        throw new ConfigurationError(`Trust gate blocked payment: ${trustResult.reason ?? "blocked"}`);
      }
      if (trustResult.verdict === "hold") {
        throw new ConfigurationError(
          `Trust gate held payment for review: ${trustResult.reason ?? "requires review"}`
        );
      }
    }

    const ledgerEntry = this.ledger.create({
      id: deriveIdempotencyKey([walletId, params.recipient, params.amount, Date.now()]),
      walletId,
      recipient: params.recipient,
      amount: params.amount,
      currency,
      status: "pending",
      metadata: { purpose: params.purpose }
    });

    try {
      if (params.recipient.startsWith("https://")) {
        if (!this.nanoAdapter) {
          throw new ConfigurationError("Nanopayments are disabled; cannot pay x402 URL recipient");
        }
        const result = await this.nanoAdapter.payX402Url({
          url: params.recipient,
          keyAlias: params.nanoKeyAlias
        });
        this.ledger.updateStatus(ledgerEntry.id, result.success ? "confirmed" : "failed");
        return {
          route: "x402_nanopayment",
          success: result.success,
          trust: trustResult,
          simulation,
          ledgerEntryId: ledgerEntry.id,
          result
        };
      }

      assertEvmAddress(params.recipient, "recipient");
      const amountFloat = Number.parseFloat(params.amount);
      if (amountFloat < 1 && this.nanoAdapter) {
        const result = await this.nanoAdapter.payDirect({
          sellerAddress: params.recipient,
          amountUsdc: params.amount,
          network: params.network ?? "eip155:5042002",
          keyAlias: params.nanoKeyAlias
        });
        this.ledger.updateStatus(ledgerEntry.id, result.success ? "confirmed" : "failed");
        return {
          route: "direct_nanopayment",
          success: result.success,
          trust: trustResult,
          simulation,
          ledgerEntryId: ledgerEntry.id,
          result
        };
      }

      const circleResult = await this.createPayment({
        amount: params.amount,
        currency,
        sourceWalletId: walletId,
        destinationAddress: params.recipient
      });
      this.ledger.updateStatus(ledgerEntry.id, "confirmed");
      return {
        route: "circle_transfer",
        success: true,
        trust: trustResult,
        simulation,
        ledgerEntryId: ledgerEntry.id,
        result: circleResult
      };
    } catch (error) {
      this.ledger.updateStatus(ledgerEntry.id, "failed");
      throw error;
    }
  }

  addNanoKey(alias: string, privateKey: string): string {
    if (!this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoVault.addKey(alias, privateKey);
  }

  generateNanoKey(alias: string): string {
    if (!this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoVault.generateKey(alias);
  }

  setDefaultNanoKey(alias: string): void {
    if (!this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    this.nanoVault.setDefaultKey(alias);
  }

  listNanoKeys(): string[] {
    if (!this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoVault.listKeys();
  }

  getNanoAddress(alias?: string): string {
    if (!this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoVault.getAddress(alias);
  }

  async getGatewaySupportedNetworks() {
    if (!this.nanoClient) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoClient.getSupported();
  }

  async getGatewayBalance(alias?: string, network = "eip155:5042002") {
    if (!this.nanoClient || !this.nanoVault) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    const address = this.nanoVault.getAddress(alias);
    return this.nanoClient.getBalance(address, network);
  }

  async payX402Url(params: PayX402UrlParams): Promise<NanopaymentResult> {
    if (!this.nanoAdapter) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoAdapter.payX402Url(params);
  }

  async payDirectNano(params: {
    sellerAddress: string;
    amountUsdc: string;
    network: string;
    keyAlias?: string;
  }): Promise<NanopaymentResult> {
    if (!this.nanoAdapter) {
      throw new ConfigurationError("Nanopayments are disabled");
    }
    return this.nanoAdapter.payDirect(params);
  }

  private async request<T>(
    endpoint: string,
    init: { method: string; body?: string; headers?: Record<string, string> }
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {})
    };

    const response = await this.fetchImpl(`${this.baseUrl}${endpoint}`, {
      method: init.method,
      headers,
      body: init.body
    });

    const text = await response.text();
    const payload = text ? safeJsonParse(text) : {};
    if (!response.ok) {
      throw new CircleApiError(
        `Circle API request failed (${response.status}) for ${endpoint}`,
        response.status,
        payload
      );
    }
    return payload as T;
  }
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return { raw: value };
  }
}
