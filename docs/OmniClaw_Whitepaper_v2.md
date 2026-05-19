# OmniClaw Whitepaper v2 Draft

## OmniClaw: Policy-Constrained Financial Execution for Autonomous Agents

Version: v2 draft  
Status: research and publication draft  
Prepared from the implemented OmniClaw artifact and supporting documentation

---

## Abstract

Autonomous agents increasingly need to buy compute, data, API access, and machine services without human intervention, but existing payment infrastructure exposes execution primitives rather than safe authority models. In most current designs, a wallet, key, or provider credential is placed close to the agent itself, which turns prompt injection, tool misuse, concurrency bugs, stale policy, and timeout ambiguity into direct financial risk. OmniClaw addresses this problem with a policy-constrained financial execution control plane that separates agent intent from settlement authority. The system enforces operator-defined policy before funds move, binds execution to an approved intent, uses durable intent and reservation state to avoid duplicate settlement and budget overcommitment, treats uncertain settlement outcomes as explicit reconciliation cases rather than retryable failures, and supports differentiated policy by counterparty type and settlement finality. Unlike wallet-only or settlement-only approaches, OmniClaw provides an authority model suitable for autonomous payments across heterogeneous rails while preserving auditability and bounded operational risk.

---

## 1. Introduction

Autonomous software agents are no longer limited to search, retrieval, and workflow orchestration. They increasingly need to perform economic actions: purchasing model inference, paying for proprietary APIs, settling service fees, compensating downstream tools, or collecting revenue for machine-exposed endpoints. This shift creates a structural mismatch between what modern payment rails provide and what autonomous systems need.

Most payment infrastructure answers the question of how to move money. It does not answer the harder question of when autonomous software should be allowed to move money.

If an agent holds direct wallet authority or raw settlement credentials, then ordinary software failures become treasury-risk events. A hallucinated tool call can authorize a payment. A prompt injection can redirect a transfer. Concurrent workers can overcommit a shared budget. A timeout can produce an unknown outcome, yet naive retry logic may replay the payment. A stale approval can remain valid after an emergency policy update. An external autonomous counterparty can generate requests at machine speed with little human accountability. In short, the problem is not only settlement. It is authority, policy, and failure semantics.

OmniClaw is designed as a control-plane answer to that problem. It places an explicit policy and stateful decision layer between agent intent and settlement execution. Agents may request economic actions. Operators define policy envelopes. The control layer evaluates whether a specific payment is permitted. The execution layer settles only an approved, bound intent. This separation preserves agent autonomy while avoiding the direct-wallet model that collapses authority and execution into the same compromise surface.

The central claim of this paper is that autonomous financial execution requires more than keys and settlement adapters. It requires a control architecture with explicit trust boundaries, policy semantics, state semantics, idempotency, concurrency control, and auditability.

---

## 2. Problem Statement

The core research question is:

How can an autonomous system perform economic actions at machine speed while preserving bounded authority, concurrency safety, failure-aware settlement semantics, and post-hoc auditability across heterogeneous payment rails?

This question breaks into a set of concrete systems requirements:

1. Agents must be able to request payments without directly controlling settlement credentials.
2. Policy must be evaluated before funds move, not after.
3. Approved execution must be bound to exact validated parameters.
4. Concurrent workers must not overspend a shared budget.
5. Timeouts and partial execution must not be treated as known failures.
6. Policy updates must not silently invalidate or weaken in-flight approvals.
7. Counterparty type and settlement finality must alter the control path.
8. All decisions and state changes must be reconstructible after the fact.

Traditional wallet or settlement APIs satisfy only a subset of these requirements. They answer how to sign or submit a payment, but not how to govern an autonomous actor that wants to pay.

---

## 3. Threat And Failure Model

OmniClaw is built for the following failure and threat classes.

### 3.1 Compromised Agent Runtime

An agent may be compromised through prompt injection, tool misuse, dependency compromise, or operator error. The critical question is whether that compromise becomes direct settlement authority or remains bounded by external controls.

### 3.2 Retry And Timeout Ambiguity

A provider call can time out after settlement may already have started. In such a case, the system does not know whether replay would duplicate a valid payment or recover from a failed one.

### 3.3 Budget Overcommitment Under Concurrency

Multiple workers sharing a budget or wallet can independently observe available capacity and each authorize spending, even though the aggregate spend exceeds the true remaining budget.

### 3.4 Policy Races

