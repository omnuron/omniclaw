# OmniClaw CLI Reference

This file is generated from the live `omniclaw-cli --help` surface.
Do not hand-edit command schemas here; regenerate instead.

Generator:

```bash
python3 scripts/generate_cli_reference.py
```

## Usage Notes

- same CLI, two roles: buyer uses `pay`, seller uses `serve`
- use `can-pay` before a new recipient when policy allow/deny matters
- use `inspect-x402` before a new paid URL when you need to see seller requirements and buyer funding readiness
- use `balance-detail` when Gateway state matters
- use `--idempotency-key` for job-based payments
- for x402 URLs, `--amount` can be omitted because the payment requirements come from the seller endpoint
- `serve` is for owner-approved agent-run seller endpoints only
- `serve` binds to `0.0.0.0` even if the banner prints `localhost`
- `serve --exec` runs a host command; do not invent the command or expose it outside an isolated runtime

## Example Flows

Buyer paying an x402 endpoint:

```bash
omniclaw-cli can-pay --recipient http://seller-host:8000/api/data
omniclaw-cli inspect-x402 --recipient http://seller-host:8000/api/data
omniclaw-cli pay --recipient http://seller-host:8000/api/data --idempotency-key job-123
```

Buyer paying a direct address:

```bash
omniclaw-cli pay \
  --recipient 0xRecipientAddress \
  --amount 5.00 \
  --purpose "service payment" \
  --idempotency-key job-123
```

Seller exposing a paid endpoint:

```bash
omniclaw-cli serve \
  --price 0.01 \
  --endpoint /api/data \
  --exec "python safe_readonly_service.py" \
  --port 8000
```

Only run this after the owner explicitly asks for an agent-run seller endpoint and supplies or approves the `--exec` command.

## Live Help Output

### `omniclaw-cli --help`

```text
                                                                                
 Usage: omniclaw-cli [OPTIONS] COMMAND [ARGS]...                                
                                                                                
 omniclaw-cli - zero-trust execution layer for policy-controlled agent          
 payments, x402 services, and agentic commerce                                  
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ configure                     Configure omniclaw-cli with server details.    │
│ address                       Get wallet address.                            │
│ balance                       Get wallet balance.                            │
│ balance-detail                Get detailed balance including Gateway and     │
│                               Circle wallet.                                 │
│ balance_detail                Alias for balance-detail                       │
│ deposit                       Deposit USDC from EOA to Gateway wallet.       │
│ withdraw                      Withdraw USDC from Gateway to Circle Developer │
│                               Wallet.                                        │
│ withdraw-trustless            Initiate trustless withdrawal (~7-day delay,   │
│                               no API needed).                                │
│ withdraw_trustless            Alias for withdraw-trustless                   │
│ withdraw-trustless-complete   Complete a trustless withdrawal after the      │
│                               delay has passed.                              │
│ withdraw_trustless_complete   Alias for withdraw-trustless-complete          │
│ pay                           Execute a payment or pay for an x402 service.  │
│ simulate                      Simulate a payment without executing.          │
│ inspect-x402                  Inspect an x402 endpoint and show which        │
│                               payment route OmniClaw would use.              │
│ inspect_x402                  Alias for inspect-x402                         │
│ can-pay                       Check if recipient is allowed.                 │
│ can_pay                       Alias for can-pay                              │
│ create-intent                 Create a payment intent (authorize).           │
│ create_intent                 Alias for create-intent                        │
│ confirm-intent                Confirm a payment intent (capture).            │
│ confirm_intent                Alias for confirm-intent                       │
│ get-intent                    Get a payment intent.                          │
│ get_intent                    Alias for get-intent                           │
│ cancel-intent                 Cancel a payment intent.                       │
│ cancel_intent                 Alias for cancel-intent                        │
│ ledger                        List transaction history.                      │
│ list-tx                       List transaction history.                      │
│ list_tx                       Alias for list-tx                              │
│ serve                         Expose a local service behind an x402 payment  │
│                               gate.                                          │
│ status                        Get agent status and health.                   │
│ ping                          Health check.                                  │
│ wallet                        Wallet operations                              │
│ intents                       Payment intents                                │
│ confirmations                 Manage pending confirmations (owner only)      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli configure --help`

