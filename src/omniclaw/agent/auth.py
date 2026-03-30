"""Token authentication for agent server."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from omniclaw.agent.policy import PolicyManager


@dataclass
class AuthenticatedAgent:
    """Authenticated agent context."""

    token: str
    wallet_id: str


class TokenAuth:
    """Token-based authentication."""

    def __init__(self, policy_manager: PolicyManager):
        self._policy = policy_manager
        self._security = HTTPBearer(auto_error=False)
        self._agent_token = os.environ.get("OMNICLAW_AGENT_TOKEN")
        if not self._agent_token:
            import logging
            logging.getLogger(__name__).warning("OMNICLAW_AGENT_TOKEN not set! Authentication will fail.")

    async def authenticate(
        self,
        credentials: HTTPAuthorizationCredentials,
    ) -> AuthenticatedAgent:
        """Authenticate request using token against the policy mapping."""
        token = credentials.credentials

        wallet_id = self._policy.get_wallet_id_for_token(token)
        if not wallet_id:
            raise HTTPException(status_code=401, detail="Invalid or unauthorized token")

        return AuthenticatedAgent(
            token=token,
            wallet_id=wallet_id,
        )


def get_auth(policy_manager: PolicyManager) -> TokenAuth:
    """Get TokenAuth instance."""
    return TokenAuth(policy_manager)
