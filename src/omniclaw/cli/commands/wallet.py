from __future__ import annotations

import json
from typing import Any

import httpx
import typer

from ..config import get_client, is_quiet


def address() -> dict[str, Any]:
    """Get wallet address."""
    client = get_client()

    try:
        response = client.get("/api/v1/address")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def balance() -> dict[str, Any]:
    """Get wallet balance."""
    client = get_client()

    try:
        response = client.get("/api/v1/balance")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        typer.echo(f"Error: {detail}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def balance_detail() -> dict[str, Any]:
    """Get detailed balance including Gateway and Circle wallet."""
    client = get_client()

    try:
        response = client.get("/api/v1/balance-detail")
        response.raise_for_status()
        data = response.json()

        if is_quiet():
            typer.echo(json.dumps(data, indent=2))
        else:
            typer.echo("=== WALLET BALANCE ===")
            typer.echo(f"EOA Address: {data.get('eoa_address')}")
            typer.echo(f"Gateway Balance: {data.get('gateway_balance')} USDC")
            typer.echo(f"Circle Wallet: {data.get('circle_wallet_balance')} USDC")

        return data
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        typer.echo(f"Error: {detail}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def balance_detail_alias() -> dict[str, Any]:
    """Alias for balance-detail."""
    return balance_detail()


def deposit_address() -> dict[str, Any]:
    """Get the EOA address to fund before Gateway deposits."""
    client = get_client()

    try:
        response = client.get("/api/v1/deposit-address")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def deposit_address_alias() -> dict[str, Any]:
    """Alias for deposit-address."""
    return deposit_address()


def deposit(
    amount: str = typer.Option(..., "--amount", help="Amount in USDC to deposit to Gateway"),
    check_gas: bool = typer.Option(False, "--check-gas", help="Check gas balance first"),
    skip_if_insufficient_gas: bool = typer.Option(
        True,
        "--skip-if-insufficient-gas/--no-skip-if-insufficient-gas",
        help="Skip deposit when gas is insufficient",
    ),
) -> dict[str, Any]:
    """Deposit USDC from EOA to Gateway wallet."""
    client = get_client()

    try:
        response = client.post(
            "/api/v1/deposit",
            params={
                "amount": amount,
                "check_gas": check_gas,
                "skip_if_insufficient_gas": skip_if_insufficient_gas,
            },
        )
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def withdraw(
    amount: str = typer.Option(..., "--amount", help="Amount in USDC to withdraw from Gateway"),
    destination_chain: str | None = typer.Option(
        None, "--destination-chain", help="Optional CAIP-2 destination chain"
    ),
    recipient: str | None = typer.Option(None, "--recipient", help="Optional destination address"),
) -> dict[str, Any]:
    """Withdraw USDC from Gateway to Circle Developer Wallet."""
    client = get_client(owner=recipient is not None)

    try:
        params: dict[str, Any] = {"amount": amount}
        if destination_chain:
            params["destination_chain"] = destination_chain
        if recipient:
            params["recipient"] = recipient
        response = client.post("/api/v1/withdraw", params=params)
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def withdraw_trustless(
    amount: str = typer.Option(
        ..., "--amount", help="Amount in USDC to withdraw (trustless, ~7-day delay)"
    ),
) -> dict[str, Any]:
    """Initiate trustless withdrawal (~7-day delay, no API needed)."""
    client = get_client()

    try:
        response = client.post("/api/v1/withdraw-trustless", params={"amount": amount})
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        if data.get("available_after"):
            typer.echo(f"\nWithdrawal available after: {data.get('available_after')}")
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def withdraw_trustless_alias(
    amount: str = typer.Option(
        ..., "--amount", help="Amount in USDC to withdraw (trustless, ~7-day delay)"
    ),
) -> dict[str, Any]:
    """Alias for withdraw-trustless."""
    return withdraw_trustless(amount=amount)


def withdraw_trustless_complete() -> dict[str, Any]:
    """Complete a trustless withdrawal after the delay has passed."""
    client = get_client()

    try:
        response = client.post("/api/v1/withdraw-trustless/complete")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def register(app: typer.Typer, group: typer.Typer) -> None:
    app.command()(address)
    app.command()(balance)
    app.command("balance-detail")(balance_detail)
    app.command(name="balance_detail", help="Alias for balance-detail")(balance_detail_alias)
    app.command("deposit-address")(deposit_address)
    app.command(name="deposit_address", help="Alias for deposit-address")(deposit_address_alias)
    app.command()(deposit)
    app.command()(withdraw)
    app.command("withdraw-trustless")(withdraw_trustless)
    app.command(name="withdraw_trustless", help="Alias for withdraw-trustless")(
        withdraw_trustless_alias
    )
    app.command("withdraw-trustless-complete")(withdraw_trustless_complete)
    app.command(name="withdraw_trustless_complete", help="Alias for withdraw-trustless-complete")(
        withdraw_trustless_complete
    )

    group.command()(address)
    group.command()(balance)
    group.command("balance-detail")(balance_detail)
    group.command(name="balance_detail", help="Alias for balance-detail")(balance_detail_alias)
    group.command("deposit-address")(deposit_address)
    group.command(name="deposit_address", help="Alias for deposit-address")(deposit_address_alias)
    group.command()(deposit)
    group.command()(withdraw)
    group.command("withdraw-trustless")(withdraw_trustless)
    group.command(name="withdraw_trustless", help="Alias for withdraw-trustless")(
        withdraw_trustless_alias
    )
    group.command("withdraw-trustless-complete")(withdraw_trustless_complete)
    group.command(name="withdraw_trustless_complete", help="Alias for withdraw-trustless-complete")(
        withdraw_trustless_complete
    )
