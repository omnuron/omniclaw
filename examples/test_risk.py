import asyncio
import logging
from decimal import Decimal
from unittest.mock import MagicMock
import sys

# Mock circle
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()

import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from omniclaw.guards.base import PaymentContext
from omniclaw.risk.factors import AmountFactor
from omniclaw.risk.guard import RiskGuard, RiskFlaggedError, RiskBlockedError

logging.basicConfig(level=logging.INFO)

async def test_risk_guard():
    print("--- Testing Risk Engine ---")
    
    # Setup Guard with Limits
    # Low=20, High=80
    guard = RiskGuard(name="risk_test", low_threshold=20.0, high_threshold=80.0)
    
    # Factor 1: Amount (Weight 1.0)
    # 0-100 -> Low Risk
    # 100-1000 -> Linear Scale
    # >1000 -> High Risk (1.0)
    
    # Need to subclass AmountFactor since we don't have storage/ledger
    class SimpleAmountFactor(AmountFactor):
        async def evaluate(self, context):
            return await super().evaluate(context)

    guard.add_factor(SimpleAmountFactor(weight=1.0, low_threshold=Decimal("100"), high_threshold=Decimal("1000")))
    
    # 1. Low Risk Test (Amount 50) -> Should Allow (Score 0)
    print("\n1. Testing Low Risk (Amount 50)...")
    ctx1 = PaymentContext(
        wallet_id="w1", 
        recipient="0x123", 
        amount=Decimal("50")
    )
    result = await guard.check(ctx1)
    print(f"   Result: Allowed={result.allowed} (Score 0)")
    assert result.allowed == True

    # 2. Medium Risk Test (Amount 500)
    # Score calculation:
    # (500-100)/(1000-100) = 400/900 = 0.444
    # Scaled to 100 = 44.4
    # Thresholds: Low=20, High=80. So 44.4 > 20 -> FLAG
    print("\n2. Testing Medium Risk (Amount 500)...")
    ctx2 = PaymentContext(
        wallet_id="w1", 
        recipient="0x123", 
        amount=Decimal("500")
    )
    try:
        await guard.check(ctx2)
        print("   FAILED: Should have raised RiskFlaggedError")
    except RiskFlaggedError as e:
        print(f"   SUCCESS: Raised RiskFlaggedError (Score: {e.score:.1f})")
        assert 40 < e.score < 50

    # 3. High Risk Test (Amount 2000) -> Should Block (Score 100)
    print("\n3. Testing High Risk (Amount 2000)...")
    ctx3 = PaymentContext(
        wallet_id="w1", 
        recipient="0x123", 
        amount=Decimal("2000")
    )
    try:
        await guard.check(ctx3)
        print("   FAILED: Should have raised RiskBlockedError")
    except RiskBlockedError as e:
        print(f"   SUCCESS: Raised RiskBlockedError ({e})")

    print("\n--- Test Passed ---")

if __name__ == "__main__":
    asyncio.run(test_risk_guard())
