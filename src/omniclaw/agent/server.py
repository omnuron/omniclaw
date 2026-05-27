import asyncio
import contextlib
import os
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from omniclaw.agent.auth import TokenAuth
from omniclaw.agent.policy import PolicyManager, WalletManager
from omniclaw.agent.routes import router
from omniclaw.core.logging import configure_logging, get_logger

# Suppress deprecation warnings from downstream dependencies (e.g. web3 using pkg_resources)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(level="INFO")
        logger.info("Starting OmniClaw Agent Server...")

        # Initialize policy manager
        policy_path = app.state.config.get("policy_path") if hasattr(app.state, "config") else None
        policy_mgr = PolicyManager(policy_path)
        await policy_mgr.load()

        # Initialize OmniClaw client
        circle_api_key = (
            app.state.config.get("circle_api_key") if hasattr(app.state, "config") else None
        )

        from omniclaw import OmniClaw
        from omniclaw.core.types import Network

        # The standalone SDK defaults to Circle-only for compatibility. The
        # buyer server is a policy engine, so default it to the full buyer rail
        # set unless the operator chooses a narrower mode.
        os.environ.setdefault("OMNICLAW_BUYER_MODE", "hybrid")

        # Read network from environment
        network_str = os.getenv("OMNICLAW_NETWORK", "ETH-SEPOLIA")
        try:
            network = Network.from_string(network_str)
        except Exception:
            network = Network.ETH_SEPOLIA
        logger.info(f"Using network: {network}")

        client = OmniClaw(
            circle_api_key=circle_api_key,
            entity_secret=None,  # Using direct private key now
            network=network,
        )

        # Initialize wallet manager
        wallet_mgr = WalletManager(policy_mgr, client)

        # Initialize wallet mappings - MUST complete before serving requests
        # In direct private key mode, this is fast (no Circle API calls)
        logger.info("OmniClaw wallet initialization starting...")
        await wallet_mgr.initialize_wallets()
        logger.info("OmniClaw wallet initialization complete")

        # Policy hot-reload loop
        reload_interval = float(os.getenv("OMNICLAW_POLICY_RELOAD_INTERVAL", "5"))
        policy_reload_task = None

        async def _policy_watch_loop() -> None:
            while True:
                await asyncio.sleep(reload_interval)
                reloaded = await policy_mgr.reload()
                if reloaded:
                    logger.info("Policy changed on disk. Reinitializing wallets and guards...")
                    await wallet_mgr.initialize_wallets()
                    logger.info("Policy reload complete.")

        if reload_interval > 0:
            policy_reload_task = asyncio.create_task(_policy_watch_loop())

        # Initialize token auth
        auth = TokenAuth(policy_mgr)

        app.state.policy_mgr = policy_mgr
        app.state.wallet_mgr = wallet_mgr
        app.state.auth = auth
        app.state.client = client

        logger.info("OmniClaw Agent Server started successfully")

        yield

        logger.info("Shutting down OmniClaw Agent Server...")
        if policy_reload_task:
            policy_reload_task.cancel()
            with contextlib.suppress(Exception):
                await policy_reload_task
        if hasattr(app.state, "client"):
            await app.state.client.__aexit__(None, None, None)
        logger.info("OmniClaw Agent Server stopped")

    app = FastAPI(
        title="OmniClaw Agent API",
        description="API for the OmniClaw Financial Policy Engine",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    from omniclaw.core.types import network_to_caip2

    omniclaw_network = os.environ.get("OMNICLAW_NETWORK", "ARC-TESTNET")
    nanopay_network = network_to_caip2(omniclaw_network)

    app.state.config = {
        "policy_path": os.environ.get("OMNICLAW_AGENT_POLICY_PATH", "/config/policy.json"),
        "circle_api_key": os.environ.get("CIRCLE_API_KEY"),
        "private_key": os.environ.get("OMNICLAW_PRIVATE_KEY"),
        "rpc_url": os.environ.get("OMNICLAW_RPC_URL"),
        "nanopay_network": nanopay_network,
        "gateway_contract_address": os.environ.get("CIRCLE_GATEWAY_CONTRACT"),
        "gateway_usdc_address": os.environ.get("CIRCLE_GATEWAY_USDC_ADDRESS")
        or os.environ.get("CIRCLE_GATEWAY_USDC_CONTRACT"),
    }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
