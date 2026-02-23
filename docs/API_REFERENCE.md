# OmniClaw SDK - API Reference

> **Version:** 0.0.1  
> **Last Updated:** 2026-01-18

This document provides a comprehensive reference of all public methods, parameters, and return types in the OmniClaw SDK.

---

## Table of Contents

1. [Setup & Onboarding](#setup--onboarding)
2. [Main Client (`OmniClaw`)](#main-client-omniclaw)
3. [Wallet Management (`WalletService`)](#wallet-management-walletservice)
4. [Guards (`GuardManager`)](#guards-guardmanager)
5. [Ledger (`Ledger`)](#ledger-ledger)
6. [Payment Intents (`PaymentIntentService`)](#payment-intents-paymentintentservice)
7. [Webhooks (`WebhookParser`)](#webhooks-webhookparser)

---

## Setup & Onboarding

Functions for initial SDK setup and configuration.

### `quick_setup(api_key, env_path=".env", network="ARC-TESTNET")`

Complete SDK setup in one call.

**Parameters:**
- `api_key` (str): Circle API key
- `env_path` (str | Path, optional): Path for .env file. Default: `".env"`
- `network` (str, optional): Target network. Default: `"ARC-TESTNET"`

**Returns:** `dict` - Contains `entity_secret`, `env_path`, `recovery_dir`

**Example:**
```python
from omniclaw import quick_setup
result = quick_setup("sk_test_...")
```

---

### `generate_entity_secret()`

Generate a new 32-byte Entity Secret (64 hex characters).

**Parameters:** None

**Returns:** `str` - 64-character hex string for use as ENTITY_SECRET

---

### `register_entity_secret(api_key, entity_secret, recovery_dir=None)`

Register an Entity Secret with Circle.

**Parameters:**
- `api_key` (str): Circle API key
- `entity_secret` (str): 64-character hex secret
- `recovery_dir` (str | Path | None, optional): Directory to save recovery file. Default: current directory

**Returns:** Registration result from Circle API

**Raises:**
- `SetupError`: If Circle SDK not installed or registration fails

---

### `create_env_file(api_key, entity_secret, env_path=".env", network="ARC-TESTNET", overwrite=False)`

Create a .env file with Circle credentials.

**Parameters:**
- `api_key` (str): Circle API key
- `entity_secret` (str): 64-character hex entity secret
- `env_path` (str | Path, optional): Path for .env file. Default: `".env"`
- `network` (str, optional): Network name. Default: `"ARC-TESTNET"`
- `overwrite` (bool, optional): Overwrite existing file. Default: `False`

**Returns:** `Path` - Path to created .env file

**Raises:**
- `SetupError`: If file exists and `overwrite=False`

---

### `verify_setup()`

Verify that SDK is properly configured.

**Parameters:** None

**Returns:** `dict` - Status of each requirement and `'ready'` boolean

---

### `print_setup_status()`

Print human-readable setup status to console.

**Parameters:** None

**Returns:** None

---

### `find_recovery_file()`

Search for an existing Circle recovery file.

**Parameters:** None

**Returns:** `Path | None` - Path to recovery file if found, None otherwise

---

### `get_config_dir()`

Get the platform-specific config directory for OmniClaw.

**Parameters:** None

**Returns:** `Path` - Path to config directory (created if doesn't exist)
- Linux: `~/.config/omniclaw/`
- macOS: `~/Library/Application Support/omniclaw/`
- Windows: `%APPDATA%/omniclaw/`

---

## Main Client (`OmniClaw`)

The primary entry point for all SDK operations.

### `__init__(circle_api_key=None, entity_secret=None, network=Network.ARC_TESTNET, log_level=None)`

Initialize OmniClaw client.

**Parameters:**
- `circle_api_key` (str | None, optional): Circle API key (or from `CIRCLE_API_KEY` env)
- `entity_secret` (str | None, optional): Entity secret for signing (or from `ENTITY_SECRET` env)
- `network` (Network, optional): Target blockchain network. Default: `Network.ARC_TESTNET`
- `log_level` (int | str | None, optional): Logging level. Default: `INFO`

**Example:**
```python
from omniclaw import OmniClaw, Network

client = OmniClaw(
    circle_api_key="sk_...",
    entity_secret="...",
    network=Network.ARC_TESTNET
)
```

---

### Properties

#### `config`
**Returns:** `Config` - SDK configuration

#### `wallet`
**Returns:** `WalletService` - Wallet service for wallet management

#### `guards`
**Returns:** `GuardManager` - Guard manager for per-wallet/wallet-set guards

#### `ledger`
**Returns:** `Ledger` - Transaction ledger

#### `webhooks`
**Returns:** `WebhookParser` - Webhook parser for verifying and parsing events

#### `intents`
**Returns:** `PaymentIntentService` - Intent management service

---

### Wallet Operations

#### `create_wallet(blockchain=None, wallet_set_id=None, account_type=AccountType.EOA, name=None)`

Create a new wallet.

**Parameters:**
- `blockchain` (Network | str | None, optional): Blockchain network (default: config.network)
- `wallet_set_id` (str | None, optional): ID of existing wallet set. If None, creates a new set
- `account_type` (AccountType, optional): Wallet type (EOA or SCA). Default: `AccountType.EOA`
- `name` (str | None, optional): Name for new wallet set if creating one

**Returns:** `WalletInfo` - Created wallet information

---

#### `create_wallet_set(name=None)`

Create a new wallet set.

**Parameters:**
- `name` (str | None, optional): Human-readable name for the wallet set

**Returns:** `WalletSetInfo` - Created wallet set information

---

#### `list_wallets(wallet_set_id=None)`

List wallets (optional filter by set).

**Parameters:**
- `wallet_set_id` (str | None, optional): Filter by wallet set ID

**Returns:** `list[WalletInfo]` - List of wallets

---

#### `list_wallet_sets()`

List available wallet sets.

**Parameters:** None

**Returns:** `list[WalletSetInfo]` - List of wallet sets

---

#### `get_wallet(wallet_id)`

Get details of a specific wallet.

**Parameters:**
- `wallet_id` (str): Wallet ID

**Returns:** `WalletInfo` - Wallet information

---

#### `list_transactions(wallet_id=None, blockchain=None)`

List transactions for a wallet or globally.

**Parameters:**
- `wallet_id` (str | None, optional): Filter by wallet ID
- `blockchain` (Network | str | None, optional): Filter by blockchain

**Returns:** `list[TransactionInfo]` - List of transactions

---

#### `get_balance(wallet_id)`

Get USDC balance for a wallet.

**Parameters:**
- `wallet_id` (str): Wallet ID to check

**Returns:** `Decimal` - USDC balance

---

### Payment Operations

#### `pay(wallet_id, recipient, amount, destination_chain=None, wallet_set_id=None, purpose=None, idempotency_key=None, fee_level=FeeLevel.MEDIUM, skip_guards=False, metadata=None, wait_for_completion=False, timeout_seconds=None, **kwargs)`

Execute a payment with automatic routing (Transfer, x402, or Gateway) and guard checks.

**Parameters:**
- `wallet_id` (str, **required**): Source wallet ID
- `recipient` (str, **required**): Payment recipient (address, x402 URL, or payment pointer)
- `amount` (AmountType, **required**): Amount to pay (Decimal or string)
- `destination_chain` (Network | str | None, optional): Destination blockchain
- `wallet_set_id` (str | None, optional): Wallet set ID (for set-level guards)
- `purpose` (str | None, optional): Human-readable purpose
- `idempotency_key` (str | None, optional): Idempotency key (auto-generated if not provided)
- `fee_level` (FeeLevel, optional): Fee level. Default: `FeeLevel.MEDIUM`
- `skip_guards` (bool, optional): Skip guard checks. Default: `False`
- `metadata` (dict[str, Any] | None, optional): Additional metadata
- `wait_for_completion` (bool, optional): Wait for blockchain confirmation. Default: `False`
- `timeout_seconds` (float | None, optional): Timeout for waiting
- `**kwargs`: Additional parameters for routing

**Returns:** `PaymentResult` - Payment execution result

**Example (Same-chain):**
```python
from decimal import Decimal

result = await client.pay(
    wallet_id="wallet-123",
    recipient="0x742d35Cc6634C0532925a3b844Bc9e7595...",
    amount=Decimal("10.00"),
    purpose="API subscription payment"
)
```

**Example (Cross-chain via CCTP):**
```python
from decimal import Decimal
from omniclaw import Network

# Transfer from Base to Ethereum
result = await client.pay(
    wallet_id="wallet-123",  # Wallet on Base
    recipient="0x742d35Cc6634C0532925a3b844Bc9e7595...",  # Address on Ethereum
    amount=Decimal("10.00"),
    destination_chain=Network.ETH,  # REQUIRED for cross-chain
    purpose="Cross-chain payment"
)
```

> **Note:** For cross-chain transfers, `destination_chain` is **required**. The `source_network` is automatically inferred from the wallet. If `destination_chain` is not provided when networks differ, the payment will fail with an error.

---

#### `simulate(wallet_id, recipient, amount, wallet_set_id=None, **kwargs)`

Simulate a payment without executing.

**Parameters:**
- `wallet_id` (str, **required**): Source wallet ID
- `recipient` (str, **required**): Payment recipient
- `amount` (Decimal | str, **required**): Amount to simulate
- `wallet_set_id` (str | None, optional): Wallet set ID (for set-level guards)
- `**kwargs`: Additional parameters

**Returns:** `SimulationResult` - Contains `would_succeed`, `route`, and `reason`

---

#### `can_pay(recipient)`

Check if a recipient can be paid.

**Parameters:**
- `recipient` (str): Payment recipient

**Returns:** `bool` - True if an adapter can handle this recipient

---

#### `detect_method(recipient)`

Detect which payment method would be used for a recipient.

**Parameters:**
- `recipient` (str): Payment recipient

**Returns:** `PaymentMethod | None` - Payment method or None

---

#### `batch_pay(requests, concurrency=5)`

Execute multiple payments in batch.

**Parameters:**
- `requests` (list[PaymentRequest], **required**): List of payment requests to execute
- `concurrency` (int, optional): Maximum number of concurrent executions. Default: `5`

**Returns:** `BatchPaymentResult` - Status of all payments

---

### Payment Intents (Authorize/Capture)

#### `create_payment_intent(wallet_id, recipient, amount, purpose=None, idempotency_key=None, **kwargs)`

Create a Payment Intent (Authorize).

**Parameters:**
- `wallet_id` (str, **required**): Source wallet ID
- `recipient` (str, **required**): Payment recipient
- `amount` (AmountType, **required**): Amount to pay
- `purpose` (str | None, optional): Human-readable purpose
- `idempotency_key` (str | None, optional): Idempotency key
- `**kwargs`: Additional context

**Returns:** `PaymentIntent` - Created payment intent

**Raises:**
- `PaymentError`: If authorization logic (guards/simulation) fails

---

#### `confirm_payment_intent(intent_id)`

Confirm and execute a Payment Intent (Capture).

**Parameters:**
- `intent_id` (str, **required**): ID of intent to confirm

**Returns:** `PaymentResult` - Payment execution result

**Raises:**
- `ValidationError`: If intent invalid or already processed

---

#### `get_payment_intent(intent_id)`

Get Payment Intent by ID.

**Parameters:**
- `intent_id` (str, **required**): Intent ID

**Returns:** `PaymentIntent | None` - Payment intent or None

---

#### `cancel_payment_intent(intent_id)`

Cancel a Payment Intent.

**Parameters:**
- `intent_id` (str, **required**): Intent ID to cancel

**Returns:** `PaymentIntent` - Updated payment intent

**Raises:**
- `ValidationError`: If intent not found or cannot be cancelled

---

### Transaction Management

#### `sync_transaction(entry_id)`

Synchronize a ledger entry with the provider status.

**Parameters:**
- `entry_id` (str, **required**): Ledger entry ID

**Returns:** `LedgerEntry` - Updated ledger entry

**Raises:**
- `ValidationError`: If entry not found or no transaction ID
- `PaymentError`: If provider fetch fails

---

### Guard Helpers

#### `add_budget_guard(wallet_id, daily_limit=None, hourly_limit=None, total_limit=None, name="budget")`

Add a budget guard to a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID
- `daily_limit` (str | Decimal | None, optional): Max spend per 24h
- `hourly_limit` (str | Decimal | None, optional): Max spend per 1h
- `total_limit` (str | Decimal | None, optional): Max total spend (lifetime)
- `name` (str, optional): Custom name for the guard. Default: `"budget"`

**Returns:** None

---

#### `add_budget_guard_for_set(wallet_set_id, daily_limit=None, hourly_limit=None, total_limit=None, name="budget")`

Add a budget guard to a wallet set (applies to ALL wallets in the set).

**Parameters:**
- `wallet_set_id` (str, **required**): Target wallet set ID
- `daily_limit` (str | Decimal | None, optional): Max spend per 24h
- `hourly_limit` (str | Decimal | None, optional): Max spend per 1h
- `total_limit` (str | Decimal | None, optional): Max total spend (lifetime)
- `name` (str, optional): Custom name for the guard. Default: `"budget"`

**Returns:** None

---

#### `add_single_tx_guard(wallet_id, max_amount, min_amount=None, name="single_tx")`

Add a Single Transaction Limit guard.

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID
- `max_amount` (str | Decimal, **required**): Max amount per transaction
- `min_amount` (str | Decimal | None, optional): Min amount per transaction
- `name` (str, optional): Guard name. Default: `"single_tx"`

**Returns:** None

---

#### `add_recipient_guard(wallet_id, mode="whitelist", addresses=None, patterns=None, domains=None, name="recipient")`

Add a Recipient Access Control guard.

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID
- `mode` (str, optional): `'whitelist'` (allow specific) or `'blacklist'` (block specific). Default: `"whitelist"`
- `addresses` (list[str] | None, optional): List of allowed/blocked addresses
- `patterns` (list[str] | None, optional): List of regex patterns
- `domains` (list[str] | None, optional): List of allowed/blocked domains (for x402/URLs)
- `name` (str, optional): Guard name. Default: `"recipient"`

**Returns:** None

---

#### `add_rate_limit_guard(wallet_id, max_per_minute=None, max_per_hour=None, max_per_day=None, name="rate_limit")`

Add a rate limit guard to a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID
- `max_per_minute` (int | None, optional): Max transactions per minute
- `max_per_hour` (int | None, optional): Max transactions per hour
- `max_per_day` (int | None, optional): Max transactions per day
- `name` (str, optional): Custom name for the guard. Default: `"rate_limit"`

**Returns:** None

---

#### `add_rate_limit_guard_for_set(wallet_set_id, max_per_minute=None, max_per_hour=None, max_per_day=None, name="rate_limit")`

Add a rate limit guard to a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Target wallet set ID
- `max_per_minute` (int | None, optional): Max transactions per minute
- `max_per_hour` (int | None, optional): Max transactions per hour
- `max_per_day` (int | None, optional): Max transactions per day
- `name` (str, optional): Custom name for the guard. Default: `"rate_limit"`

**Returns:** None

---

#### `add_confirm_guard(wallet_id, threshold=None, always_confirm=False, name="confirm")`

Add a confirmation guard to a wallet (Human-in-the-Loop).

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID
- `threshold` (str | Decimal | None, optional): Amount above which confirmation is required
- `always_confirm` (bool, optional): If True, require confirmation for ALL payments. Default: `False`
- `name` (str, optional): Custom name for the guard. Default: `"confirm"`

**Returns:** None

---

#### `add_confirm_guard_for_set(wallet_set_id, threshold=None, always_confirm=False, name="confirm")`

Add a confirmation guard to a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Target wallet set ID
- `threshold` (str | Decimal | None, optional): Amount above which confirmation is required
- `always_confirm` (bool, optional): If True, require confirmation for ALL payments. Default: `False`
- `name` (str, optional): Custom name for the guard. Default: `"confirm"`

**Returns:** None

---

#### `add_recipient_guard_for_set(wallet_set_id, mode="whitelist", addresses=None, patterns=None, domains=None, name="recipient")`

Add a Recipient Access Control guard to a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Target wallet set ID
- `mode` (str, optional): `'whitelist'` or `'blacklist'`. Default: `"whitelist"`
- `addresses` (list[str] | None, optional): List of allowed/blocked addresses
- `patterns` (list[str] | None, optional): List of regex patterns
- `domains` (list[str] | None, optional): List of allowed/blocked domains
- `name` (str, optional): Guard name. Default: `"recipient"`

**Returns:** None

---

#### `list_guards(wallet_id)`

List all guard names registered for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Target wallet ID

**Returns:** `list[str]` - List of guard names

---

#### `list_guards_for_set(wallet_set_id)`

List all guard names registered for a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Target wallet set ID

**Returns:** `list[str]` - List of guard names

---

## Wallet Management (`WalletService`)

Access via `client.wallet` property.

### `create_wallet_set(name)`

Create a new wallet set to contain wallets.

**Parameters:**
- `name` (str, **required**): Human-readable name for the wallet set

**Returns:** `WalletSetInfo` - Created wallet set info

---

### `list_wallet_sets()`

List all wallet sets.

**Parameters:** None

**Returns:** `list[WalletSetInfo]` - List of wallet sets

---

### `get_wallet_set(wallet_set_id)`

Get a wallet set by ID.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID

**Returns:** `WalletSetInfo` - Wallet set info

---

### `create_wallet(wallet_set_id, blockchain=None, account_type=AccountType.EOA)`

Create a new wallet in a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set to create wallet in
- `blockchain` (Network | str | None, optional): Blockchain network (defaults to config network)
- `account_type` (AccountType, optional): Account type (SCA for smart contract, EOA for native). Default: `AccountType.EOA`

**Returns:** `WalletInfo` - Created wallet info

---

### `create_wallets(wallet_set_id, count, blockchain=None, account_type=AccountType.EOA)`

Create multiple wallets in a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set to create wallets in
- `count` (int, **required**): Number of wallets to create (1-20)
- `blockchain` (Network | str | None, optional): Blockchain network
- `account_type` (AccountType, optional): Account type. Default: `AccountType.EOA`

**Returns:** `list[WalletInfo]` - List of created wallets

---

### `create_agent_wallet(agent_name, blockchain=None, count=1)`

Create wallet(s) for an AI agent.

**Parameters:**
- `agent_name` (str, **required**): Unique agent name (used as wallet set name with "agent-" prefix)
- `blockchain` (Network | str | None, optional): Blockchain network
- `count` (int, optional): Number of wallets to create. Default: `1`

**Returns:** `tuple[WalletSetInfo, WalletInfo | list[WalletInfo]]` - Wallet set and wallet(s)

**Example:**
```python
wallet_set, wallet = await client.wallet.create_agent_wallet("assistant-1")
# Or create multiple:
wallet_set, wallets = await client.wallet.create_agent_wallet("swarm-1", count=5)
```

---

### `create_user_wallet(user_id, blockchain=None, count=1)`

Create wallet(s) for an end user.

**Parameters:**
- `user_id` (str, **required**): Unique user identifier (used as wallet set name with "user-" prefix)
- `blockchain` (Network | str | None, optional): Blockchain network
- `count` (int, optional): Number of wallets to create. Default: `1`

**Returns:** `tuple[WalletSetInfo, WalletInfo | list[WalletInfo]]` - Wallet set and wallet(s)

---

### `get_wallet(wallet_id)`

Get a wallet by ID.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `WalletInfo` - Wallet info

---

### `list_wallets(wallet_set_id=None, blockchain=None)`

List wallets with optional filtering.

**Parameters:**
- `wallet_set_id` (str | None, optional): Filter by wallet set
- `blockchain` (Network | str | None, optional): Filter by blockchain

**Returns:** `list[WalletInfo]` - List of wallets

---

### `list_transactions(wallet_id=None, blockchain=None)`

List transactions with optional filtering.

**Parameters:**
- `wallet_id` (str | None, optional): Filter by wallet ID
- `blockchain` (Network | str | None, optional): Filter by blockchain

**Returns:** `list[TransactionInfo]` - List of transactions

---

### `get_balances(wallet_id)`

Get all token balances for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `list[Balance]` - List of token balances

---

### `get_usdc_balance(wallet_id)`

Get USDC balance object for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `Balance` - USDC balance object

---

### `get_usdc_balance_amount(wallet_id)`

Get USDC balance amount for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `Decimal` - USDC balance amount

---

### `transfer(from_wallet_id, to_address, amount, destination_chain=None, fee_level=FeeLevel.MEDIUM, idempotency_key=None, wait_for_completion=False, timeout_seconds=None)`

Transfer USDC between wallets or to external addresses.

**Parameters:**
- `from_wallet_id` (str, **required**): Source wallet ID
- `to_address` (str, **required**): Destination address or wallet ID
- `amount` (Decimal | str, **required**): Amount to transfer
- `destination_chain` (Network | str | None, optional): Destination blockchain
- `fee_level` (FeeLevel, optional): Fee level. Default: `FeeLevel.MEDIUM`
- `idempotency_key` (str | None, optional): Idempotency key
- `wait_for_completion` (bool, optional): Wait for blockchain confirmation. Default: `False`
- `timeout_seconds` (float | None, optional): Timeout for waiting

**Returns:** `TransferResult` - Transfer result with transaction info

**Raises:**
- `InsufficientBalanceError`: If wallet balance insufficient
- `WalletError`: If transfer fails

---

## Guards (`GuardManager`)

Access via `client.guards` property.

### `add_guard(wallet_id, guard)`

Add a guard for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID
- `guard` (Guard, **required**): Guard instance to add

**Returns:** `GuardManager` - Self for chaining

---

### `add_guard_for_set(wallet_set_id, guard)`

Add a guard for a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID
- `guard` (Guard, **required**): Guard instance to add

**Returns:** `GuardManager` - Self for chaining

---

### `remove_guard(wallet_id, guard_name)`

Remove a guard from a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID
- `guard_name` (str, **required**): Name of guard to remove

**Returns:** `GuardManager` - Self for chaining

---

### `remove_guard_from_set(wallet_set_id, guard_name)`

Remove a guard from a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID
- `guard_name` (str, **required**): Name of guard to remove

**Returns:** `GuardManager` - Self for chaining

---

### `get_wallet_guards(wallet_id)`

Get guards for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `list[Guard]` - List of guard instances

---

### `get_wallet_set_guards(wallet_set_id)`

Get guards for a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID

**Returns:** `list[Guard]` - List of guard instances

---

### `list_wallet_guard_names(wallet_id)`

List guard names for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** `list[str]` - List of guard names

---

### `list_wallet_set_guard_names(wallet_set_id)`

List guard names for a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID

**Returns:** `list[str]` - List of guard names

---

### `get_guard_chain(wallet_id, wallet_set_id=None)`

Get combined guard chain for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID
- `wallet_set_id` (str | None, optional): Wallet set ID

**Returns:** `GuardChain` - Combined guard chain

---

### `check(context)`

Check guards for a payment context.

**Parameters:**
- `context` (PaymentContext, **required**): Payment context to check

**Returns:** `tuple[bool, str, list[str]]` - (allowed, reason, passed_guards)

---

### `record_spending(wallet_id, wallet_set_id, amount, recipient, purpose)`

Record spending in all relevant guards.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID
- `wallet_set_id` (str | None, **required**): Wallet set ID (can be None)
- `amount` (Decimal, **required**): Amount spent
- `recipient` (str, **required**): Recipient address
- `purpose` (str | None, **required**): Purpose (can be None)

**Returns:** None

---

### `clear_wallet_guards(wallet_id)`

Clear all guards for a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID

**Returns:** None

---

### `clear_wallet_set_guards(wallet_set_id)`

Clear all guards for a wallet set.

**Parameters:**
- `wallet_set_id` (str, **required**): Wallet set ID

**Returns:** None

---

## Ledger (`Ledger`)

Access via `client.ledger` property.

### `record(entry)`

Record a transaction.

**Parameters:**
- `entry` (LedgerEntry, **required**): Ledger entry to record

**Returns:** `str` - Entry ID

---

### `get(entry_id)`

Get entry by ID.

**Parameters:**
- `entry_id` (str, **required**): Entry ID

**Returns:** `LedgerEntry | None` - Ledger entry or None if not found

---

### `update_status(entry_id, status, tx_hash=None, metadata_updates=None)`

Update entry status and metadata.

**Parameters:**
- `entry_id` (str, **required**): Entry ID
- `status` (LedgerEntryStatus, **required**): New status
- `tx_hash` (str | None, optional): Transaction hash
- `metadata_updates` (dict[str, Any] | None, optional): Metadata updates to merge

**Returns:** `bool` - True if updated, False if not found

---

### `query(wallet_id=None, wallet_set_id=None, recipient=None, entry_type=None, status=None, from_date=None, to_date=None, limit=100)`

Query ledger entries.

**Parameters:**
- `wallet_id` (str | None, optional): Filter by wallet
- `wallet_set_id` (str | None, optional): Filter by wallet set
- `recipient` (str | None, optional): Filter by recipient
- `entry_type` (LedgerEntryType | None, optional): Filter by type
- `status` (LedgerEntryStatus | None, optional): Filter by status
- `from_date` (datetime | None, optional): Start date
- `to_date` (datetime | None, optional): End date
- `limit` (int, optional): Max results. Default: `100`

**Returns:** `list[LedgerEntry]` - Filtered ledger entries

---

### `get_total_spent(wallet_id, from_date=None)`

Get total amount spent by a wallet.

**Parameters:**
- `wallet_id` (str, **required**): Wallet ID
- `from_date` (datetime | None, optional): Optional start date

**Returns:** `Decimal` - Total spent amount

---

### `clear()`

Clear all ledger entries.

**Parameters:** None

**Returns:** `int` - Number of entries cleared

---

## Payment Intents (`PaymentIntentService`)

Access via `client.intents` property.

### `create(wallet_id, recipient, amount, currency="USDC", metadata=None, client_secret=None)`

Create a new payment intent.

**Parameters:**
- `wallet_id` (str, **required**): Source wallet ID
- `recipient` (str, **required**): Payment recipient
- `amount` (Decimal, **required**): Amount to pay
- `currency` (str, optional): Currency code. Default: `"USDC"`
- `metadata` (dict[str, Any] | None, optional): Additional metadata
- `client_secret` (str | None, optional): Client secret for future use

**Returns:** `PaymentIntent` - Created payment intent

---

### `get(intent_id)`

Get intent by ID.

**Parameters:**
- `intent_id` (str, **required**): Intent ID

**Returns:** `PaymentIntent | None` - Payment intent or None

---

### `update_status(intent_id, status)`

Update intent status.

**Parameters:**
- `intent_id` (str, **required**): Intent ID
- `status` (PaymentIntentStatus, **required**): New status

**Returns:** `PaymentIntent` - Updated payment intent

**Raises:**
- `ValidationError`: If intent not found

---

## Webhooks (`WebhookParser`)

Access via `client.webhooks` property.

### `__init__(verification_key=None)`

Initialize webhook parser.

**Parameters:**
- `verification_key` (str | None, optional): Public key for signature verification (PEM, Hex, or Base64)

---

### `verify_signature(payload, headers)`

Verify the webhook signature.

**Parameters:**
- `payload` (str | bytes, **required**): Raw request body
- `headers` (Mapping[str, str], **required**): Request headers

**Returns:** `bool` - True if valid

**Raises:**
- `InvalidSignatureError`: If signature invalid or missing

---

### `handle(payload, headers)`

Parse and validate a webhook request.

**Parameters:**
- `payload` (str | bytes | dict[str, Any], **required**): Raw body or parsed dict
- `headers` (Mapping[str, str], **required**): Request headers

**Returns:** `WebhookEvent` - Parsed webhook event

**Raises:**
- `InvalidSignatureError`: If signature invalid
- `ValidationError`: If payload malformed

**Example:**
```python
# Flask example
@app.route('/webhooks/circle', methods=['POST'])
def handle_webhook():
    event = client.webhooks.handle(
        payload=request.data,
        headers=request.headers
    )
    
    if event.type == NotificationType.PAYMENT_COMPLETED:
        # Handle payment completion
        pass
        
    return '', 200
```

---

## Data Types

### Common Types

- `Network`: Enum for blockchain networks (`ARC_TESTNET`, `ARB_SEPOLIA`, `POLYGON_AMOY`, etc.)
- `FeeLevel`: Enum for fee levels (`LOW`, `MEDIUM`, `HIGH`)
- `AccountType`: Enum for wallet types (`EOA`, `SCA`)
- `PaymentMethod`: Enum for payment methods (`TRANSFER`, `X402`, `GATEWAY`)
- `PaymentStatus`: Enum for payment statuses (`PENDING`, `COMPLETED`, `FAILED`, `BLOCKED`, `CANCELLED`)
- `PaymentIntentStatus`: Enum for intent statuses (`REQUIRES_CONFIRMATION`, `PROCESSING`, `SUCCEEDED`, `FAILED`, `CANCELED`)
- `LedgerEntryStatus`: Enum for ledger statuses (`PENDING`, `COMPLETED`, `FAILED`, `CANCELLED`, `BLOCKED`)
- `NotificationType`: Enum for webhook event types (`PAYMENT_COMPLETED`, `PAYMENT_FAILED`, `PAYMENT_CANCELED`, `UNKNOWN`)

### Data Classes

- `WalletInfo`: Wallet information
- `WalletSetInfo`: Wallet set information
- `Balance`: Token balance
- `TransactionInfo`: Transaction details
- `PaymentRequest`: Payment request data
- `PaymentResult`: Payment execution result
- `SimulationResult`: Payment simulation result
- `PaymentIntent`: Payment intent data
- `BatchPaymentResult`: Batch payment results
- `LedgerEntry`: Ledger entry data
- `PaymentContext`: Guard payment context
- `GuardResult`: Guard check result
- `WebhookEvent`: Webhook event data

---

## Error Handling

All SDK methods may raise these exceptions:

- `OmniClawError`: Base exception for all SDK errors
- `ConfigurationError`: Configuration or setup errors
- `WalletError`: Wallet operation errors
- `PaymentError`: Payment execution errors
- `GuardError`: Guard check failures
- `InsufficientBalanceError`: Insufficient wallet balance
- `ValidationError`: Input validation errors
- `NetworkError`: Network/API communication errors
- `ProtocolError`: Protocol adapter errors
- `X402Error`: X402 protocol-specific errors
- `InvalidSignatureError`: Webhook signature verification failures

**Example:**
```python
from omniclaw import OmniClaw, PaymentError, InsufficientBalanceError
from decimal import Decimal

client = OmniClaw()

try:
    result = await client.pay(
        wallet_id="wallet-123",
        recipient="0x...",
        amount=Decimal("100.00")
    )
except InsufficientBalanceError as e:
    print(f"Not enough funds: {e}")
except PaymentError as e:
    print(f"Payment failed: {e}")
```

---

## Complete Usage Example

```python
from omniclaw import OmniClaw, quick_setup, BudgetGuard, Network
from decimal import Decimal

# One-time setup
quick_setup("YOUR_CIRCLE_API_KEY")

# Initialize client
async def main():
    client = OmniClaw(
        network=Network.ARC_TESTNET,
        log_level="DEBUG"
    )
    
    # Create wallet for agent
    wallet_set, wallet = await client.wallet.create_agent_wallet("assistant-1")
    print(f"Created wallet: {wallet.id}")
    
    # Add budget guard
    await client.add_budget_guard(
        wallet_id=wallet.id,
        daily_limit=Decimal("100.00"),
        hourly_limit=Decimal("20.00")
    )
    
    # Execute payment
    result = await client.pay(
        wallet_id=wallet.id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f0b4cb",
        amount=Decimal("10.00"),
        purpose="API subscription"
    )
    
    if result.success:
        print(f"Payment successful! TX: {result.blockchain_tx}")
    else:
        print(f"Payment failed: {result.error}")
    
    # Check balance
    balance = await client.get_balance(wallet.id)
    print(f"Remaining balance: ${balance}")
    
    # Query ledger
    entries = await client.ledger.query(
        wallet_id=wallet.id,
        limit=10
    )
    for entry in entries:
        print(f"{entry.timestamp}: ${entry.amount} to {entry.recipient}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

**For more information, see:**
- [SDK Usage Guide](SDK_USAGE_GUIDE.md)
- [Vision Document](OMNICLAW_VISION.md)
- [Main README](../README.md)
