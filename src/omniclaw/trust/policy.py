"""
Trust Policy Engine — Configurable per-wallet trust evaluation.

Evaluates agent identity and reputation against an operator-configured
TrustPolicy to produce a verdict (APPROVED / BLOCKED / HELD).

Checks are evaluated in strict priority order (§4.3 of the spec):
1. Address blocklist
2. Org whitelist (skip rest if matched)
3. Identity required check
4. Fraud tag check
5. New agent check
6. Min feedback count
7. Min WTS check
8. High-value WTS check
9. Attestation check
10. All pass → APPROVED
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from omniclaw.core.logging import get_logger
from omniclaw.identity.types import (
    AgentIdentity,
    ReputationScore,
    TrustCheckResult,
    TrustPolicy,
    TrustVerdict,
)

logger = get_logger("trust.policy")


class PolicyEngine:
    """
    Evaluates trust policies against agent identity and reputation data.

    The engine applies a strict-order set of checks. The first failing
    check determines the verdict.
    """

    def evaluate(
        self,
        identity: AgentIdentity | None,
        reputation: ReputationScore | None,
        amount: Decimal,
        recipient_address: str,
        policy: TrustPolicy,
    ) -> TrustCheckResult:
        """
        Run all policy checks and return a TrustCheckResult.

        Args:
            identity: Resolved ERC-8004 identity (None if not found)
            reputation: Computed WTS score (None if no identity)
            amount: Payment amount in USDC
            recipient_address: Recipient wallet address
            policy: Operator's trust policy

        Returns:
            TrustCheckResult with verdict and reasoning
        """
        # Build result object
        result = TrustCheckResult(
            identity_found=identity is not None,
            token_id=identity.agent_id if identity else None,
            organization=identity.organization if identity else None,
            wts=reputation.wts if reputation else None,
            sample_size=reputation.sample_size if reputation else 0,
            new_agent=reputation.new_agent if reputation else True,
            flags=list(reputation.flags) if reputation else [],
            attestations=list(identity.attestations) if identity else [],
            policy_id=policy.policy_id,
        )

        # ─── Check 1: Address Blocklist ──────────────────────────────
        if self._is_blocklisted(recipient_address, policy):
            result.verdict = TrustVerdict.BLOCKED
            result.block_reason = "ADDRESS_BLOCKLISTED"
            result.flags.append("blocklisted")
            logger.info(f"Trust BLOCKED: {recipient_address} is blocklisted")
            return result

        # ─── Check 2: Org Whitelist (skip rest) ──────────────────────
        if identity and self._is_whitelisted(identity, policy):
            result.verdict = TrustVerdict.APPROVED
            logger.debug(f"Trust APPROVED: org whitelist match for {identity.organization}")
            return result

        # ─── Check 3: Identity Required ──────────────────────────────
        if policy.identity_required and identity is None:
            result.verdict = TrustVerdict.BLOCKED
            result.block_reason = "NO_IDENTITY"
            result.flags.append("no_identity")
            logger.info(f"Trust BLOCKED: no ERC-8004 identity for {recipient_address}")
            return result

        # ─── Check 4: Fraud Tag ──────────────────────────────────────
        if reputation and "fraud" in reputation.flags:
            result.verdict = policy.fraud_tag_action
            result.block_reason = "FRAUD_TAG"
            logger.warning(f"Trust {policy.fraud_tag_action.value}: fraud tag on agent {recipient_address}")
            return result

        # ─── Check 5: New Agent ──────────────────────────────────────
        # A new agent has < min_sample_size feedback OR has no reputation data at all
        is_new = (reputation and reputation.new_agent) or (identity and not reputation)
        if is_new and policy.new_agent_action != TrustVerdict.APPROVED:
            result.verdict = policy.new_agent_action
            result.block_reason = "NEW_AGENT"
            logger.info(f"Trust {policy.new_agent_action.value}: new agent {recipient_address}")
            return result

        # ─── Check 6: Min Feedback Count ─────────────────────────────
        actual_sample = reputation.sample_size if reputation else 0
        if policy.min_feedback_count > 0 and actual_sample < policy.min_feedback_count:
            result.verdict = TrustVerdict.HELD
            result.block_reason = "INSUFFICIENT_FEEDBACK"
            logger.info(
                f"Trust HELD: {actual_sample} feedback < "
                f"required {policy.min_feedback_count}"
            )
            return result

        # ─── Check 7: Min WTS ────────────────────────────────────────
        actual_wts = reputation.wts if reputation else 0
        if policy.min_wts > 0 and actual_wts < policy.min_wts:
            result.verdict = TrustVerdict.BLOCKED
            result.block_reason = "LOW_WTS"
            result.flags.append("low_wts")
            logger.info(f"Trust BLOCKED: WTS {actual_wts} < min {policy.min_wts}")
            return result

        # ─── Check 8: High-Value WTS ─────────────────────────────────
        if (
            policy.high_value_threshold_usd > 0
            and amount >= policy.high_value_threshold_usd
        ):
            hv_wts = reputation.wts if reputation else 0
            if hv_wts < policy.high_value_min_wts:
                result.verdict = TrustVerdict.HELD
                result.block_reason = "HIGH_VALUE_WTS_FAIL"
                logger.info(
                    f"Trust HELD: amount ${amount} >= ${policy.high_value_threshold_usd} "
                    f"but WTS {hv_wts} < required {policy.high_value_min_wts}"
                )
                return result

        # ─── Check 9: Required Attestations ──────────────────────────
        if policy.require_attestations:
            agent_attestations = set(identity.attestations) if identity else set()
            missing = set(policy.require_attestations) - agent_attestations
            if missing:
                result.verdict = TrustVerdict.HELD
                result.block_reason = f"MISSING_ATTESTATIONS:{','.join(sorted(missing))}"
                logger.info(f"Trust HELD: missing attestations {missing}")
                return result

        # ─── Check 10: All Pass ──────────────────────────────────────
        result.verdict = TrustVerdict.APPROVED
        logger.debug(f"Trust APPROVED for {recipient_address} (WTS: {actual_wts})")
        return result

    # ─── Helper Methods ──────────────────────────────────────────────

    @staticmethod
    def _is_blocklisted(address: str, policy: TrustPolicy) -> bool:
        """Check if address is in the blocklist."""
        return address.lower() in {a.lower() for a in policy.address_blocklist}

    @staticmethod
    def _is_whitelisted(identity: AgentIdentity, policy: TrustPolicy) -> bool:
        """Check if agent's organization is in the whitelist."""
        if not policy.org_whitelist or not identity.organization:
            return False
        return identity.organization.lower() in {
            o.lower() for o in policy.org_whitelist
        }


__all__ = ["PolicyEngine"]
