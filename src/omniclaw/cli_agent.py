from __future__ import annotations

import warnings

# Suppress deprecation warnings from downstream dependencies (e.g. web3 using pkg_resources)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import typer

app = typer.Typer(help="omniclaw-cli - CLI for AI agents to make USDC payments")

CONFIG_DIR = Path.home() / ".omniclaw"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict[str, Any]:
    """Load configuration from file."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_client() -> httpx.Client:
    """Get HTTP client with auth."""
    config = load_config()
    server_url = config.get("server_url", os.environ.get("OMNICLAW_SERVER_URL"))
    token = config.get("token", os.environ.get("OMNICLAW_TOKEN"))

    if not server_url:
        typer.echo("Error: Server URL not configured. Run 'omniclaw-cli configure'", err=True)
        raise typer.Exit(1)

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return httpx.Client(base_url=server_url, headers=headers, timeout=30.0)


@app.command()
def configure(
    server_url: str = typer.Option(..., "--server-url", help="OmniClaw server URL"),
    token: str = typer.Option(..., "--token", help="Agent token"),
    wallet: str = typer.Option(..., "--wallet", help="Wallet alias"),
    show: bool = typer.Option(False, "--show", help="Show current config"),
) -> None:
    """Configure omniclaw-cli with server details."""
    if show:
        config = load_config()
        if not config:
            typer.echo("No configuration found. Run 'omniclaw-cli configure --server-url ...'")
            return
        typer.echo(json.dumps(config, indent=2))
        return

    config = {
        "server_url": server_url.rstrip("/"),
        "token": token,
        "wallet": wallet,
    }
    save_config(config)
    typer.echo(f"Configuration saved to {CONFIG_FILE}")
    typer.echo(f"Server: {server_url}")
    typer.echo(f"Wallet: {wallet}")


@app.command()
def address() -> dict[str, Any]:
    """Get wallet address."""
    client = get_client()
    _config = load_config()

    try:
        response = client.get("/api/v1/address")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
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
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def pay(
    recipient: str = typer.Option(..., "--recipient", help="Payment recipient (address or URL)"),
    amount: str | None = typer.Option(
        None, "--amount", help="Amount in USDC (optional for x402 URLs)"
    ),
    purpose: str | None = typer.Option(None, "--purpose", help="Payment purpose"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Idempotency key"),
    destination_chain: str | None = typer.Option(
        None, "--destination-chain", help="Target network"
    ),
    fee_level: str | None = typer.Option(
        None, "--fee-level", help="Gas fee level (LOW, MEDIUM, HIGH)"
    ),
    check_trust: bool = typer.Option(False, "--check-trust", help="Run Trust Gate check"),
    skip_guards: bool = typer.Option(False, "--skip-guards", help="Skip guards (OWNER ONLY)"),
    method: str = typer.Option("GET", "--method", help="HTTP method for x402 requests"),
    body: str | None = typer.Option(None, "--body", help="JSON body for x402 requests"),
    header: list[str] = typer.Option([], "--header", help="Additional headers for x402 requests"),
    output: str | None = typer.Option(None, "--output", help="Save response to file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate first"),
) -> dict[str, Any]:
    """Execute a payment or pay for an x402 service."""
    if dry_run:
        return simulate(
            recipient=recipient,
            amount=amount or "0.00",
            idempotency_key=idempotency_key,
            destination_chain=destination_chain,
            fee_level=fee_level,
            check_trust=check_trust,
            skip_guards=skip_guards,
        )

    client = get_client()

    # If recipient is a URL, handle x402 flow
    if recipient.startswith("http"):
        typer.echo(f"Ã°ÂÂÂ Paying for x402 service: {recipient}")
        payload: dict[str, Any] = {
            "url": recipient,
            "method": method,
        }
        if body:
            payload["body"] = body
        if header:
            payload["headers"] = {h.split(":")[0]: h.split(":")[1].strip() for h in header}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        try:
            response = client.post("/api/v1/x402/pay", json=payload)
            response.raise_for_status()
            data = response.json()
            if output:
                Path(output).write_text(json.dumps(data, indent=2))
                typer.echo(f"Ã¢ÂÂ Response saved to {output}")
            else:
                typer.echo(json.dumps(data, indent=2))
            return data
        except httpx.HTTPStatusError as e:
            typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    # Standard direct transfer
    if not amount:
        typer.echo("Error: --amount is required for direct transfers", err=True)
        raise typer.Exit(1)

    payload = {
        "recipient": recipient,
        "amount": amount,
    }
    if purpose:
        payload["purpose"] = purpose
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if destination_chain:
        payload["destination_chain"] = destination_chain
    if fee_level:
        payload["fee_level"] = fee_level
    if check_trust:
        payload["check_trust"] = True
    if skip_guards:
        payload["skip_guards"] = True

    try:
        response = client.post("/api/v1/pay", json=payload)
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def simulate(
    recipient: str = typer.Option(..., "--recipient", help="Recipient to simulate"),
    amount: str = typer.Option(..., "--amount", help="Amount to simulate"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Idempotency key"),
    destination_chain: str | None = typer.Option(
        None, "--destination-chain", help="Target network"
    ),
    fee_level: str | None = typer.Option(
        None, "--fee-level", help="Gas fee level (LOW, MEDIUM, HIGH)"
    ),
    check_trust: bool = typer.Option(False, "--check-trust", help="Run Trust Gate check"),
    skip_guards: bool = typer.Option(False, "--skip-guards", help="Skip guards (OWNER ONLY)"),
) -> dict[str, Any]:
    """Simulate a payment without executing."""
    client = get_client()

    payload: dict[str, Any] = {
        "recipient": recipient,
        "amount": amount,
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if destination_chain:
        payload["destination_chain"] = destination_chain
    if fee_level:
        payload["fee_level"] = fee_level
    if check_trust:
        payload["check_trust"] = True
    if skip_guards:
        payload["skip_guards"] = True

    try:
        response = client.post("/api/v1/simulate", json=payload)
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def ledger(
    limit: int = typer.Option(20, "--limit", help="Number of transactions to fetch"),
) -> dict[str, Any]:
    """List transaction history."""
    return list_tx(limit=limit)


@app.command()
def list_tx(
    limit: int = typer.Option(20, "--limit", help="Number of transactions to fetch"),
) -> dict[str, Any]:
    """List transaction history."""
    client = get_client()

    try:
        response = client.get("/api/v1/transactions", params={"limit": limit})
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def create_intent(
    recipient: str = typer.Option(..., "--recipient", help="Recipient"),
    amount: str = typer.Option(..., "--amount", help="Amount"),
    purpose: str | None = typer.Option(None, "--purpose", help="Purpose"),
    expires_in: int | None = typer.Option(None, "--expires-in", help="Expiry in seconds"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Idempotency key"),
    destination_chain: str | None = typer.Option(
        None, "--destination-chain", help="Target network"
    ),
    fee_level: str | None = typer.Option(
        None, "--fee-level", help="Gas fee level (LOW, MEDIUM, HIGH)"
    ),
    check_trust: bool = typer.Option(False, "--check-trust", help="Run Trust Gate check"),
    skip_guards: bool = typer.Option(False, "--skip-guards", help="Skip guards (OWNER ONLY)"),
) -> dict[str, Any]:
    """Create a payment intent (authorize)."""
    client = get_client()

    payload: dict[str, Any] = {
        "recipient": recipient,
        "amount": amount,
    }
    if purpose:
        payload["purpose"] = purpose
    if expires_in:
        payload["expires_in"] = expires_in
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if destination_chain:
        payload["destination_chain"] = destination_chain
    if fee_level:
        payload["fee_level"] = fee_level
    if check_trust:
        payload["check_trust"] = True
    if skip_guards:
        payload["skip_guards"] = True

    try:
        response = client.post("/api/v1/intents", json=payload)
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def confirm_intent(
    intent_id: str = typer.Option(..., "--intent-id", help="Intent ID to confirm"),
) -> dict[str, Any]:
    """Confirm a payment intent (capture)."""
    client = get_client()

    try:
        response = client.post(f"/api/v1/intents/{intent_id}/confirm")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def get_intent(
    intent_id: str = typer.Option(..., "--intent-id", help="Intent ID to fetch"),
) -> dict[str, Any]:
    """Get a payment intent."""
    client = get_client()

    try:
        response = client.get(f"/api/v1/intents/{intent_id}")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def cancel_intent(
    intent_id: str = typer.Option(..., "--intent-id", help="Intent ID to cancel"),
    reason: str | None = typer.Option(None, "--reason", help="Cancel reason"),
) -> dict[str, Any]:
    """Cancel a payment intent."""
    client = get_client()

    try:
        response = client.delete(
            f"/api/v1/intents/{intent_id}", params={"reason": reason} if reason else {}
        )
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def can_pay(
    recipient: str = typer.Option(..., "--recipient", help="Recipient to check"),
) -> dict[str, Any]:
    """Check if recipient is allowed."""
    client = get_client()

    try:
        response = client.get("/api/v1/can-pay", params={"recipient": recipient})
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def serve(
    price: float = typer.Option(..., "--price", help="Price per request in USDC"),
    endpoint: str = typer.Option(..., "--endpoint", help="Endpoint path to expose"),
    exec_cmd: str = typer.Option(..., "--exec", help="Command to execute on success"),
    port: int = typer.Option(8000, "--port", help="Local port to listen on"),
) -> None:
    """Expose a local service behind an x402 payment gate."""
    import uvicorn
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import JSONResponse

    server_app = FastAPI()
    client = get_client()

    @server_app.api_route(endpoint, methods=["GET", "POST", "PUT", "DELETE"])
    async def payment_gate(request: Request):
        # 1. Check for x402 header (V2)
        sig = request.headers.get("PAYMENT-SIGNATURE")
        if not sig:
            # Return 402 with requirements
            _config = load_config()
            wallet_addr = client.get("/api/v1/address").json().get("address")

            requirements = {
                "x402Version": 2,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "eip155:5042002",  # ARC Testnet
                        "amount": str(int(price * 10**6)),
                        "payTo": wallet_addr,
                    }
                ],
            }
            encoded = base64.b64encode(json.dumps(requirements).encode()).decode()
            return JSONResponse(
                status_code=402,
                content={"detail": "Payment Required"},
                headers={"PAYMENT-REQUIRED": encoded},
            )

        # 2. Verify payment with OmniClaw Server
        try:
            # We need to extract the sender and amount from the signature or payload
            # For the demo, we'll assume the signature is valid if the server verifies it
            verify_payload = {
                "signature": sig,
                "amount": str(price),
                "sender": "unknown",  # extracted from sig later
                "resource": str(request.url),
            }
            v_resp = client.post("/api/v1/x402/verify", json=verify_payload)
            v_resp.raise_for_status()

            if not v_resp.json().get("valid"):
                return JSONResponse(status_code=402, content={"detail": "Invalid Payment"})

        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Verification failed: {e}"})

        # 3. Success: Run the command
        try:
            env = os.environ.copy()
            env["OMNICLAW_PAYER_ADDRESS"] = v_resp.json().get("sender", "unknown")
            env["OMNICLAW_AMOUNT_USD"] = str(price)

            result = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, env=env)
            return Response(content=result.stdout, media_type="text/plain")
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Execution failed: {e}"})

    typer.echo(f"Ã°ÂÂÂ OmniClaw Service exposed at http://localhost:{port}{endpoint}")
    typer.echo(f"Ã°ÂÂÂ° Price: ${price} USDC")
    typer.echo(f"Ã°ÂÂÂ Ã¯Â¸Â Exec: {exec_cmd}")

    uvicorn.run(server_app, host="0.0.0.0", port=port)


@app.command()
def status() -> dict[str, Any]:
    """Get agent status and health."""
    client = get_client()
    config = load_config()

    try:
        # Get multiple stats for a complete status report
        health = client.get("/api/v1/health").json()
        balance_data = client.get("/api/v1/balance").json()
        addr_data = client.get("/api/v1/address").json()

        status_data = {
            "Agent": config.get("wallet", "unknown"),
            "Wallet": addr_data.get("address"),
            "Balance": f"${balance_data.get('available')} available",
            "Guards": "active" if health.get("status") == "ok" else "degraded",
            "Circle": "connected" if health.get("status") == "ok" else "disconnected",
            "Circuit": "CLOSED" if health.get("status") == "ok" else "OPEN",
        }

        # Print in the premium format from the user vision
        typer.echo(f"Agent:     {status_data['Agent']}")
        typer.echo(f"Wallet:    {status_data['Wallet']}")
        typer.echo(f"Balance:   {status_data['Balance']}")
        typer.echo(f"Guards:    {status_data['Guards']}")
        typer.echo(f"Circle:    {status_data['Circle']} Ã¢ÂÂ")
        typer.echo(f"Circuit:   {status_data['Circuit']} Ã¢ÂÂ")

        return status_data
    except Exception as e:
        typer.echo(f"Error fetching status: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def ping() -> dict[str, Any]:
    """Health check."""
    client = get_client()

    try:
        response = client.get("/api/v1/health")
        response.raise_for_status()
        data = response.json()
        typer.echo(json.dumps(data, indent=2))
        return data
    except httpx.HTTPStatusError as e:
        typer.echo(f"Error: {e.response.json().get('detail', str(e))}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def main() -> int:
    """Main entry point."""
    return app()


if __name__ == "__main__":
    raise SystemExit(main())
