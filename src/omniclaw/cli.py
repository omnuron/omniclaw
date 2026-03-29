from __future__ import annotations

import warnings

# Suppress deprecation warnings from downstream dependencies (e.g. web3 using pkg_resources)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

import argparse
import os
from collections.abc import Sequence

from omniclaw.onboarding import print_doctor_status


ENV_VARS = {
    "required": {
        "CIRCLE_API_KEY": "Circle API key for wallet/payment operations",
        "ENTITY_SECRET": "Entity secret for transaction signing",
    },
    "optional": {
        "OMNICLAW_RPC_URL": "RPC endpoint for trust gate (ERC-8004)",
        "OMNICLAW_STORAGE_BACKEND": "Storage backend: memory or redis",
        "OMNICLAW_REDIS_URL": "Redis connection URL (when using redis)",
        "OMNICLAW_LOG_LEVEL": "Logging: DEBUG, INFO, WARNING, ERROR",
    },
    "production": {
        "OMNICLAW_ENV": "Set to production for mainnet/strict mode",
        "OMNICLAW_STRICT_SETTLEMENT": "Enable strict settlement validation",
        "OMNICLAW_WEBHOOK_VERIFICATION_KEY": "Public key for webhook signatures",
        "OMNICLAW_SELLER_NONCE_REDIS_URL": "Redis for distributed nonce (multi-instance)",
    },
}


def print_env_vars():
    """Print all available environment variables."""
    print("\n=== OmniClaw Environment Variables ===\n")

    print("Required:")
    for var, desc in ENV_VARS["required"].items():
        value = os.environ.get(var, "")
        status = f"â {value[:20]}..." if value else "â not set"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")

    print("\nOptional:")
    for var, desc in ENV_VARS["optional"].items():
        value = os.environ.get(var, "")
        status = f"â {value[:30]}..." if value else "â default"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")

    print("\nProduction:")
    for var, desc in ENV_VARS["production"].items():
        value = os.environ.get(var, "")
        status = f"â {value[:30]}..." if value else "â not set"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the OmniClaw CLI parser."""
    parser = argparse.ArgumentParser(prog="omniclaw")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect OmniClaw setup, managed credentials, and recovery state",
    )
    doctor_parser.add_argument("--api-key", help="Override CIRCLE_API_KEY for diagnostics")
    doctor_parser.add_argument(
        "--entity-secret",
        help="Override ENTITY_SECRET for diagnostics",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )

    subparsers.add_parser(
        "env",
        help="List all available environment variables",
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="Quickly set up your Control Plane credentials (.env.agent)",
    )
    setup_parser.add_argument("--api-key", help="Circle API Key")
    setup_parser.add_argument(
        "--network", default="ARC-TESTNET", help="Circle Network (default: ARC-TESTNET)"
    )

    server_parser = subparsers.add_parser(
        "server",
        help="Start the OmniClaw Control Plane (Financial Firewall) server",
    )
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    server_parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    server_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    return parser


def handle_setup(args: argparse.Namespace) -> int:
    """Handle the setup command."""
    from omniclaw.onboarding import resolve_entity_secret, create_env_file

    api_key = args.api_key or os.getenv("CIRCLE_API_KEY")
    if not api_key:
        api_key = input("Enter your Circle API Key: ").strip()

    if not api_key:
        print("â Error: Circle API Key is required.")
        return 1

    entity_secret = resolve_entity_secret(api_key)
    if entity_secret:
        print("â Found existing Entity Secret in managed store.")
    else:
        print("ð¡ No Entity Secret found for this API key.")
        entity_secret = input(
            "Enter your 64-char Entity Secret (or press Enter to generate): "
        ).strip()
        if not entity_secret:
            from omniclaw.onboarding import auto_setup_entity_secret

            print("ð Generating and registering new Entity Secret...")
            entity_secret = auto_setup_entity_secret(api_key)

    env_path = ".env.agent"
    create_env_file(api_key, entity_secret, env_path=env_path, network=args.network, overwrite=True)
    print(f"â¨ Successfully configured {env_path}!")
    print("To start the server locally, run: omniclaw server")
    print("To start via Docker, run: docker compose -f docker-compose.agent.yml up -d")
    return 0


def handle_server(args: argparse.Namespace) -> int:
    """Handle the server command."""
    import uvicorn
    from dotenv import load_dotenv
    from omniclaw.onboarding import resolve_entity_secret, auto_setup_entity_secret

    # Load .env.agent if it exists
    if os.path.exists(".env.agent"):
        load_dotenv(".env.agent")
        print("ð Loaded configuration from .env.agent")
    elif os.path.exists(".env"):
        load_dotenv(".env")
        print("ð Loaded configuration from .env")

    # Auto-Setup Logic: Check if we have an API key but no Entity Secret
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")

    if api_key and not entity_secret:
        print("ð¡ Found API Key but no Entity Secret. Attempting auto-setup...")
        entity_secret = resolve_entity_secret(api_key)
        if not entity_secret:
            print("ð Generating new Entity Secret for this machine...")
            entity_secret = auto_setup_entity_secret(api_key)

        if entity_secret:
            os.environ["ENTITY_SECRET"] = entity_secret
            print("â Credentials verified and injected.")
        else:
            print("â Error: Failed to resolve or generate Entity Secret.")
            return 1

    print(f"ð Starting OmniClaw Control Plane on {args.host}:{args.port}...")
    uvicorn.run(
        "omniclaw.agent.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=os.getenv("OMNICLAW_LOG_LEVEL", "info").lower(),
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OmniClaw CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        print_doctor_status(
            api_key=args.api_key,
            entity_secret=args.entity_secret,
            as_json=args.json,
        )
        return 0

    if args.command == "env":
        print_env_vars()
        return 0

    if args.command == "setup":
        return handle_setup(args)

    if args.command == "server":
        return handle_server(args)

    parser.print_help()
    print("\nCommands:")
    print("  setup   - Quick credentials configuration")
    print("  server  - Start the Financial Firewall server")
    print("  doctor  - Inspect setup and credentials")
    print("  env     - List all environment variables")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
