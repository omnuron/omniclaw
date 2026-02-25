# 002 - Risk Engine & RiskGuard Specification

## 1. Overview
The **Risk Engine** is a probabilistic layer that sits on top of the deterministic kernel guards. While kernel guards (Budget, RateLimit) provide hard binary limits (Allow/Block), the Risk Engine calculates a **Risk Score (0-100)** for every transaction based on multiple factors.

This score determines the action:
- **0-19 (Low):** ✅ **ALLOW** (Execute immediately)
- **20-79 (Medium):** ⚠️ **FLAG** (Require async HITL review / 2FA)
- **80-100 (High):** 🛑 **BLOCK** (Reject immediately)

## 2. Core Components

### 2.1 `RiskFactor` (The Signals)
A modular interface for calculating specific risk signals.

```python
class RiskFactor(ABC):
    @abstractmethod
    async def evaluate(self, context: PaymentContext) -> float:
        """Returns a risk score contribution (0.0 to 1.0)."""
        pass
```

**Planned Factors:**
1.  **`VelocityFactor`**: Checks if transaction frequency/volume is spiking compared to the moving average (e.g., "5x normal volume in last hour").
2.  **`NewRecipientFactor`**: High risk if the recipient address has never been seen before for this wallet/team.
3.  **`TimeFactor`**: Higher risk for transactions during anomalous hours (e.g., 3 AM local time) or weekends if configured.
4.  **`AmountFactor`**: Non-linear risk scaling with amount (e.g., small tx = low risk, large tx = exponential risk).
5.  **`ReputationFactor`** (Future): Checks external blacklists (OFAC, Chainalysis) via API.

### 2.2 `RiskGuard` (The Engine)
The guard implementation that aggregates factors.

- **Configuration:**
    - `factors`: List of enabled factors and their weights.
    - `thresholds`: Configuration for Low/Medium/High actions.
- **Logic:**
    - `Total Score = Sum(Factor Score * Weight) / Sum(Weights)`
    - If `Score >= high_threshold`: Raise `RiskBlockedError`.
    - If `Score >= medium_threshold`: Raise `RiskFlaggedError` (which triggers `PaymentIntent` hold).
    - Else: Allow.

### 2.3 Integration with Ledger
The `LedgerEntry` must be updated to store:
- `risk_score`: The final calculated score.
- `risk_factors`: Breakdown of individual factor scores (for audit/explainability).
- `risk_decision`: `ALLOW`, `FLAG`, or `BLOCK`.

## 3. Workflow (The "B2B" Flow)

1.  **Agent initiates `pay()`**.
2.  **Kernel Guards Check:** Budget, Rate Limit, Whitelist. If fail -> **BLOCK**.
3.  **Risk Engine Check:**
    - Calculates Score.
    - **Scenario A (Low Risk):** Returns `ALLOW`. `pay()` proceeds to Lock -> Execute.
    - **Scenario B (Medium Risk):** Throws `RiskFlaggedError`.
        - `pay()` catches error.
        - Automatically creates a `PaymentIntent` with status `REQUIRES_CONFIRMATION`.
        - Returns `PaymentResult(status=PENDING, reason="Risk Check: Flagged for Review")`.
    - **Scenario C (High Risk):** Throws `RiskBlockedError`. `pay()` fails.

## 4. Case Management (Audit)
When a transaction is **FLAGGED**:
- A **Case** is logically created (linked to the `PaymentIntent`).
- Notification sent to Admin (via Webhook/Event).
- Admin reviews via Dashboard/API:
    - *View:* "Risk Score: 65 (New Recipient + High Velocity)"
    - *Action:* `approve()` or `reject()`.
- If `approve()`: Intent transitions to `PROCESSING` -> Executed.
- If `reject()`: Intent transitions to `CANCELLED`.

## 5. Implementation Phases

### Phase 1: The Engine (This Spec)
- Implement `RiskFactor` interface.
- Implement `VelocityFactor`, `NewRecipientFactor`, `AmountFactor`.
- Implement `RiskGuard` aggregation logic.
- Update `PaymentContext` to support history lookups (needed for Velocity/Recipient checks).

### Phase 2: The Workflow
- Update `OmniClawClient.pay()` to handle `RiskFlaggedError`.
- Auto-convert Flagged transactions to `PaymentIntents`.

### Phase 3: The Case Management
- Add `Case` entity to Ledger.
- Add Admin API for reviewing/resolving cases.
