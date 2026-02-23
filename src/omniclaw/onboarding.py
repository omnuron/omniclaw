"""
OmniClaw SDK Onboarding Utilities.

Handles one-time Circle Developer-Controlled Wallets setup:
- Generate Entity Secret
- Register Entity Secret with Circle
- Save recovery file to secure config directory
- Create .env file with credentials

Usage:
    >>> from omniclaw.onboarding import quick_setup
    >>> quick_setup("YOUR_CIRCLE_API_KEY")
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from logging import Logger

# Circle SDK utilities for entity secret management
try:
    from circle.web3 import utils as circle_utils

    CIRCLE_SDK_AVAILABLE = True
except ImportError:
    CIRCLE_SDK_AVAILABLE = False
    circle_utils = None


def get_config_dir() -> Path:
    """
    Get the platform-specific config directory for OmniClaw.

    Returns:
        Path to config directory:
        - Linux: ~/.config/omniclaw/
        - macOS: ~/Library/Application Support/omniclaw/
        - Windows: %APPDATA%/omniclaw/

    The directory is created if it doesn't exist.
    """
    if sys.platform == "darwin":
        # macOS
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        # Windows
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        # Linux and others - use XDG standard
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"

    config_dir = base / "omniclaw"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def find_recovery_file() -> Path | None:
    """
    Search for an existing Circle recovery file.

    Recovery files are named 'circle_recovery_*.dat' and are stored in the
    config directory during entity secret registration.

    Returns:
        Path to recovery file if found, None otherwise
    """
    config_dir = get_config_dir()
    recovery_files = list(config_dir.glob("recovery_file_*.dat"))

    if recovery_files:
        # Return the most recently modified one
        return max(recovery_files, key=lambda p: p.stat().st_mtime)

    return None


class SetupError(Exception):
    """Error during SDK setup."""

    pass


def generate_entity_secret() -> str:
    """
    Generate a new 32-byte Entity Secret (64 hex characters).

    Returns:
        64-character hex string for use as ENTITY_SECRET
    """
    return secrets.token_hex(32)


def register_entity_secret(
    api_key: str,
    entity_secret: str,
    recovery_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Register an Entity Secret with Circle.

    Args:
        api_key: Circle API key
        entity_secret: 64-character hex secret
        recovery_dir: Directory to save recovery file (default: current directory)

    Returns:
        Registration result from Circle API

    Raises:
        SetupError: If Circle SDK not installed or registration fails
    """
    if not CIRCLE_SDK_AVAILABLE:
        raise SetupError(
            "Circle SDK not installed. Run: pip install circle-developer-controlled-wallets"
        )

    # Validate entity secret format
    if len(entity_secret) != 64:
        raise SetupError(f"Entity Secret must be 64 hex characters, got {len(entity_secret)}")

    try:
        int(entity_secret, 16)
    except ValueError:
        raise SetupError("Entity Secret must be valid hexadecimal") from None

    # Default to secure config directory
    # Default to secure config directory
    recovery_dir = get_config_dir() if recovery_dir is None else Path(recovery_dir).resolve()

    # Ensure directory exists
    recovery_dir.mkdir(parents=True, exist_ok=True)

    # Store list of existing files to detect new one
    existing_files = set(recovery_dir.glob("recovery_file_*.dat"))

    try:
        result = circle_utils.register_entity_secret_ciphertext(
            api_key=api_key,
            entity_secret=entity_secret,
            recoveryFileDownloadPath=str(recovery_dir),
        )

        # VERIFY: Check if a new recovery file was actually created.
        # Circle SDK v9.1.0 can sometimes swallow 409 Conflict errors and return success
        # without downloading the file. We must catch this case.
        current_files = set(recovery_dir.glob("recovery_file_*.dat"))
        new_files = current_files - existing_files

        if not new_files:
            # No new file created - suspicious.
            # If we were registering a NEW secret, this almost certainly means
            # the API key already has a DIFFERENT secret registered (409 Conflict).
            raise SetupError(
                "Entity Secret registration appeared to succeed, but NO recovery file was downloaded.\n"
                "This usually means an Entity Secret is ALREADY registered for this API key.\n\n"
                "Circle SDK suppressed the 409 Conflict error.\n"
                "See 'Entity secret already registered' in your logs."
            )

        return result
    except Exception as e:
        error_str = str(e)

        # Check for WAF/Cloudflare Lockout (HTML response)
        if "520" in error_str and ("DOCTYPE html" in error_str or "Lockout" in error_str):
            raise SetupError(
                "Access Denied (WAF Lockout).\n\n"
                "The Circle API is blocking your request (Cloudflare Error 520).\n"
                "This usually happens if you make too many failed requests quickly.\n\n"
                "Solution: Wait 5-10 minutes before trying again."
            ) from e

        # Check for 401 Unauthorized / malformed API key
        # Also catch cryptic TypeError from Circle SDK when public key fetch fails (returns None)
        is_auth_error = (
            "401" in error_str
            or "unauthorized" in error_str.lower()
            or "malformed" in error_str.lower()
            or "'NoneType' object cannot be interpreted as an integer" in error_str
        )

        if is_auth_error:
            raise SetupError(
                "Invalid or malformed Circle API key.\n\n"
                "Your API key format should be: ENV:KEY_ID:SECRET\n"
                "Example: TEST_API_KEY:abc123def456:789xyz000111\n\n"
                "Get a valid API key at: https://console.circle.com\n"
                "Then set it in your .env file:\n"
                "  CIRCLE_API_KEY=your_api_key_here"
            ) from e

        # Check for "already registered" error (HTTP 409 Conflict)
        if (
            "409" in error_str
            or "already registered" in error_str.lower()
            or "conflict" in error_str.lower()
        ):
            # Check if we have a recovery file
            recovery_file = find_recovery_file()

            if recovery_file:
                raise SetupError(
                    "Entity secret already registered for this API key.\n\n"
                    "A recovery file was found at:\n"
                    f"  {recovery_file}\n\n"
                    "To reset your entity secret:\n"
                    "  1. Go to https://console.circle.com\n"
                    "  2. Navigate to Developer > Entity Secret\n"
                    "  3. Upload the recovery file to reset your secret\n"
                    "  4. Generate a new entity secret and save it to your .env file\n\n"
                    "For details, see: https://developers.circle.com/w3s/entity-secret-management"
                ) from e
            else:
                raise SetupError(
                    "Entity secret already registered for this API key.\n\n"
                    "No recovery file found. Your options:\n"
                    "  1. Set ENTITY_SECRET in .env if you saved your original secret\n"
                    "  2. Create a new API key at https://console.circle.com\n\n"
                    "Note: Without the original entity secret or recovery file, you cannot\n"
                    "create new wallets or sign transactions with this API key.\n\n"
                    "For details, see: https://developers.circle.com/w3s/entity-secret-management"
                ) from e

        # Generic error - include original message for debugging
        raise SetupError(
            f"Failed to register entity secret with Circle API.\n\n"
            f"Error: {e}\n\n"
            "Check your CIRCLE_API_KEY is valid and try again."
        ) from e


