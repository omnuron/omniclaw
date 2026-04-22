# OmniClaw Research Evidence Matrix

Purpose: map research claims to current implementation evidence so future papers, whitepapers, and outreach materials stay anchored to the artifact.

## Claim 1: Separation Of Intent From Settlement Authority

Claim:
- Agents create payment intents, but the execution layer alone settles approved payments.

Code / Docs:
- `README.md`
- `docs/compliance-architecture.md`
- `src/omniclaw/intents/intent_facade.py`
- `src/omniclaw/agent/routes.py`

Evidence Type:
- architecture documentation
- implemented control flow

What to verify next:
- exact execution-binding path in runtime code and authorization boundary documentation

## Claim 2: Intent-Bound Execution Authorization

Claim:
- Settlement is bound to exact approved parameters rather than generic approval.

Code / Docs:
- task-derived reference answer and architecture logic
- `docs/compliance-architecture.md`
- execution-layer request handling in agent/server routes

Evidence Type:
- architectural semantics
- runtime control-path inspection

What to strengthen:
- add a dedicated implementation note or test showing rejection of mismatched execution parameters

## Claim 3: Explicit Lifecycle And Transition Semantics

Claim:
- Payment intents follow explicit states and reject illegal transitions.

Code / Docs:
- `src/omniclaw/intents/service.py`
- `src/omniclaw/core/types.py`
- `tests/test_intent_transitions.py`

Evidence Type:
- code
- transition tests

Notes:
- current runtime uses `PaymentIntentStatus` values such as `REQUIRES_CONFIRMATION`, `REQUIRES_REVIEW`, `PROCESSING`, `SUCCEEDED`, `CANCELED`, and `FAILED`
- paper narrative can present a stricter generalized control-state model while mapping back to artifact states

## Claim 4: Idempotent Retry Safety

Claim:
- Equivalent payment requests derive the same idempotency key, reducing duplicate execution risk.

Code / Docs:
- `tests/test_idempotency.py`
- `README.md`
- CLI and SDK docs requiring idempotency keys

Evidence Type:
- normalization test
- product and operator docs

What to strengthen:
- add or reference an end-to-end duplicate-settlement prevention test under retry or crash scenarios

## Claim 5: Concurrency-Safe Reservation And Locking

Claim:
- Reservation plus locking reduces overspend risk under concurrent workers.

Code / Docs:
- `src/omniclaw/intents/reservation.py`
- `docs/FEATURES.md`
- `tests/test_payment_concurrency.py`
- `tests/test_reservation_integrity.py`
- `tests/test_sdk_integration_extended.py`
- `SECURITY.md`

Evidence Type:
- code
- concurrency tests
- design documentation

Notes:
- this is one of the strongest artifact-backed claims in the system

## Claim 6: Policy Versioning And Revalidation

Claim:
- Policy evaluation is tied to explicit policy state, and emergency changes can force revalidation.

Code / Docs:
- current architecture and control-plane design
- `docs/compliance-architecture.md`
- policy docs in `docs/POLICY_REFERENCE.md`

Evidence Type:
- design semantics
- policy documentation

What to strengthen:
- add or document a specific code path or test for policy version attachment and emergency revalidation

## Claim 7: Counterparty-Type-Aware Policy

Claim:
- Policy should differ for human-operated vendors, internal services, and autonomous-agent counterparties.

Code / Docs:
- task-derived architecture
- `docs/compliance-architecture.md`
- future policy schema extensions

Evidence Type:
- design contribution

What to strengthen:
- introduce explicit runtime policy fields or examples reflecting counterparty class
- add a policy-matrix example to docs

## Claim 8: Finality-Aware Policy Branching

Claim:
- Reversible and irreversible rails should follow different approval, replay, and intervention rules.

Code / Docs:
- `docs/PRODUCTION_HARDENING.md` notes on strict settlement
- task-derived architecture

Evidence Type:
- architectural semantics

What to strengthen:
- add explicit docs and tests for reversible-window versus irreversible-rail behavior

## Claim 9: Trust Gate And Counterparty Evaluation

Claim:
- Counterparty trust can be evaluated with explicit verdicts such as approve, hold, or block.

Code / Docs:
- `src/omniclaw/identity/types.py`
- `docs/compliance-architecture.md`
- `docs/FEATURES.md`
- `tests/test_trust_gate.py`

Evidence Type:
- code
- tests
- design docs

## Claim 10: Auditability And Traceability

Claim:
- The system records who requested a payment, which policy allowed it, and how execution proceeded.

Code / Docs:
- `docs/compliance-architecture.md`
- audit descriptions in `README.md` and `docs/FEATURES.md`
- event-emission points in intent services

Evidence Type:
- docs
- code hooks

What to strengthen:
- add an explicit audit-event schema doc

## Claim 11: Seller-Side Replay Resistance

Claim:
- Seller or facilitator-side consumed-proof handling can reduce replay acceptance.

Code / Docs:
- whitepaper v1 discussion
- seller-side nonce handling in `src/omniclaw/seller/seller.py`

Evidence Type:
- implementation hook

What to strengthen:
- add a dedicated replay-resistance test reference into the docs and paper

## Strongest Claims Today

These are the claims most clearly supported by current artifact evidence:

1. Separation of intent and settlement authority
2. Reservation and locking for concurrency safety
3. Intent lifecycle and transition enforcement
4. Trust Gate verdict model
5. Idempotency normalization and product-wide idempotency discipline

## Claims That Need Stronger Explicit Evidence Before Formal Publication

These are still good claims, but should be tightened with more direct code-path documentation or tests:

1. Exact execution-parameter binding rejection path
2. Policy version attachment and emergency revalidation tests
3. Counterparty-type-aware runtime policy examples
4. Reversible-versus-irreversible runtime control-path evidence
5. Formal replay-resistance evaluation

## Recommended Next Actions

1. Create an artifact appendix that links each major claim to code and test files
2. Add a dedicated audit-event schema document
3. Add explicit docs or examples for counterparty-type and finality-aware policy branching
4. Add one or two tests that directly exercise the strongest paper-specific claims not yet obvious from current test names
5. Use this matrix to keep the whitepaper and future preprint honest
