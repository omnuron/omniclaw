from __future__ import annotations

import warnings

# Suppress deprecation warnings from downstream dependencies (e.g. web3 using pkg_resources)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from omniclaw.agent.auth import TokenAuth
from omniclaw.agent.policy import PolicyManager, WalletManager
from omniclaw.agent.routes import router
from omniclaw.core.logging import configure_logging, get_logger

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
        entity_secret = (
            app.state.config.get("entity_secret") if hasattr(app.state, "config") else None
        )

        from omniclaw import OmniClaw
        from omniclaw.core.types import Network

        client = OmniClaw(
            circle_api_key=circle_api_key,
            entity_secret=entity_secret,
            network=Network.ARC_TESTNET,
        )

        # Initialize wallet manager
        wallet_mgr = WalletManager(policy_mgr, client)
        wallet_results = await wallet_mgr.initialize_wallets()
        logger.info(f"Initialized agent wallet: {wallet_results}")

        # Initialize token auth
        auth = TokenAuth(policy_mgr)

        app.state.policy_mgr = policy_mgr
        app.state.wallet_mgr = wallet_mgr
        app.state.auth = auth
        app.state.client = client

        logger.info("OmniClaw Agent Server started successfully")

        yield

        logger.info("Shutting down OmniClaw Agent Server...")
        if hasattr(app.state, "client"):
            await app.state.client.__aexit__(None, None, None)
        logger.info("OmniClaw Agent Server stopped")

    app = FastAPI(
        title="OmniClaw Agent API",
        description="API for OmniClaw Agent Wallet Control Plane",
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

    import os

    app.state.config = {
        "policy_path": os.environ.get("OMNICLAW_AGENT_POLICY_PATH", "/config/policy.json"),
        "circle_api_key": os.environ.get("CIRCLE_API_KEY"),
        "entity_secret": os.environ.get("ENTITY_SECRET"),
    }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