def create_env_file(
    api_key: str,
    entity_secret: str,
    env_path: str | Path = ".env",
    network: str = "ARC-TESTNET",
    overwrite: bool = False,
) -> Path:
    """
    Create a .env file with Circle credentials.

    Args:
        api_key: Circle API key
        entity_secret: 64-character hex entity secret
        env_path: Path for .env file (default: ".env")
        network: Target network (default: "ARC-TESTNET")
        overwrite: If True, overwrite existing file

    Returns:
        Path to created .env file

    Raises:
        SetupError: If file exists and overwrite=False
    """
    env_path = Path(env_path)

    if env_path.exists() and not overwrite:
        raise SetupError(f"{env_path} already exists. Use overwrite=True to replace.")

    env_content = f"""# OmniClaw Configuration
CIRCLE_API_KEY={api_key}
ENTITY_SECRET={entity_secret}
OMNICLAW_NETWORK={network}
"""

    env_path.write_text(env_content)
    return env_path


def quick_setup(
    api_key: str,
    env_path: str | Path = ".env",
    network: str = "ARC-TESTNET",
) -> dict[str, Any]:
    """
    Complete SDK setup in one call.

    Creates:
    - .env file with CIRCLE_API_KEY and ENTITY_SECRET (in current directory)
    - Recovery file in secure config directory (~/.config/omniclaw/)

    Args:
        api_key: Your Circle API key
        env_path: Path for .env file (default: ".env" in current directory)
        network: Target network (default: "ARC-TESTNET")

    Returns:
        Dict with entity_secret, env_path, recovery_dir

    Example:
        >>> quick_setup("sk_test_...")
    """
    env_path = Path(env_path).resolve()
    recovery_dir = get_config_dir()  # Secure platform-specific location

    print("OmniClaw Setup")
    print("-" * 40)

    # Step 1: Generate Entity Secret
    entity_secret = generate_entity_secret()
    print("[OK] Generated Entity Secret")

    # Step 2: Register with Circle (saves recovery file to config dir)
    try:
        register_entity_secret(
            api_key=api_key,
            entity_secret=entity_secret,
            recovery_dir=recovery_dir,
        )
        print("[OK] Registered with Circle")
    except SetupError as e:
        print(f"[FAILED] Registration failed:\n{e}")
        raise

    # Step 3: Create .env file in project directory
    env_content = f"""# OmniClaw Configuration
CIRCLE_API_KEY={api_key}
ENTITY_SECRET={entity_secret}
OMNICLAW_NETWORK={network}
"""

    env_path.write_text(env_content)
    print(f"[OK] Created {env_path.name}")

    # Summary
    print("-" * 40)
    print(f"Credentials saved to: {env_path}")
    print(f"Recovery file saved to: {recovery_dir}")
    print()
    print("IMPORTANT: Keep the recovery file safe. You will need it if you")
    print("lose your entity secret and need to reset it.")
    print()
    print("Ready to use:")
    print("  from omniclaw import OmniClaw")
    print("  client = OmniClaw()")

    return {
        "entity_secret": entity_secret,
        "env_path": str(env_path),
        "recovery_dir": str(recovery_dir),
    }


