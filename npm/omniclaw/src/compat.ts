import { ConfigurationError, OmniClawError } from "./errors.js";
import { randomBytes } from "node:crypto";
import { parsePrice } from "./protocols/nanopayments/middleware.js";

export enum Network {
  ARC_TESTNET = "eip155:5042002",
  BASE_SEPOLIA = "eip155:84532",
  BASE_MAINNET = "eip155:8453",
  ETHEREUM = "eip155:1"
}

export enum FeeLevel {
  LOW = "low",
  MEDIUM = "medium",
  HIGH = "high"
}

export enum PaymentMethod {
  TRANSFER = "transfer",
  X402 = "x402",
  NANO = "nano"
}

export enum PaymentStatus {
  PENDING = "pending",
  SUCCESS = "success",
  FAILED = "failed"
}

export interface WalletInfo {
  id: string;
  address?: string;
  blockchain?: string;
}

export interface WalletSetInfo {
  id: string;
  name?: string;
}

export interface Balance {
  amount: string;
  currency: string;
}

export interface TokenInfo {
  symbol: string;
  decimals: number;
  contractAddress?: string;
}

export interface PaymentRequest {
  wallet_id: string;
  recipient: string;
  amount: string;
  currency?: string;
  purpose?: string;
}

export interface PaymentResult {
  success: boolean;
  transaction_id?: string;
  status?: string;
}

export interface SimulationResult {
  would_succeed: boolean;
  estimated_fees: string;
  net_transfer: string;
}

export interface TransactionInfo {
  id: string;
  status: string;
}

export interface PaymentIntent {
  id: string;
  status: string;
  amount: string;
  currency: string;
}

export type PaymentIntentStatus = "pending" | "requires_review" | "confirmed" | "cancelled" | "failed";

export interface TrustPolicy {
  minScore?: number;
  actionOnUnknown?: "allow" | "hold" | "block";
}

export interface AgentIdentity {
  id: string;
  walletAddress?: string;
}

export interface ReputationScore {
  score: number;
  source?: string;
}

// Exception aliases matching common OmniClaw error names across clients.
export class WalletError extends OmniClawError {}
export class PaymentError extends OmniClawError {}
export class GuardError extends OmniClawError {}
export class ProtocolError extends OmniClawError {}
export class InsufficientBalanceError extends OmniClawError {}
export class NetworkError extends OmniClawError {}
export class X402Error extends OmniClawError {}
export class CrosschainError extends OmniClawError {}
export class IdempotencyError extends OmniClawError {}
export class TransactionTimeoutError extends OmniClawError {}
export class ValidationError extends OmniClawError {}

export interface DoctorStatus {
  ok: boolean;
  checks: Record<string, boolean>;
  notes: string[];
}

export function quickSetup(circleApiKey: string, entitySecret?: string): {
  CIRCLE_API_KEY: string;
  ENTITY_SECRET?: string;
} {
  if (!circleApiKey) {
    throw new ConfigurationError("circleApiKey is required");
  }
  return { CIRCLE_API_KEY: circleApiKey, ENTITY_SECRET: entitySecret };
}

export const quick_setup = quickSetup;

export function ensureSetup(): boolean {
  return Boolean(process.env.CIRCLE_API_KEY);
}

export const ensure_setup = ensureSetup;

export function verifySetup(): DoctorStatus {
  const checks = {
    CIRCLE_API_KEY: Boolean(process.env.CIRCLE_API_KEY),
    ENTITY_SECRET: Boolean(process.env.ENTITY_SECRET)
  };
  return {
    ok: Object.values(checks).every(Boolean),
    checks,
    notes: []
  };
}

export const verify_setup = verifySetup;

export function doctor(): DoctorStatus {
  return verifySetup();
}

export function printDoctorStatus(status = doctor()): void {
  // Intentionally console-based for CLI-style diagnostics.
  // eslint-disable-next-line no-console
  console.log(status);
}

export const print_doctor_status = printDoctorStatus;

export function printSetupStatus(status = verifySetup()): void {
  // eslint-disable-next-line no-console
  console.log(status);
}

export const print_setup_status = printSetupStatus;

export function getConfigDir(): string {
  return process.env.OMNICLAW_CONFIG_DIR ?? ".omniclaw";
}

export const get_config_dir = getConfigDir;

export function generateEntitySecret(): string {
  return cryptoRandomString(64);
}

export const generate_entity_secret = generateEntitySecret;

export function findRecoveryFile(): string | null {
  return null;
}

export const find_recovery_file = findRecoveryFile;

export function storeManagedCredentials(): void {
  // no-op compatibility helper
}

export const store_managed_credentials = storeManagedCredentials;

export const parse_price = parsePrice;

function cryptoRandomString(len: number): string {
  const neededBytes = Math.ceil(len / 2);
  return randomBytes(neededBytes).toString("hex").slice(0, len);
}
