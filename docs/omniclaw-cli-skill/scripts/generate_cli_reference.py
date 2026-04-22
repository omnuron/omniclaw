#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HUMAN_REF = REPO_ROOT / "docs" / "cli-reference.md"

COMMANDS = [
    ("omniclaw-cli --help", ["omniclaw-cli", "--help"]),
    ("omniclaw-cli configure --help", ["omniclaw-cli", "configure", "--help"]),
    ("omniclaw-cli status --help", ["omniclaw-cli", "status", "--help"]),
    ("omniclaw-cli ping --help", ["omniclaw-cli", "ping", "--help"]),
    ("omniclaw-cli address --help", ["omniclaw-cli", "address", "--help"]),
    ("omniclaw-cli balance --help", ["omniclaw-cli", "balance", "--help"]),
    ("omniclaw-cli balance-detail --help", ["omniclaw-cli", "balance-detail", "--help"]),
    ("omniclaw-cli can-pay --help", ["omniclaw-cli", "can-pay", "--help"]),
    ("omniclaw-cli inspect-x402 --help", ["omniclaw-cli", "inspect-x402", "--help"]),
    ("omniclaw-cli simulate --help", ["omniclaw-cli", "simulate", "--help"]),
    ("omniclaw-cli pay --help", ["omniclaw-cli", "pay", "--help"]),
    ("omniclaw-cli deposit --help", ["omniclaw-cli", "deposit", "--help"]),
    ("omniclaw-cli withdraw --help", ["omniclaw-cli", "withdraw", "--help"]),
    ("omniclaw-cli withdraw-trustless --help", ["omniclaw-cli", "withdraw-trustless", "--help"]),
    ("omniclaw-cli withdraw-trustless-complete --help", ["omniclaw-cli", "withdraw-trustless-complete", "--help"]),
    ("omniclaw-cli serve --help", ["omniclaw-cli", "serve", "--help"]),
    ("omniclaw-cli create-intent --help", ["omniclaw-cli", "create-intent", "--help"]),
    ("omniclaw-cli confirm-intent --help", ["omniclaw-cli", "confirm-intent", "--help"]),
    ("omniclaw-cli get-intent --help", ["omniclaw-cli", "get-intent", "--help"]),
    ("omniclaw-cli cancel-intent --help", ["omniclaw-cli", "cancel-intent", "--help"]),
    ("omniclaw-cli ledger --help", ["omniclaw-cli", "ledger", "--help"]),
    ("omniclaw-cli list-tx --help", ["omniclaw-cli", "list-tx", "--help"]),
    ("omniclaw-cli confirmations --help", ["omniclaw-cli", "confirmations", "--help"]),
    ("omniclaw-cli confirmations get --help", ["omniclaw-cli", "confirmations", "get", "--help"]),
    ("omniclaw-cli confirmations approve --help", ["omniclaw-cli", "confirmations", "approve", "--help"]),
    ("omniclaw-cli confirmations deny --help", ["omniclaw-cli", "confirmations", "deny", "--help"]),
]

FALLBACK_OUTPUTS = {
    "omniclaw-cli balance --help": """\
Usage: omniclaw-cli balance [OPTIONS]

Get wallet balance.

Options:
  --help  Show this message and exit.
""",
    "omniclaw-cli balance-detail --help": """\
Usage: omniclaw-cli balance-detail [OPTIONS]

Get detailed balance including Gateway and Circle wallet.

Options:
  --help  Show this message and exit.
""",
}

TIMEOUT_SECONDS = 25

HEADER = """# OmniClaw CLI Reference

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
omniclaw-cli pay \\
  --recipient 0xRecipientAddress \\
  --amount 5.00 \\
  --purpose "service payment" \\
  --idempotency-key job-123
```

Seller exposing a paid endpoint:

```bash
omniclaw-cli serve \\
  --price 0.01 \\
  --endpoint /api/data \\
  --exec "python safe_readonly_service.py" \\
  --port 8000
```

Only run this after the owner explicitly asks for an agent-run seller endpoint and supplies or approves the `--exec` command.

## Live Help Output
"""


def run_help(title: str, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env={"OMNICLAW_CLI_NO_BANNER": "1", **os.environ},
        )
    except subprocess.TimeoutExpired:
        fallback = FALLBACK_OUTPUTS.get(title)
        if fallback:
            return f"{fallback.rstrip()}\n\n[live help timed out after {TIMEOUT_SECONDS}s; schema filled from source]"
        return f"[help command timed out after {TIMEOUT_SECONDS}s]"

    output = (proc.stdout or "").rstrip()
    if proc.returncode == 0:
        return output

    if output:
        return f"{output}\n\n[exit code: {proc.returncode}]"
    return f"[help command failed with exit code {proc.returncode}]"


sections: list[str] = [HEADER.rstrip()]
for title, args in COMMANDS:
    output = run_help(title, args)
    sections.append(f"### `{title}`\n\n```text\n{output}\n```")

content = "\n\n".join(sections) + "\n"
HUMAN_REF.write_text(content)
print(f"wrote {HUMAN_REF}")
