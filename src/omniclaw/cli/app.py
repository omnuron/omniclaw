from __future__ import annotations

import os
import warnings

import typer

from .commands import configure as configure_cmd
from .commands import confirmations as confirmations_cmd
from .commands import intents as intents_cmd
from .commands import ledger as ledger_cmd
from .commands import payments as payments_cmd
from .commands import status as status_cmd
from .commands import wallet as wallet_cmd
from .config import is_quiet

# Aggressively suppress noisy deprecation warnings from downstream dependencies (e.g. web3, circle-sdk)
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="web3")

app = typer.Typer(
    help=(
        "omniclaw-cli - zero-trust execution layer for policy-controlled agent payments "
        "and x402 buyer flows"
    )
)

BANNER = r"""
   ____  __  __ _   _ ___ ____ _        ___        __
  / __ \|  \/  | \ | |_ _/ ___| |      / \ \      / /
 | |  | | |\/| |  \| || | |   | |     / _ \ \ /\ / /
 | |__| | |  | | |\  || | |___| |___ / ___ \ V  V /
  \____/|_|  |_|_| \_|___\____|_____/_/   \_\_/\_/

  Economic Execution and Control Layer for Agentic Systems
"""


def print_banner() -> None:
    """Print the OmniClaw CLI banner."""
    typer.echo(typer.style(BANNER, fg=typer.colors.CYAN, bold=True))


@app.callback()
def callback() -> None:
    """Show banner on startup."""
    if is_quiet():
        return
    if str(os.environ.get("OMNICLAW_CLI_NO_BANNER", "")).strip().lower() in {"1", "true", "yes"}:
        return
    print_banner()


wallet_app = typer.Typer(help="Wallet operations")
payments_app = None
intents_app = typer.Typer(help="Payment intents")
ledger_app = None
confirmations_app = typer.Typer(help="Manage pending confirmations (owner only)")
status_app = None

configure_cmd.register(app)
wallet_cmd.register(app, wallet_app)
payments_cmd.register(app)
intents_cmd.register(app, intents_app)
ledger_cmd.register(app)
confirmations_cmd.register(app, confirmations_app)
status_cmd.register(app)

app.add_typer(wallet_app, name="wallet")
app.add_typer(intents_app, name="intents")
app.add_typer(confirmations_app, name="confirmations")
# Note: grouping under pay/ledger/status previously shadowed top-level commands.


def main() -> int:
    """Main entry point."""
    return app()