A payment intent can be evaluated under one policy version and later executed after a revocation, freeze, destination change, or emergency operator action.

### 3.5 Adversarial Counterparties

External recipients may attempt redirection, replay, false success claims, or exploit the system’s inability to distinguish trusted from high-variance counterparties.

### 3.6 Parameter Tampering Between Approval And Execution

If approval says “something like this is allowed” but execution can vary amount, destination, or context, then policy can be bypassed after the fact.

The threat model does not assume perfect network reliability, perfectly synchronized clocks, or exactly-once message delivery. It assumes durable storage and enforceable component separation, but not a perfect environment.

---

## 4. Design Goals

OmniClaw is built around five design goals.

### G1. Separate Intent From Settlement

Agents should be able to request economic action without holding the authority to directly settle it.

### G2. Make Policy First-Class

Policy should be explicit, versioned, and evaluated against every payment request before execution.

### G3. Treat Uncertain Outcomes As A Distinct State

Timeouts and ambiguous provider results should not be collapsed into failure or success. They should enter reconciliation.

### G4. Preserve Correctness Under Concurrency

Shared budgets and wallet capacity must be enforced against aggregate in-flight usage, not only local read-time observations.

### G5. Make Authorization Auditable

A later reviewer should be able to reconstruct which agent requested a payment, which policy version authorized it, which execution attempt ran, and why the system took the path it did.

---

## 5. Architecture Overview

OmniClaw decomposes the payment authority problem into explicit components.

### 5.1 Agent Runtime

The agent runtime creates attributable payment intents. It does not hold settlement keys or direct settlement authority.

### 5.2 Payment Control Service

The control service evaluates intents against policy, decides whether to allow, block, or escalate, and creates bound execution authorizations for approved intents.

### 5.3 Versioned Policy Store

The policy store contains operator-defined rules, limits, recipient controls, confirmation thresholds, and trust-related policy inputs. Each executable intent must be associated with the policy version or snapshot used during evaluation.

### 5.4 Approval Service

High-risk intents are routed to a higher-trust approval path rather than executed automatically.

### 5.5 Payment-Intent Ledger

The ledger stores durable intent state and attempt state. It is the source of truth for lifecycle and reconciliation.

### 5.6 Execution Service

The execution service is the only component permitted to trigger payment execution. It uses provider integrations or rail-specific adapters, but only for already-approved intents.

### 5.7 Audit Layer

Every control decision and state transition is logged with enough metadata to reconstruct the authorization chain. The log must be append-only and tamper-evident.

---

## 6. Trust Boundary And Execution Binding

The core trust decision in OmniClaw is that the authority to request payment is not the same as the authority to settle payment.

Agents authenticate to the control layer through workload identity, mTLS, or another non-exportable service credential. Approval does not itself move funds. Instead, the control service mints a short-lived execution authorization that binds the exact intent ID, amount, destination, policy version, and expiry. The execution layer must reject any settlement request that lacks a valid authorization or that does not match the bound parameters.

This design produces a stronger invariant than “the execution layer is separate.” It produces:

Only the exact approved intent may be settled, and only by the execution layer.

Settlement signing material should be accessible only to the execution layer through non-exportable custody such as HSM or KMS-backed keys. Network isolation should also prevent agent runtimes from directly reaching settlement endpoints.

---

## 7. Payment-Intent State Semantics

OmniClaw requires explicit financial state rather than vague “pending” flags.

The current implementation exposes payment-intent lifecycle support and tests legal transition behavior, while the task-derived architecture sharpens the desired semantics into a stricter operational model:

- Submitted
- PolicyEvaluating
- AwaitingApproval
- ApprovedForExecution
- Executing
- ReconciliationRequired
- FailedTerminal
- Finalized

The legal progression is intentionally narrow:

Submitted -> PolicyEvaluating -> AwaitingApproval or ApprovedForExecution -> Executing -> Finalized / FailedTerminal / ReconciliationRequired

ReconciliationRequired may transition only to Finalized or FailedTerminal after the actual settlement outcome is resolved.

The critical invariants are:

1. at most one live execution attempt per immutable intent
2. terminal states do not transition backward into pre-execution states
3. uncertain outcomes are modeled explicitly, not guessed away

The current artifact already supports intent lifecycle management and rejects illegal transitions in tests such as `tests/test_intent_transitions.py`. That artifact evidence is important because it shows OmniClaw is not merely describing a state machine abstractly; it is already enforcing transition semantics in code.