```text
                                                                                
 Usage: omniclaw-cli configure [OPTIONS]                                        
                                                                                
 Configure omniclaw-cli with server details.                                    
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --server-url         TEXT  OmniClaw Financial Policy Engine URL              │
│ --token              TEXT  Agent token                                       │
│ --wallet             TEXT  Wallet alias                                      │
│ --owner-token        TEXT  Owner token                                       │
│ --show                     Show current config                               │
│ --show-raw                 Show raw secrets                                  │
│ --interactive              Prompt for missing values                         │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli status --help`

```text
                                                                                
 Usage: omniclaw-cli status [OPTIONS]                                           
                                                                                
 Get agent status and health.                                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli ping --help`

```text
                                                                                
 Usage: omniclaw-cli ping [OPTIONS]                                             
                                                                                
 Health check.                                                                  
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli address --help`

```text
                                                                                
 Usage: omniclaw-cli address [OPTIONS]                                          
                                                                                
 Get wallet address.                                                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli balance --help`

```text
                                                                                
 Usage: omniclaw-cli balance [OPTIONS]                                          
                                                                                
 Get wallet balance.                                                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli balance-detail --help`

```text
                                                                                
 Usage: omniclaw-cli balance-detail [OPTIONS]                                   
                                                                                
 Get detailed balance including Gateway and Circle wallet.                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli can-pay --help`

```text
                                                                                
 Usage: omniclaw-cli can-pay [OPTIONS]                                          
                                                                                
 Check if recipient is allowed.                                                 
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --recipient        TEXT  Recipient to check [required]                    │
│    --help                   Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli inspect-x402 --help`

```text
                                                                                
 Usage: omniclaw-cli inspect-x402 [OPTIONS]                                     
                                                                                
 Inspect an x402 endpoint and show which payment route OmniClaw would use.      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --recipient        TEXT  x402 URL to inspect [required]                  │
│    --amount           TEXT  Optional max amount in USDC                     │
│    --method           TEXT  HTTP method for x402 requests [default: GET]    │
│    --body             TEXT  Request body for x402 requests                  │
│    --header           TEXT  Additional headers for x402 requests            │
│    --help                   Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli simulate --help`

```text
                                                                                
 Usage: omniclaw-cli simulate [OPTIONS]                                         
                                                                                
 Simulate a payment without executing.                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --recipient                TEXT  Recipient to simulate [required]         │
│ *  --amount                   TEXT  Amount to simulate [required]            │
│    --idempotency-key          TEXT  Idempotency key                          │
│    --destination-chain        TEXT  Target network                           │
│    --fee-level                TEXT  Gas fee level (LOW, MEDIUM, HIGH)        │
│    --check-trust                    Run Trust Gate check                     │
│    --skip-guards                    Skip guards (OWNER ONLY)                 │
│    --help                           Show this message and exit.              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli pay --help`

```text
                                                                                
 Usage: omniclaw-cli pay [OPTIONS]                                              
                                                                                
 Execute a payment or pay for an x402 service.                                  
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --recipient                TEXT  Payment recipient (address or URL)       │
│                                     [required]                               │
│    --amount                   TEXT  Amount in USDC (optional for x402 URLs)  │
│    --purpose                  TEXT  Payment purpose                          │
│    --idempotency-key          TEXT  Idempotency key                          │
│    --destination-chain        TEXT  Target network                           │
│    --fee-level                TEXT  Gas fee level (LOW, MEDIUM, HIGH)        │
│    --check-trust                    Run Trust Gate check                     │
│    --skip-guards                    Skip guards (OWNER ONLY)                 │
│    --method                   TEXT  HTTP method for x402 requests            │
│                                     [default: GET]                           │
│    --body                     TEXT  JSON body for x402 requests              │
│    --header                   TEXT  Additional headers for x402 requests     │
│    --output                   TEXT  Save response to file                    │
│    --dry-run                        Simulate first                           │
│    --help                           Show this message and exit.              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli deposit --help`

```text
                                                                                
 Usage: omniclaw-cli deposit [OPTIONS]                                          
                                                                                
 Deposit USDC from EOA to Gateway wallet.                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --amount        TEXT  Amount in USDC to deposit to Gateway [required]     │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli withdraw --help`

```text
                                                                                
 Usage: omniclaw-cli withdraw [OPTIONS]                                         
                                                                                
 Withdraw USDC from Gateway to Circle Developer Wallet.                         
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --amount        TEXT  Amount in USDC to withdraw from Gateway [required]  │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli withdraw-trustless --help`

