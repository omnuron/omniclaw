from __future__ import annotations

import argparse
import json
import os
import warnings
from collections.abc import Sequence

from omniclaw.onboarding import print_doctor_status

# Suppress deprecation warnings from downstream dependencies.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

BANNER = r"""
   ____  __  __ _   _ ___ ____ _        ___        __
  / __ \|  \/  | \ | |_ _/ ___| |      / \ \      / /
 | |  | | |\/| |  \| || | |   | |     / _ \ \ /\ / /
 | |__| | |  | | |\  || | |___| |___ / ___ \ V  V /
  \____/|_|  |_|_| \_|___\____|_____/_/   \_\_/\_/

  OmniClaw is the economy and control layer for AI agent payments.
  Economic Execution and Control Layer for Agentic Systems
"""

ENV_VARS = {
    "required": {
        "CIRCLE_API_KEY": "Circle API key for wallet/payment operations",
        "OMNICLAW_PRIVATE_KEY": "Private key for nanopayment signing",
    },
    "optional": {
        "ENTITY_SECRET": (
            "Existing Circle Entity Secret. Set this directly if your API key already has one."
        ),
        "OMNICLAW_RPC_URL": "RPC endpoint for trust gate (ERC-8004)",
        "OMNICLAW_NETWORK": "Default network profile, for example BASE-SEPOLIA or ARC-TESTNET",
        "OMNICLAW_STORAGE_BACKEND": "Storage backend: memory or redis",
        "OMNICLAW_REDIS_URL": "Redis connection URL (when using redis)",
        "OMNICLAW_LOG_LEVEL": "Logging: DEBUG, INFO, WARNING, ERROR",
    },
    "production": {
        "OMNICLAW_ENV": "Set to production for mainnet/strict mode",
        "OMNICLAW_STRICT_SETTLEMENT": "Enable strict settlement validation",
        "OMNICLAW_WEBHOOK_VERIFICATION_KEY": "Public key for webhook signatures",
    },
}


def print_banner() -> None:
    print(f"\033[1;36m{BANNER}\033[0m")
    print("\033[90mOmniClaw Financial Infrastructure - v2.0 Production-Ready\033[0m\n")


def print_env_vars() -> None:
    print("\n=== OmniClaw Environment Variables ===\n")

    print("Required:")
    for var, desc in ENV_VARS["required"].items():
        value = os.environ.get(var, "")
        status = f"✓ {value[:20]}..." if value else "✗ not set"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")

    print("\nOptional:")
    for var, desc in ENV_VARS["optional"].items():
        value = os.environ.get(var, "")
        status = f"✓ {value[:30]}..." if value else "○ default"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")

    print("\nProduction:")
    for var, desc in ENV_VARS["production"].items():
        value = os.environ.get(var, "")
        status = f"✓ {value[:30]}..." if value else "○ not set"
        print(f"  {var}")
        print(f"    {desc}")
        print(f"    {status}\n")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _require_positive(name: str, value: float | int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omniclaw")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect OmniClaw setup, managed credentials, and recovery state",
    )
    doctor_parser.add_argument("--api-key", help="Override CIRCLE_API_KEY for diagnostics")
    doctor_parser.add_argument("--entity-secret", help="Override ENTITY_SECRET for diagnostics")
    doctor_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    subparsers.add_parser("env", help="List all available environment variables")

    setup_parser = subparsers.add_parser(
        "setup",
        help="Quickly set up your Financial Policy Engine credentials (.env.agent)",
    )
    setup_parser.add_argument("--api-key", help="Circle API Key")
    setup_parser.add_argument(
        "--entity-secret",
        default=None,
        help=(
            "Existing 64-char Circle Entity Secret. If omitted, OmniClaw uses a "
            "managed/env secret or generates and registers a new one."
        ),
    )
    setup_parser.add_argument(
        "--network",
        default="ARC-TESTNET",
        help="Circle Network (default: ARC-TESTNET)",
    )

    server_parser = subparsers.add_parser(
        "server",
        help="Start the OmniClaw Financial Policy Engine server",
    )
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    server_parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    server_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    policy_parser = subparsers.add_parser("policy", help="Policy utilities (lint/validate)")
    policy_sub = policy_parser.add_subparsers(dest="policy_command")
    lint_parser = policy_sub.add_parser("lint", help="Validate policy.json")
    lint_parser.add_argument(
        "--path",
        default=os.environ.get("OMNICLAW_AGENT_POLICY_PATH", "/config/policy.json"),
        help="Path to policy.json",
    )

    return parser


