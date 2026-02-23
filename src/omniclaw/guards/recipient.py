"""
RecipientGuard - Controls which recipients are allowed.

Supports whitelist and blacklist modes for recipient validation.
"""

from __future__ import annotations

import re

from omniclaw.guards.base import Guard, GuardResult, PaymentContext


class RecipientGuard(Guard):
    """
    Guard that controls which recipients are allowed.

    Supports whitelist and blacklist modes for recipient validation:
    - Whitelist: Only explicitly allowed recipients can receive payments
    - Blacklist: All recipients allowed except explicitly blocked ones

    Supports exact matching and regex patterns.
    """

    def __init__(
        self,
        mode: str = "whitelist",
        addresses: list[str] | None = None,
        patterns: list[str] | None = None,
        domains: list[str] | None = None,
        name: str = "recipient",
    ) -> None:
        """
        Initialize RecipientGuard.

        Args:
            mode: "whitelist" or "blacklist"
            addresses: List of wallet addresses (exact match)
            patterns: List of regex patterns to match
            domains: List of domain names (for URL recipients)
            name: Guard name for identification
        """
        if mode not in ("whitelist", "blacklist"):
            raise ValueError("mode must be 'whitelist' or 'blacklist'")

        self._name = name
        self._mode = mode
        self._addresses = {addr.lower() for addr in (addresses or [])}
        self._domains = {domain.lower() for domain in (domains or [])}
        self._patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or [])]

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> str:
        return self._mode

    def add_address(self, address: str) -> None:
        """Add an address to the list."""
        self._addresses.add(address.lower())

    def remove_address(self, address: str) -> None:
        """Remove an address from the list."""
        self._addresses.discard(address.lower())

    def add_domain(self, domain: str) -> None:
        """Add a domain to the list."""
        self._domains.add(domain.lower())

    def add_pattern(self, pattern: str) -> None:
        """Add a regex pattern to the list."""
        self._patterns.append(re.compile(pattern, re.IGNORECASE))

    def _matches(self, recipient: str) -> bool:
        """Check if recipient matches any rule."""
        recipient_lower = recipient.lower()

        # Check exact address match
        if recipient_lower in self._addresses:
            return True

        # Check domain match (for URLs)
        for domain in self._domains:
            if domain in recipient_lower:
                return True

        # Check regex patterns
        # Check regex patterns
        return any(pattern.search(recipient) for pattern in self._patterns)

    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if recipient is allowed."""
        recipient = context.recipient
        matches = self._matches(recipient)

        if self._mode == "whitelist":
            # Whitelist: must match to be allowed
            if matches:
                return GuardResult(
                    allowed=True,
                    guard_name=self.name,
                    metadata={"mode": "whitelist", "matched": True},
                )
            else:
                return GuardResult(
                    allowed=False,
                    reason=f"Recipient {recipient} not in whitelist",
                    guard_name=self.name,
                    metadata={"mode": "whitelist", "matched": False},
                )
        else:
            # Blacklist: must NOT match to be allowed
            if matches:
                return GuardResult(
                    allowed=False,
                    reason=f"Recipient {recipient} is blacklisted",
                    guard_name=self.name,
                    metadata={"mode": "blacklist", "matched": True},
                )
            else:
                return GuardResult(
                    allowed=True,
                    guard_name=self.name,
                    metadata={"mode": "blacklist", "matched": False},
                )

    def reset(self) -> None:
        """Reset does not clear the lists - use clear() for that."""
        pass

    def clear(self) -> None:
        """Clear all addresses, domains, and patterns."""
        self._addresses.clear()
        self._domains.clear()
        self._patterns.clear()
