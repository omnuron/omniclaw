"""
Risk Guard.

The master Risk Guard that aggregates risk factors and enforces thresholds.
"""

from __future__ import annotations

import logging
from typing import Any, List

from omniclaw.guards.base import Guard, GuardResult, PaymentContext
from omniclaw.risk.factors import RiskFactor

logger = logging.getLogger(__name__)


class RiskBlockedError(Exception):
    """Raised when risk score is too high (BLOCK)."""
    pass


class RiskFlaggedError(Exception):
    """Raised when risk score is medium (FLAG)."""
    def __init__(self, message: str, score: float, reasons: dict[str, float]):
        super().__init__(message)
        self.score = score
        self.reasons = reasons

    @property
    def details(self):
        return {"score": self.score, "reasons": self.reasons}

class RiskGuard(Guard):
    """
    Risk-based payment guard.

    Evaluates multiple risk factors to produce a composite risk score (0-100).
    Enforces actions based on score thresholds:
    - Low (0-20): ALLOW
    - Medium (20-80): FLAG (Requires Confirmation)
    - High (80-100): BLOCK
    """

    def __init__(
        self,
        name: str = "risk_engine",
        storage: Any = None,
        ledger: Any = None,
        low_threshold: float = 20.0,
        high_threshold: float = 80.0,
    ) -> None:
        self._name = name
        self._storage = storage
        self._ledger = ledger
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self._factors: List[RiskFactor] = []

    @property
    def name(self) -> str:
        return self._name

    def add_factor(self, factor: RiskFactor) -> None:
        """Add a risk factor to the engine."""
        self._factors.append(factor)
        if self._storage and self._ledger:
            # Initialize if storage already bound
            # But await is async. We can't do it in sync add_factor easily.
            # We defer initialization to check() or explicit init?
            # Or make add_factor async? 
            # Or make initialize sync?
            # Let's defer to check() for now, or assume factors are stateless except for injected deps.
            pass

    async def initialize(self) -> None:
        """Initialize all factors."""
        for factor in self._factors:
            if hasattr(factor, "initialize"):
                await factor.initialize(self._storage, self._ledger)

    async def check(self, context: PaymentContext) -> GuardResult:
        """
        Evaluate risk score and determine action.

        Returns:
            GuardResult(allowed=True) if Low Risk.
            Raises RiskFlaggedError if Medium Risk.
            Raises RiskBlockedError if High Risk.
            
            Note: Standard Guard interface expects GuardResult(allowed=False) for block.
            But we need to distinguish between BLOCK and FLAG.
            
            Strategy:
            - High Risk -> allowed=False, reason="Risk Blocked (Score: 85)"
            - Medium Risk -> allowed=False, reason="Risk Flagged (Score: 45)" 
              (Client catches this specific reason string or we use metadata?)
            
            Better: Use metadata to signal the flag.
        """
        # Ensure initialization
        if self._storage and self._ledger:
             # This re-init is cheap if factors handle idempotency
             # But ideally we do it once.
             pass

        total_score = 0.0
        total_weight = 0.0
        factor_scores = {}

        for factor in self._factors:
            # Inject deps if needed on the fly
            if hasattr(factor, "initialize") and not getattr(factor, "_ledger", None):
                await factor.initialize(self._storage, self._ledger)

            raw_score = await factor.evaluate(context)
            weighted_score = raw_score * factor.weight
            
            total_score += weighted_score
            total_weight += factor.weight
            
            factor_scores[factor.__class__.__name__] = raw_score

        # Normalize to 0-100
        if total_weight > 0:
            final_score = (total_score / total_weight) * 100.0
        else:
            final_score = 0.0

        trust_result = context.metadata.get("trust_result") if context.metadata else None
        
        # Adjust thresholds based on trust score (if available)
        adjusted_high_threshold = self.high_threshold
        adjusted_low_threshold = self.low_threshold

        if trust_result:
            # If high trust (WTS > 80), relax risk thresholds
            # Example: Allow 20% more risk for trusted counterparties
            if trust_result.wts >= 80:
                adjusted_high_threshold += 10.0 # Allow up to 90
                adjusted_low_threshold += 10.0  # Allow up to 30
            # If low trust (WTS < 20), tighten thresholds
            elif trust_result.wts <= 20:
                adjusted_high_threshold -= 20.0 # Block at 60
                adjusted_low_threshold -= 10.0  # Flag at 10

        metadata = {
            "risk_score": final_score,
            "risk_factors": factor_scores,
            "thresholds": {
                "low": adjusted_low_threshold,
                "high": adjusted_high_threshold,
                "original_low": self.low_threshold,
                "original_high": self.high_threshold
            },
            "trust_adjustment": bool(trust_result)
        }

        if final_score >= adjusted_high_threshold:
            logger.warning(f"Risk BLOCK: Score {final_score} for {context.wallet_id}")
            raise RiskBlockedError(f"Risk Score too high ({final_score:.1f} >= {adjusted_high_threshold})")
        
        if final_score >= adjusted_low_threshold:
            logger.info(f"Risk FLAG: Score {final_score} for {context.wallet_id}")
            raise RiskFlaggedError(
                f"Risk Flagged ({final_score:.1f})", 
                score=final_score,
                reasons=factor_scores
            )

        logger.info(f"Risk ALLOW: Score {final_score} for {context.wallet_id}")
        metadata["action"] = "ALLOW"
        return GuardResult(
            allowed=True,
            reason="Risk check passed",
            guard_name=self.name,
            metadata=metadata
        )

    async def reserve(self, context: PaymentContext) -> str | None:
        """
        Check risk and return token (none for risk guard).
        Raises RiskFlaggedError or RiskBlockedError on failure.
        """
        # We call check, which raises exceptions for non-allow
        await self.check(context)
        return None