def handle_setup(args: argparse.Namespace) -> int:
    from omniclaw.onboarding import create_env_file, resolve_entity_secret, validate_entity_secret

    api_key = args.api_key or os.getenv("CIRCLE_API_KEY")
    if not api_key:
        api_key = input("Enter your Circle API Key: ").strip()

    if not api_key:
        print("❌ Error: Circle API Key is required.")
        return 1

    entity_secret = args.entity_secret or resolve_entity_secret(api_key)
    if entity_secret:
        entity_secret = validate_entity_secret(entity_secret)
        print("✅ Using existing Circle Entity Secret.")
    else:
        print("💡 No Entity Secret found for this API key.")
        entity_secret = input(
            "Enter your 64-char Entity Secret (or press Enter to generate): "
        ).strip()
        if not entity_secret:
            from omniclaw.onboarding import auto_setup_entity_secret

            print("🚀 Generating and registering new Entity Secret...")
            entity_secret = auto_setup_entity_secret(api_key)
        else:
            entity_secret = validate_entity_secret(entity_secret)

    env_path = ".env.agent"
    create_env_file(api_key, entity_secret, env_path=env_path, network=args.network, overwrite=True)
    print(f"✨ Successfully configured {env_path}!")
    print("To start the server locally, run: omniclaw server")
    print(
        "To start via Docker, run: "
        "docker compose -f examples/agent/docker-compose.yml up -d"
    )
    return 0


def handle_server(args: argparse.Namespace) -> int:
    import uvicorn
    from dotenv import load_dotenv

    from omniclaw.onboarding import auto_setup_entity_secret, resolve_entity_secret

    if os.path.exists(".env.agent"):
        load_dotenv(".env.agent")
        print("📄 Loaded configuration from .env.agent")
    elif os.path.exists(".env"):
        load_dotenv(".env")
        print("📄 Loaded configuration from .env")

    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")

    if api_key and not entity_secret:
        print("💡 Found API Key but no Entity Secret. Attempting auto-setup...")
        entity_secret = resolve_entity_secret(api_key)
        if not entity_secret:
            print("🚀 Generating new Entity Secret for this machine...")
            entity_secret = auto_setup_entity_secret(api_key)

        if entity_secret:
            os.environ["ENTITY_SECRET"] = entity_secret
            print("✅ Credentials verified and injected.")
        else:
            print("❌ Error: Failed to resolve or generate Entity Secret.")
            return 1

    print(f"🚀 Starting OmniClaw Financial Policy Engine on {args.host}:{args.port}...")
    uvicorn.run(
        "omniclaw.agent.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=os.getenv("OMNICLAW_LOG_LEVEL", "info").lower(),
    )
    return 0


def handle_policy_lint(args: argparse.Namespace) -> int:
    from omniclaw.agent.policy_schema import validate_policy

    try:
        with open(args.path) as f:
            data = json.load(f)
        validate_policy(data)
        print(f"✅ policy.json is valid: {args.path}")
        return 0
    except Exception as exc:
        print(f"❌ Invalid policy.json: {exc}")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print_banner()

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

    if args.command == "policy" and args.policy_command == "lint":
        return handle_policy_lint(args)

    parser.print_help()
    print("\nCommands:")
    print("  setup       - Quick credentials configuration")
    print("  server      - Start the Financial Policy Engine server")
    print("  doctor      - Inspect setup and credentials")
    print("  env         - List all environment variables")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
