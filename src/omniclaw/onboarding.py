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

import warnings

# Suppress deprecation warnings from downstream dependencies (e.g. web3 using pkg_resources)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

import contextlib
import hashlib
import json
import logging
import os
import secrets
import stat
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


MANAGED_CREDENTIALS_FILE = "credentials.json"
KEYRING_SERVICE = "omniclaw.managed_credentials"


def _api_key_fingerprint(api_key: str) -> str:
    """Create a stable, non-reversible fingerprint for an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _mask_secret(secret: str | None) -> str | None:
    """Mask a secret for safe display."""
    if not secret:
        return None
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"


def _managed_credentials_path() -> Path:
    """Return the path to the managed credentials metadata file."""
    return get_config_dir() / MANAGED_CREDENTIALS_FILE


def _store_secret_in_keyring(secret_ref: str, secret_value: str) -> bool:
    """Store a secret in OS keyring if available."""
    try:
        import keyring  # type: ignore

        keyring.set_password(KEYRING_SERVICE, secret_ref, secret_value)
        return True
    except Exception:
        return False


def _load_secret_from_keyring(secret_ref: str | None) -> str | None:
    """Load a secret from OS keyring if available."""
    if not secret_ref:
        return None
    try:
        import keyring  # type: ignore

        value = keyring.get_password(KEYRING_SERVICE, secret_ref)
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def _read_managed_credentials_store() -> dict[str, Any]:
    """Read the managed credentials store from disk."""
    path = _managed_credentials_path()
    if not path.exists():
        return {"version": 1, "credentials": {}}

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SetupError(f"Managed credentials store is invalid JSON: {path}") from exc

    if not isinstance(data, dict):
        raise SetupError(f"Managed credentials store has invalid structure: {path}")

    credentials = data.get("credentials")
    if not isinstance(credentials, dict):
        data["credentials"] = {}

    data.setdefault("version", 1)
    return data


def _write_managed_credentials_store(data: dict[str, Any]) -> Path:
    """Write the managed credentials store to disk with restrictive permissions."""
    path = _managed_credentials_path()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o600)
    return path


def store_managed_credentials(
    api_key: str,
    entity_secret: str,
    *,
    source: str,
    recovery_file: str | None = None,
) -> Path:
    """
    Persist the active entity secret to OmniClaw's managed config store.

    This store is the runtime fallback when `.env` is missing but the user
    has already completed setup on the machine.
    """
    store = _read_managed_credentials_store()
    fingerprint = _api_key_fingerprint(api_key)
    secret_ref = f"{fingerprint}:entity_secret"
    stored_in_keyring = _store_secret_in_keyring(secret_ref, entity_secret)
    runtime_env = os.environ.get("OMNICLAW_ENV", "development").lower()
    default_plaintext_fallback = (
        "false" if runtime_env in {"prod", "production", "mainnet"} else "true"
    )
    allow_plaintext_fallback = (
        os.environ.get(
            "OMNICLAW_ALLOW_PLAINTEXT_MANAGED_SECRET",
            default_plaintext_fallback,
        ).lower()
        == "true"
    )
    recovery_path = recovery_file or (str(find_recovery_file()) if find_recovery_file() else None)

    stored_entity_secret = (
        entity_secret if (not stored_in_keyring and allow_plaintext_fallback) else None
    )

    store["credentials"][fingerprint] = {
        "api_key_fingerprint": fingerprint,
        "api_key_masked": _mask_secret(api_key),
        "entity_secret": stored_entity_secret,
        "entity_secret_masked": _mask_secret(entity_secret),
        "entity_secret_ref": secret_ref if stored_in_keyring else None,
        "entity_secret_storage": "keyring"
        if stored_in_keyring
        else ("plaintext" if stored_entity_secret else "unavailable"),
        "source": source,
        "recovery_file": recovery_path,
    }
    return _write_managed_credentials_store(store)


def load_managed_credentials(api_key: str) -> dict[str, Any] | None:
    """Load managed credentials for the provided Circle API key."""
    store = _read_managed_credentials_store()
    fingerprint = _api_key_fingerprint(api_key)
    entry = store.get("credentials", {}).get(fingerprint)
    return entry if isinstance(entry, dict) else None


def load_managed_entity_secret(api_key: str) -> str | None:
    """Load the managed entity secret for a Circle API key, if present."""
    entry = load_managed_credentials(api_key)
    if not entry:
        return None
    secret = _load_secret_from_keyring(entry.get("entity_secret_ref"))
    if secret:
        return secret
    secret = entry.get("entity_secret")
    return secret if isinstance(secret, str) and secret else None


def resolve_entity_secret(api_key: str | None = None) -> str | None:
    """
    Find the best available entity secret for the current session.

    Resolution order:
    1. OS environment (ENTITY_SECRET)
    2. Managed store (matching CIRCLE_API_KEY)
    """
    # 1. Environment priority
    env_secret = os.getenv("ENTITY_SECRET")
    if env_secret:
        return env_secret

    # 2. Managed store fallback
    resolved_api_key = api_key or os.getenv("CIRCLE_API_KEY")
    if resolved_api_key:
        return load_managed_entity_secret(resolved_api_key)

    return None


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

        for new_file in new_files:
            os.chmod(new_file, 0o600)

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
    os.chmod(env_path, 0o600)
    with contextlib.suppress(OSError):
        store_managed_credentials(api_key, entity_secret, source="create_env_file")
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
    os.chmod(env_path, 0o600)
    recovery_file = find_recovery_file()
    try:
        store_managed_credentials(
            api_key,
            entity_secret,
            source="quick_setup",
            recovery_file=str(recovery_file) if recovery_file else None,
        )
    except OSError:
        print("[WARN] Unable to sync managed credentials store.")
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
        with contextlib.suppress(OSError):
            os.chmod(env_file, 0o600)
        log.info(f"Entity secret appended to {env_file.resolve()}")

    recovery_file = find_recovery_file()
    try:
        store_managed_credentials(
            api_key,
            entity_secret,
            source="auto_setup",
            recovery_file=str(recovery_file) if recovery_file else None,
        )
    except OSError as exc:
        log.warning(f"Unable to sync managed credentials store: {exc}")

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


def doctor(
    api_key: str | None = None,
    entity_secret: str | None = None,
) -> dict[str, Any]:
    """
    Diagnose the local OmniClaw setup and credential recovery state.

    Resolution order is explicit args, environment, then managed config.
    """
    resolved_api_key = api_key or os.getenv("CIRCLE_API_KEY")
    env_entity_secret = entity_secret or os.getenv("ENTITY_SECRET")
    managed_secret = None
    if resolved_api_key:
        load_managed_credentials(resolved_api_key)
        managed_secret = load_managed_entity_secret(resolved_api_key)
    recovery_file = find_recovery_file()
    config_dir = get_config_dir()
    credentials_path = _managed_credentials_path()

    active_secret = env_entity_secret or managed_secret
    if env_entity_secret:
        secret_source = "environment"
    elif managed_secret:
        secret_source = "managed_config"
    else:
        secret_source = None

    warnings: list[str] = []
    if resolved_api_key and not active_secret:
        warnings.append("No active ENTITY_SECRET found for the current API key.")
    if active_secret and not recovery_file:
        warnings.append("No Circle recovery file found in the OmniClaw config directory.")
    if recovery_file:
        mode = stat.S_IMODE(recovery_file.stat().st_mode)
        if mode & 0o077:
            warnings.append(
                f"Recovery file permissions are too broad ({oct(mode)}). Expected 0o600."
            )
    if env_entity_secret and managed_secret and env_entity_secret != managed_secret:
        warnings.append("Environment ENTITY_SECRET does not match the managed config copy.")

    return {
        "ready": bool(resolved_api_key and active_secret and CIRCLE_SDK_AVAILABLE),
        "circle_sdk_installed": CIRCLE_SDK_AVAILABLE,
        "config_dir": str(config_dir),
        "managed_credentials_path": str(credentials_path),
        "api_key_set": bool(resolved_api_key),
        "api_key_masked": _mask_secret(resolved_api_key),
        "env_entity_secret_set": bool(env_entity_secret),
        "managed_entity_secret_set": bool(managed_secret),
        "active_entity_secret_source": secret_source,
        "active_entity_secret_masked": _mask_secret(active_secret),
        "recovery_file_found": bool(recovery_file),
        "recovery_file_path": str(recovery_file) if recovery_file else None,
        "warnings": warnings,
        "can_sync_to_env": bool(managed_secret and not env_entity_secret),
    }


def print_doctor_status(
    api_key: str | None = None,
    entity_secret: str | None = None,
    *,
    as_json: bool = False,
) -> None:
    """Print human-readable diagnostic output for OmniClaw setup."""
    status = doctor(api_key=api_key, entity_secret=entity_secret)

    if as_json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return

    def icon(ok: bool) -> str:
        return "[OK]" if ok else "[MISSING]"

    print("OmniClaw Doctor")
    print("-" * 30)
    print(f"  {icon(status['circle_sdk_installed'])} Circle SDK")
    print(f"  {icon(status['api_key_set'])} Circle API key")
    print(f"  {icon(status['env_entity_secret_set'])} ENTITY_SECRET in environment")
    print(f"  {icon(status['managed_entity_secret_set'])} Managed entity secret")
    print(f"  {icon(status['recovery_file_found'])} Circle recovery file")
    print()
    print(f"  Config dir: {status['config_dir']}")
    print(f"  Managed store: {status['managed_credentials_path']}")
    print(f"  Active secret source: {status['active_entity_secret_source'] or 'none'}")
    print(f"  Recovery file: {status['recovery_file_path'] or 'not found'}")
    print()

    if status["warnings"]:
        print("Warnings:")
        for warning in status["warnings"]:
            print(f"  - {warning}")
        print()

    next_steps: list[str] = []
    if not status["api_key_set"]:
        next_steps.append("Set CIRCLE_API_KEY before initializing OmniClaw.")
    if not status["env_entity_secret_set"] and not status["managed_entity_secret_set"]:
        next_steps.append(
            "Initialize OmniClaw once or run a setup flow so an ENTITY_SECRET can be registered."
        )
    if status["managed_entity_secret_set"] and not status["env_entity_secret_set"]:
        next_steps.append(
            "Optionally export the managed entity secret into your deployment environment."
        )
    if status["managed_entity_secret_set"] and not status["recovery_file_found"]:
        next_steps.append(
            "Back up or regenerate a Circle recovery file before relying on this account in production."
        )
    if status["recovery_file_found"]:
        next_steps.append(
            f"Back up the recovery file and managed store from {status['config_dir']} to a secure location."
        )

    if next_steps:
        print("Next steps:")
        for step in next_steps:
            print(f"  - {step}")
        if status.get("can_sync_to_env"):
            print("\n  ð¡ TIP: You have a saved Entity Secret but it's not in your environment.")
            print("     Run: omniclaw setup  # to sync it automatically")
        print()

    print("Ready to use." if status["ready"] else "Setup needs attention.")


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
