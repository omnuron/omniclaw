# OmniClaw Policy Reference

This guide explains all possible policy.json configuration options.
Policy files are strictly validated on startup; unknown fields or invalid types will fail server initialization.
On startup, policy limits are converted into persistent guard rules (Budget/Rate/Recipient/SingleTx/Confirm) and enforced on every payment.

Hot reload:
- Set `OMNICLAW_POLICY_RELOAD_INTERVAL` (seconds) to auto-reload policy.json without restart.

---

## Simple vs Advanced

### Simple Policy (Minimal)
```json
{
  "version": "2.0",
  "tokens": {
    "my-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "My Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Primary Wallet",
      "limits": {
        "daily_max": "100.00",
        "per_tx_max": "50.00"
      },
      "recipients": {
        "mode": "allow_all"
      },
      "rails": {
        "circle_transfer": true,
        "x402_exact": true,
        "gateway": true
      }
    }
  }
}
```

### Advanced Policy (Full Control)
```json
{
  "version": "2.0",
  "tokens": {
    "buyer-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "Buyer Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Primary Wallet",
      "limits": {
        "daily_max": "1000.00",
        "hourly_max": "200.00",
        "per_tx_max": "100.00",
        "per_tx_min": "0.01"
      },
      "rate_limits": {
        "per_minute": 10,
        "per_hour": 100
      },
      "recipients": {
        "mode": "whitelist",
        "addresses": ["0xSeller1...", "0xSeller2..."],
        "domains": ["api.service-a.com"]
      },
      "rails": {
        "circle_transfer": true,
        "x402_exact": true,
        "gateway": true
      },
      "confirm_threshold": "50.00"
    }
  }
}
```

---

## Complete Field Reference

### Top-Level

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Policy format version (use "2.0") |
| `tokens` | object | Yes | Agent token mappings |
| `wallets` | object | Yes | Wallet configurations |
| `limits` | object | No | Global/default limits (optional) |
| `rate_limits` | object | No | Global/default rate limits (optional) |
| `recipients` | object | No | Global/default recipient rules (optional) |
| `confirm_threshold` | decimal | No | Global/default confirm threshold |

### tokens.{token_name}

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `wallet_alias` | string | Yes | Which wallet config to use |
| `active` | boolean | Yes | Is this token active |
| `label` | string | No | Human-readable label |

### wallets.{wallet_alias}

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Wallet name |
| `wallet_id` | string | Optional existing Circle Developer Wallet ID |
| `address` | string | Optional expected Circle Developer Wallet address |
| `limits` | object | Spending limits |
| `rate_limits` | object | Rate limits |
| `recipients` | object | Recipient rules |
| `rails` | object | Buyer payment rails enabled for this wallet |
| `confirm_threshold` | decimal | Amount requiring owner confirmation |

### limits

| Field | Type | Description |
|-------|------|-------------|
| `daily_max` | string (decimal) | Maximum spending per day |
| `hourly_max` | string (decimal) | Maximum spending per hour |
| `per_tx_max` | string (decimal) | Maximum per transaction |
| `per_tx_min` | string (decimal) | Minimum per transaction |

### rate_limits

| Field | Type | Description |
|-------|------|-------------|
| `per_minute` | integer | Max transactions per minute |
| `per_hour` | integer | Max transactions per hour |

### recipients

| Field | Type | Description |
|-------|------|-------------|
| `mode` | string | "whitelist", "blacklist", or "allow_all" |
| `addresses` | array | List of allowed/blocked addresses |
| `domains` | array | List of allowed/blocked domains (for x402 URLs) |

### rails

| Field | Type | Description |
|-------|------|-------------|
| `circle_transfer` | boolean | Allow direct Circle Developer Wallet transfers |
| `gateway` | boolean | Allow Circle Gateway routes |
| `x402_exact` | boolean | Allow direct x402 exact payments signed by `OMNICLAW_PRIVATE_KEY` |

Generated Circle wallet IDs and EOA addresses are stored in `OMNICLAW_AGENT_STATE_PATH`, not in `policy.json`. Keep policy files stable and reviewable.

---

## Recipient Modes

### mode: "allow_all"
Agent can pay anyone. No restrictions.

```json
"recipients": {
  "mode": "allow_all"
}
```

### mode: "whitelist"
Agent can ONLY pay these addresses/domains.

```json
"recipients": {
  "mode": "whitelist",
  "addresses": ["0x123...", "0x456..."],
  "domains": ["api.service.com"]
}
```

### mode: "blacklist"
Agent can pay everyone EXCEPT these addresses/domains.

```json
"recipients": {
  "mode": "blacklist",
  "addresses": ["0xBanned..."],
  "domains": ["malicious.com"]
}
```

---

## Examples

### Strict Agent (Can Only Pay Specific Sellers)
```json
{
  "version": "2.0",
  "tokens": {
    "strict-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "Strict Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Strict Wallet",
      "limits": {
        "daily_max": "50.00",
        "per_tx_max": "10.00"
      },
      "recipients": {
        "mode": "whitelist",
        "addresses": ["0xTrustedSeller1...", "0xTrustedSeller2..."]
      }
    }
  }
}
```

### Open Agent (Can Pay Anyone, Limited Budget)
```json
{
  "version": "2.0",
  "tokens": {
    "open-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "Open Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Open Wallet",
      "limits": {
        "daily_max": "100.00",
        "per_tx_max": "25.00"
      },
      "recipients": {
        "mode": "allow_all"
      }
    }
  }
}
```

### High-Volume Agent (Rate Limited, High Budget)
```json
{
  "version": "2.0",
  "tokens": {
    "high-volume-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "High Volume Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "High Volume Wallet",
      "limits": {
        "daily_max": "10000.00",
        "hourly_max": "2000.00",
        "per_tx_max": "500.00",
        "per_tx_min": "0.10"
      },
      "rate_limits": {
        "per_minute": 60,
        "per_hour": 1000
      },
      "recipients": {
        "mode": "allow_all"
      }
    }
  }
}
```

### Receive-Only Agent
```json
{
  "version": "2.0",
  "tokens": {
    "receive-only-agent": {
      "wallet_alias": "primary",
      "active": true,
      "label": "Receive-Only Agent"
    }
  },
  "wallets": {
    "primary": {
      "name": "Receive-Only Wallet",
      "limits": {
        "daily_max": "0",
        "per_tx_max": "0"
      }
    }
  }
}
```

---

## SDK Environment Guard Defaults

When using the SDK directly, you can set default guard limits via environment variables:

```bash
export OMNICLAW_DAILY_BUDGET="100.00"
export OMNICLAW_HOURLY_BUDGET="50.00"
export OMNICLAW_TX_LIMIT="25.00"
export OMNICLAW_RATE_LIMIT_PER_MIN="10"
```

The buyer server applies `policy.json` as its source of truth. Put server-side
agent limits in the policy file.

---

## Files

- Simple: `examples/policy-simple.json`
- Advanced: `examples/policy-advanced.json`
- Default: `examples/default-policy.json`
- Buyer server template: `examples/agent/buyer/policy.example.json`