---

## 8. Retry Safety, Idempotency, And Reconciliation

Retry logic is one of the most financially dangerous surfaces in autonomous systems.

OmniClaw’s model is that retries must be anchored to immutable business identity, not to transient RPC attempts. The implementation already derives idempotency keys in normalized form, demonstrated in `tests/test_idempotency.py`, and the product docs require caller-provided idempotency keys for job-based payments.

The stronger control-plane formulation is:

1. derive a stable settlement identity from immutable payment parameters
2. persist an execution-attempt record before calling the provider
3. submit provider-side idempotency keyed to the same identity
4. if a provider call may have happened and the outcome is uncertain, enter reconciliation rather than replay
5. replay only after authoritative proof that the earlier attempt did not settle

This rule is more precise than generic “idempotency support.” It means timeout is not failure. A provider call that may have happened moves the system into a different control path.

---

## 9. Policy Races And Atomic Reservation

A safe autonomous payments system cannot rely on point-in-time checks alone.

The OmniClaw artifact already includes reservation services, fund locks, and documentation stating that reservations hold spend capacity while fund locks serialize wallet execution. Tests such as `tests/test_payment_concurrency.py`, `tests/test_reservation_integrity.py`, and `tests/test_sdk_integration_extended.py` show that concurrency and reservation logic are treated as first-class implementation concerns.

The control-plane semantics are:

1. evaluate an intent against a specific policy version or snapshot
2. persist that version with the intent
3. reserve relevant spending capacity atomically when an intent becomes executable
4. keep the reservation while the intent is in flight
5. release the reservation only when the intent finalizes, fails terminally, or is explicitly revoked
6. allow emergency revalidation before execution under revocation, freeze, or emergency-stop conditions

This avoids two distinct failure classes:

- stale-approved execution after a policy change
- aggregate overspend under concurrent workers

This is one of the most publication-worthy parts of OmniClaw because it turns budget enforcement into a distributed systems correctness problem rather than a generic “payment limit” feature.

---

## 10. Counterparty-Type-Aware Policy

Not all recipients create the same risk.

The task-derived architecture, which is consistent with OmniClaw’s broader control model, makes this explicit:

- Human-operated service
  Standard recipient allowlist, ordinary approval thresholds, and contractual accountability.

- Internal service
  Potentially looser thresholds, but only when workload identity, service registry entry, destination account, and transaction class match internal control records.

- Autonomous agent
  Lower auto-approval ceilings, narrower transaction classes, dedicated allowlists, and escalation for novel destinations or unusual amounts.

This is not a cosmetic policy choice. It is a recognition that counterparty accountability, operational trust, and machine-speed request generation differ materially by counterparty class.

A worthwhile research claim here is that amount-only financial policy is insufficient for autonomous systems; counterparty class must be part of the policy decision.

---

## 11. Finality-Aware Policy

Payment rails are not uniform. Some allow intervention before finality, others do not.

That difference should change the control path.

- Reversible-before-finality rails can support a pending window, automated rechecks, cancellation or clawback, and somewhat looser approval thresholds where post-authorization intervention remains possible.

- Irreversible rails require stricter pre-execution controls: tighter limits, lower auto-approval thresholds, stronger destination verification, and no replay until reconciliation proves non-settlement.

This is another strong research contribution because it formalizes a dimension that generic payment APIs usually leave implicit: finality is a policy input, not just a rail detail.

---

## 12. Adversarial Counterparties And Bounded Blast Radius

OmniClaw addresses two related but distinct safety questions.

### 12.1 What can a compromised agent do?

The answer should be bounded externally by policy:

- single-payment limits
- rolling limits
- recipient controls
- transaction-class restrictions
- approval thresholds

This means an agent compromise becomes policy-bounded risk rather than direct wallet risk.

### 12.2 What can an adversarial counterparty do?

The architecture should limit:

- destination redirection through allowlists
- pull-style draining through push-only execution
- category abuse through transaction-class restrictions
- false outcome claims through independent settlement verification
- pre-finality abuse through reversible intervention windows where available

This distinction matters because “agent compromise” and “counterparty manipulation” are not the same threat, even though they often get bundled together in product discussion.

---

## 13. Auditability And Accountability

OmniClaw’s audit story is not just observability. It is an accountability chain.

For each material event, the system should be able to answer:

- which agent requested the payment
- which policy version allowed or blocked it
- whether approval was required
- which execution attempt ran
- what settlement rail was used
- how the final state was reached

The compliance architecture documentation in the repo is already strong on this point. For a research audience, the main refinement is to make clear that auditability is not a side effect of logs; it is a consequence of explicit authorization and state semantics.

---

## 14. Implementation Evidence

The credibility of OmniClaw as a research system comes from the fact that these ideas are not merely proposed. They are reflected in the artifact surface:

- intent lifecycle services in `src/omniclaw/intents/service.py`
- fund reservations in `src/omniclaw/intents/reservation.py`
- trust-layer types and verdicts in `src/omniclaw/identity/types.py`
- guard, reservation, and fund-lock documentation in `docs/FEATURES.md`
- compliance framing in `docs/compliance-architecture.md`
- product surfaces across buyer SDK, policy engine, and CLI workflows

There is also substantial test evidence:

- `tests/test_idempotency.py`
- `tests/test_intent_transitions.py`
- `tests/test_payment_concurrency.py`
- `tests/test_reservation_integrity.py`
- `tests/test_payment_failures.py`
- `tests/test_trust_gate.py`
- `tests/test_x402_idempotency.py`

That matters because it shows OmniClaw is not a speculative architecture. It is an implemented system with explicit correctness concerns.

---

## 15. Evaluation Agenda

To turn OmniClaw into a publishable systems/security paper, the next step is to convert its existing artifact surface into a structured evaluation.

### 15.1 Concurrency Safety

Measure whether atomic reservation prevents overspend compared with naive point-in-time approval under concurrent workers.

### 15.2 Retry Safety

Measure whether intent-bound idempotency plus reconciliation prevents duplicate settlement under crash and timeout scenarios.

### 15.3 Policy-Race Safety

Measure stale-approved execution under policy changes with and without versioned revalidation.

### 15.4 Finality-Aware Control

Compare approval and replay behavior on reversible versus irreversible rails.

### 15.5 Operational Overhead

Measure the latency and throughput cost of policy evaluation, reservation, and reconciliation relative to direct execution.

### 15.6 Trust And Counterparty Policy

Evaluate whether counterparty-type-aware policy reduces unsafe auto-approval compared with uniform thresholding.

---

## 16. Comparison Baselines

The natural baselines are:

1. Direct-wallet agent execution
2. Approval gateway without execution binding
3. Naive dedupe without explicit uncertain-outcome semantics

OmniClaw should be evaluated against these models, not just against “no system at all.”

---

## 17. Limitations

A rigorous paper should state limitations plainly.

- OmniClaw reduces but does not eliminate financial risk.
- It assumes trustworthy separation between control and execution domains.
- It depends on storage and locking behavior for some guarantees.
- Trust gating quality depends on identity and reputation signal quality.
- Regulatory alignment is not the same as legal compliance.

These are not weaknesses to hide. They are what make the paper credible.

---

## 18. Conclusion

Autonomous payments need more than settlement rails. They need a control architecture that answers who authorized this transaction, under which rules, with which state semantics, under which failure conditions, and with what recourse when the outcome is uncertain.

OmniClaw’s central contribution is to treat financial execution for autonomous systems as a control-plane problem rather than a wallet problem. By separating intent from settlement, binding execution to approved parameters, reserving capacity under concurrency, modeling uncertain outcomes explicitly, branching policy by counterparty type and finality, and preserving a tamper-evident authorization trail, the system provides a stronger authority model for agentic commerce than raw wallet delegation or settlement-only adapters.

The remaining work is not to invent the architecture. It is to evaluate and present it with the same precision with which it is already being built.

---

## Appendix A. Candidate Claims For External Use

These are safe, strong statements for a whitepaper, preprint, or outreach memo.

- OmniClaw is a control layer for autonomous payments, not just a settlement adapter.
- OmniClaw separates agent intent from settlement authority.
- OmniClaw enforces policy before funds move.
- OmniClaw uses reservation and locking semantics to reduce overspend risk under concurrency.
- OmniClaw treats uncertain outcomes as explicit reconciliation cases rather than ordinary failures.
- OmniClaw supports policy branching by counterparty type and rail finality.
- OmniClaw is backed by a working artifact with tests, demos, and operator controls.

## Appendix B. Candidate Next Documents

- Whitepaper v2 polished PDF
- Evidence matrix mapping claims to tests and code
- Technical article for engineers
- Short research-lab memo
