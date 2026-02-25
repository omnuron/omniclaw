"""
Weighted Trust Score (WTS) — Reputation Aggregator.

Computes a reputation score from raw ERC-8004 Reputation Registry feedback
signals using the algorithm from §3.3 of the OmniClaw system design spec.

Algorithm:
1. Filter out self-reviews (submitter == agent owner)
2. Apply recency decay (>90d = 50%, >180d = 20%) via feedback_index heuristic
3. Boost verified submitters (submitters with own ERC-8004 identity)
4. Fraud tag → mandatory 'fraud' flag
5. Weighted average of normalized scores (handles negative int128 values)
6. Minimum sample size guard (<3 → new_agent flag)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from omniclaw.core.logging import get_logger
from omniclaw.identity.types import FeedbackSignal, ReputationScore

logger = get_logger("trust.scoring")

# Tags that indicate fraud (case-insensitive)
FRAUD_TAGS = frozenset({"fraud", "scam", "malicious", "spam", "phishing"})

# Minimum number of feedback entries to be considered established
MIN_SAMPLE_SIZE = 3

# Recency bands based on feedback_index position
# top 33% of signals = recent, middle 33% = aging, bottom 33% = old
RECENT_BAND = 0.67   # top third starts at 67% of max index
AGING_BAND = 0.33    # middle third starts at 33%


class ReputationAggregator:
    """
    Computes Weighted Trust Score (WTS) from raw feedback signals.

    The scoring algorithm weights feedback by recency and submitter
    credibility, flags fraud indicators, and handles edge cases like
    new agents with insufficient history.
    """

    def __init__(
        self,
        recency_90d_weight: float = 0.5,
        recency_180d_weight: float = 0.2,
        verified_boost: float = 1.5,
        min_sample_size: int = MIN_SAMPLE_SIZE,
    ) -> None:
        """
        Args:
            recency_90d_weight: Weight multiplier for signals >90 days old
            recency_180d_weight: Weight multiplier for signals >180 days old
            verified_boost: Weight multiplier for ERC-8004 verified submitters
            min_sample_size: Minimum feedback count to NOT be flagged as new_agent
        """
        self._recency_90d = recency_90d_weight
        self._recency_180d = recency_180d_weight
        self._verified_boost = verified_boost
        self._min_sample_size = min_sample_size

    def compute_wts(
        self,
        signals: list[FeedbackSignal],
        agent_owner_address: str | None = None,
        verified_submitters: set[str] | None = None,
        now: datetime | None = None,
    ) -> ReputationScore:
        """
        Compute the Weighted Trust Score from raw feedback signals.

        Args:
            signals: Raw feedback from the Reputation Registry
            agent_owner_address: Agent's owner address (to filter self-reviews)
            verified_submitters: Set of addresses with ERC-8004 identity
            now: Current time (for recency decay)

        Returns:
            ReputationScore with WTS 0-100, flags, and breakdown
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Pre-compute lowercased verified set once (avoid O(n²) rebuild)
        verified_lower: frozenset[str] = frozenset()
        if verified_submitters:
            verified_lower = frozenset(a.lower() for a in verified_submitters)

        # Step 0: Partition signals
        total_count = len(signals)
        revoked = [s for s in signals if s.is_revoked]
        active = [s for s in signals if not s.is_revoked]

        # Step 1: Filter self-reviews
        self_reviews: list[FeedbackSignal] = []
        eligible: list[FeedbackSignal] = []
        owner_lower = agent_owner_address.lower() if agent_owner_address else None
        for signal in active:
            if owner_lower and signal.client_address.lower() == owner_lower:
                self_reviews.append(signal)
            else:
                eligible.append(signal)

        # Step 4: Check for fraud tags (before scoring)
        flags: list[str] = []
        fraud_count = 0
        for signal in eligible:
            tags = {signal.tag1.lower(), signal.tag2.lower()} - {""}
            if tags & FRAUD_TAGS:
                fraud_count += 1

        if fraud_count > 0:
            flags.append("fraud")

        # Step 6: Minimum sample size guard
        sample_size = len(eligible)
        new_agent = sample_size < self._min_sample_size
        if new_agent:
            flags.append("new_agent")

        # Step 2+3+5: Compute weighted average
        verified_count = 0
        if not eligible:
            wts = 0
            if not flags:
                flags.append("no_feedback")
        else:
            weighted_sum = 0.0
            weight_total = 0.0

            # Find max feedback_index for recency decay estimation
            max_index = max(s.feedback_index for s in eligible)

            for signal in eligible:
                # Normalize score to 0-100 range
                # ERC-8004 uses int128 — can be negative for trading losses
                # Clamp to [0, 100] for WTS purposes
                score = signal.normalized_score
                score = max(0.0, min(100.0, score))

                # Step 2: Recency decay (index-based approximation)
                weight = self._recency_weight(signal, max_index)

                # Step 3: Verified submitter boost
                if signal.client_address.lower() in verified_lower:
                    weight *= self._verified_boost
                    verified_count += 1

                weighted_sum += score * weight
                weight_total += weight

            wts = int(round(weighted_sum / weight_total)) if weight_total > 0 else 0

        # Clamp to 0-100
        wts = max(0, min(100, wts))

        # Low WTS flag (only if not already flagged for fraud)
        if wts < 30 and "fraud" not in flags:
            flags.append("low_wts")

        return ReputationScore(
            wts=wts,
            sample_size=sample_size,
            new_agent=new_agent,
            flags=flags,
            raw_signals=eligible,
            total_feedback_count=total_count,
            revoked_count=len(revoked),
            self_review_count=len(self_reviews),
            verified_submitter_count=verified_count,
        )

    def _recency_weight(
        self,
        signal: FeedbackSignal,
        max_index: int,
    ) -> float:
        """
        Compute recency weight for a feedback signal.

        Uses feedback_index as a proxy for recency since on-chain events
        don't store timestamps in contract storage. Higher index = more recent.

        - Recent (top 33%): weight = 1.0 (full)
        - Aging (middle 33%): weight = recency_90d (default 0.5)
        - Old (bottom 33%): weight = recency_180d (default 0.2)
        """
        if max_index <= 0:
            return 1.0

        # Position as fraction of max (0.0 = oldest, 1.0 = newest)
        position = signal.feedback_index / max_index

        if position >= RECENT_BAND:
            return 1.0
        elif position >= AGING_BAND:
            return self._recency_90d
        else:
            return self._recency_180d


__all__ = ["ReputationAggregator"]