```text
                                                                                
 Usage: omniclaw-cli withdraw-trustless [OPTIONS]                               
                                                                                
 Initiate trustless withdrawal (~7-day delay, no API needed).                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --amount        TEXT  Amount in USDC to withdraw (trustless, ~7-day       │
│                          delay)                                              │
│                          [required]                                          │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli withdraw-trustless-complete --help`

```text
                                                                                
 Usage: omniclaw-cli withdraw-trustless-complete [OPTIONS]                      
                                                                                
 Complete a trustless withdrawal after the delay has passed.                    
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli serve --help`

```text
                                                                                
 Usage: omniclaw-cli serve [OPTIONS]                                            
                                                                                
 Expose a local service behind an x402 payment gate.                            
                                                                                
 Uses the production GatewayMiddleware for full x402 v2 protocol compliance:    
 - Returns proper 402 responses with all required fields                        
 - Parses PAYMENT-SIGNATURE headers                                             
 - Settles atomically via Circle Gateway /settle                                
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --price           FLOAT    Price per request in USDC [required]           │
│ *  --endpoint        TEXT     Endpoint path to expose [required]             │
│ *  --exec            TEXT     Command to execute on success [required]       │
│    --port            INTEGER  Local port to listen on [default: 8000]        │
│    --help                     Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli create-intent --help`

```text
                                                                                
 Usage: omniclaw-cli create-intent [OPTIONS]                                    
                                                                                
 Create a payment intent (authorize).                                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --recipient                TEXT     Recipient [required]                  │
│ *  --amount                   TEXT     Amount [required]                     │
│    --purpose                  TEXT     Purpose                               │
│    --expires-in               INTEGER  Expiry in seconds                     │
│    --idempotency-key          TEXT     Idempotency key                       │
│    --destination-chain        TEXT     Target network                        │
│    --fee-level                TEXT     Gas fee level (LOW, MEDIUM, HIGH)     │
│    --check-trust                       Run Trust Gate check                  │
│    --skip-guards                       Skip guards (OWNER ONLY)              │
│    --help                              Show this message and exit.           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli confirm-intent --help`

```text
                                                                                
 Usage: omniclaw-cli confirm-intent [OPTIONS]                                   
                                                                                
 Confirm a payment intent (capture).                                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --intent-id        TEXT  Intent ID to confirm [required]                  │
│    --help                   Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli get-intent --help`

```text
                                                                                
 Usage: omniclaw-cli get-intent [OPTIONS]                                       
                                                                                
 Get a payment intent.                                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --intent-id        TEXT  Intent ID to fetch [required]                    │
│    --help                   Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli cancel-intent --help`

```text
                                                                                
 Usage: omniclaw-cli cancel-intent [OPTIONS]                                    
                                                                                
 Cancel a payment intent.                                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --intent-id        TEXT  Intent ID to cancel [required]                   │
│    --reason           TEXT  Cancel reason                                    │
│    --help                   Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli ledger --help`

```text
                                                                                
 Usage: omniclaw-cli ledger [OPTIONS]                                           
                                                                                
 List transaction history.                                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit        INTEGER  Number of transactions to fetch [default: 20]        │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli list-tx --help`

```text
                                                                                
 Usage: omniclaw-cli list-tx [OPTIONS]                                          
                                                                                
 List transaction history.                                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit        INTEGER  Number of transactions to fetch [default: 20]        │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli confirmations --help`

```text
                                                                                
 Usage: omniclaw-cli confirmations [OPTIONS] COMMAND [ARGS]...                  
                                                                                
 Manage pending confirmations (owner only)                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ get       Get confirmation details.                                          │
│ approve   Approve a confirmation.                                            │
│ deny      Deny a confirmation.                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli confirmations get --help`

```text
                                                                                
 Usage: omniclaw-cli confirmations get [OPTIONS]                                
                                                                                
 Get confirmation details.                                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --id          TEXT  Confirmation ID [required]                            │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli confirmations approve --help`

```text
                                                                                
 Usage: omniclaw-cli confirmations approve [OPTIONS]                            
                                                                                
 Approve a confirmation.                                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --id          TEXT  Confirmation ID [required]                            │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `omniclaw-cli confirmations deny --help`

```text
                                                                                
 Usage: omniclaw-cli confirmations deny [OPTIONS]                               
                                                                                
 Deny a confirmation.                                                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --id          TEXT  Confirmation ID [required]                            │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```