def auto_setup_entity_secret(
    api_key: str,
    logger: Logger | None = None,
) -> str:
    """
    Silently auto-generate and register entity secret.

    Called automatically by OmniClaw client when ENTITY_SECRET is missing.
    Saves recovery file to secure config directory (~/.config/omniclaw/).
    Also appends ENTITY_SECRET to .env file if it exists.

    Args:
        api_key: Circle API key
        logger: Optional logger for status messages

    Returns:
        Generated entity secret (64 hex chars)
    """
    log = logger or logging.getLogger("omniclaw.onboarding")

    entity_secret = generate_entity_secret()

    # Register with Circle - save to secure config directory
    recovery_dir = get_config_dir()
    try:
        register_entity_secret(
            api_key=api_key,
            entity_secret=entity_secret,
            recovery_dir=recovery_dir,
        )
        log.info(f"Entity secret registered. Recovery file saved to: {recovery_dir}")
    except SetupError:
        # Don't log here - the error message is already clear
        raise

    # Set in current environment
    os.environ["ENTITY_SECRET"] = entity_secret

    # Also save to .env file if it exists (so it persists across restarts)
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "a") as f:
            f.write(f"\n# Auto-generated by OmniClaw\nENTITY_SECRET={entity_secret}\n")
        log.info(f"Entity secret appended to {env_file.resolve()}")

    return entity_secret


def verify_setup() -> dict[str, bool]:
    """
    Verify that SDK is properly configured.

    Returns:
        Dict with status of each requirement and 'ready' boolean
    """
    results = {
        "circle_sdk_installed": CIRCLE_SDK_AVAILABLE,
        "api_key_set": bool(os.getenv("CIRCLE_API_KEY")),
        "entity_secret_set": bool(os.getenv("ENTITY_SECRET")),
    }
    results["ready"] = all(results.values())
    return results


def print_setup_status() -> None:
    """Print human-readable setup status."""
    status = verify_setup()

    def icon(ok: bool) -> str:
        return "[OK]" if ok else "[MISSING]"

    print("OmniClaw Status")
    print("-" * 30)
    print(f"  {icon(status['circle_sdk_installed'])} Circle SDK")
    print(f"  {icon(status['api_key_set'])} CIRCLE_API_KEY")
    print(f"  {icon(status['entity_secret_set'])} ENTITY_SECRET")
    print()

    if status["ready"]:
        print("Ready to use.")
    else:
        print("Setup incomplete. Run: quick_setup('YOUR_API_KEY')")


# Backwards compatibility alias
ensure_setup = quick_setup
