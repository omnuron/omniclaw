
OmniAgentPay
Feature System Design

ERC-8004 Agent Identity & Trust Integration
Phase 3, Feature #5 — The Trust Layer
Target Completion: Q2 2026

Version	1.0 — Initial Draft
Status	Ready for Engineering Review
Author	OmniAgentPay Product Team
Audience	Engineering, Architecture, QA
 
1. Overview & Objectives
This document provides a complete technical system design for integrating ERC-8004 (Trustless Agents) into OmniAgentPay's payment pipeline. The integration enables OmniAgentPay to verify the on-chain identity and reputation of any recipient agent before releasing funds, eliminating the risk of paying fraudulent or unverified bots in agent-to-agent (A2A) commerce.

The Core Problem
When Agent A hires Agent B to perform a task, there is no shared trust infrastructure. Agent B could be a fake bot, a known scammer, or a poorly-rated agent. Today, OmniAgentPay cannot make this verification automatically — every payment is blind to recipient identity.

ERC-8004 solves this by providing a neutral, on-chain registry where agents publish their identity, and where reputation feedback is stored permissionlessly. OmniAgentPay will become the payment layer that reads and enforces this registry at transaction time.

1.1 Objectives
•	Integrate ERC-8004 Identity Registry lookup into the OmniAgentPay pre-payment check flow
•	Integrate ERC-8004 Reputation Registry scoring into configurable risk policies
•	Block or hold payments to agents failing identity/reputation thresholds
•	Expose SDK controls for operators to configure trust policies per-wallet
•	Provide full audit trail of every trust check performed

1.2 Success Metrics
Metric	Target	Measurement
ERC-8004 lookup latency (p99)	< 200ms	APM trace on registry call
Payment false-block rate	< 0.1%	Manual review of blocked tx
Trust check audit coverage	100%	Every payment has a trust log entry
SDK integration time	< 1 day	Developer feedback
Sybil detection accuracy	> 95%	Red team simulation results
 
2. System Architecture
2.1 High-Level Architecture
The ERC-8004 integration lives as a middleware layer inside OmniAgentPay's payment pipeline. Every call to pay() or escrow() passes through the Trust Gate before funds move. The Trust Gate orchestrates calls to two external systems: the ERC-8004 on-chain registries (via an RPC provider), and OmniAgentPay's own internal Policy Engine.

Architecture Layers (Top to Bottom)
[ SDK / API ]  →  Developer calls client.pay(recipient, amount)
[ Payment Router ]  →  Validates input, enriches request with wallet context
[ Trust Gate ]  →  NEW — ERC-8004 lookup + policy evaluation
[ Atomic Guards ]  →  Existing spend-limit enforcement
[ Payment Executor ]  →  Stablecoin transfer via Circle / Base
[ Audit Logger ]  →  Immutable log of every action

2.2 Trust Gate — Detailed Component Design
The Trust Gate is the core new component. It is a stateless service that receives a payment request and returns either APPROVED, BLOCKED, or HELD with a structured reason.

2.2.1 Trust Gate Sub-Components

Component	Responsibility	Technology
Identity Resolver	Fetches agent's ERC-8004 Identity NFT (token ID + agentURI) for a given wallet address	Ethers.js / viem, ERC-721 read
Metadata Fetcher	Retrieves off-chain JSON registration file from agentURI (IPFS / HTTPS)	HTTP client, IPFS gateway
Reputation Aggregator	Reads raw feedback signals from ERC-8004 Reputation Registry and computes a normalized score	Contract read, internal scoring algo
Policy Engine	Applies operator-configured rules (min score, required attestations, blocked addresses) to produce a verdict	Rules engine, Redis cache
Trust Cache	Caches lookup results with TTL to reduce RPC load and latency	Redis, 5-min default TTL
Audit Emitter	Emits a structured TrustCheckEvent to the audit log for every evaluation	Internal event bus / Postgres

2.3 Data Flow Diagram
The sequence below represents a complete pay() call with Trust Gate active:

Payment Flow with ERC-8004 Trust Gate
1.  Developer calls:  client.pay({ to: agentB_address, amount: 10, currency: 'USDC' })

2.  Payment Router validates input format, checks sender wallet balance.

3.  Trust Gate receives (sender, recipient, amount, policy_id):
    a.  Check Trust Cache for recipient — if HIT, skip to step 3e.
    b.  Identity Resolver calls ERC-8004 Identity Registry (ERC-721 ownerOf / tokenURI).
    c.  Metadata Fetcher retrieves agentURI JSON (company, services, attestations).
    d.  Reputation Aggregator reads feedback signals from Reputation Registry contract.
    e.  Policy Engine evaluates all signals against operator policy.
    f.  Audit Emitter writes TrustCheckEvent (result, scores, latency, block reason).

4.  If APPROVED  →  Payment passes to Atomic Guards → Executor → funds move.
5.  If BLOCKED   →  Payment rejected, error returned to SDK with reason code.
6.  If HELD      →  Payment queued for human review; owner notified via webhook.
 
3. ERC-8004 Contract Interface
3.1 Identity Registry Contract
The Identity Registry is an ERC-721 contract deployed on Ethereum mainnet and supported L2s (Base, Optimism, Arbitrum). OmniAgentPay needs read-only access to two functions:

ownerOf(tokenId) → address
Used to confirm a given token is actively owned (not burned). OmniAgentPay will derive the token ID from the recipient's wallet address using the registry's lookup function.

tokenURI(tokenId) → string
Returns the agentURI pointing to the off-chain JSON registration file. This is the entry point to all agent metadata.

3.2 Agent Registration File (agentURI JSON Schema)
This is the structured JSON document fetched from the agentURI. OmniAgentPay parses the following fields:

Field	Type	OmniAgentPay Usage
name	string	Display in audit logs and developer dashboard
description	string	Informational only
organization	string	Used by Policy Engine for org-level whitelisting
services[]	array	Verify agent offers expected service type
endpoints[]	array	Validate A2A / MCP endpoint format
attestations[]	array	Check for required third-party verifications
trust_models[]	array	Determine which validation paths are available
created_at	ISO8601	Flag newly created agents as higher risk

3.3 Reputation Registry Contract
The Reputation Registry stores raw feedback signals. OmniAgentPay reads these signals and applies its own scoring algorithm. The contract exposes:

getFeedback(agentAddress) → FeedbackRecord[]
Returns an array of feedback entries. Each record contains: submitter address, numeric score (0-100), tags (e.g. 'fast', 'fraud', 'reliable'), timestamp, and optional metadata CID.

Reputation Scoring Algorithm
OmniAgentPay's Reputation Aggregator computes a Weighted Trust Score (WTS) from raw signals. The algorithm is:

WTS Calculation Formula
1.  Filter out self-reviews (submitter == recipient).
2.  Apply recency decay: signals older than 90 days weighted at 50%; older than 180 days at 20%.
3.  Boost weight of verified submitters (submitters who are themselves ERC-8004 registered).
4.  Flag fraud tags: any single 'fraud' or 'scam' tag triggers a mandatory HELD status regardless of numeric score.
5.  Compute weighted average of numeric scores.
6.  Apply minimum sample size guard: agents with fewer than 3 feedback entries get a 'NEW_AGENT' flag.
7.  Output: { wts: 0-100, flags: string[], sample_size: int, new_agent: bool }
 
4. Policy Engine Design
4.1 Overview
The Policy Engine is what makes the trust integration configurable per operator. Rather than a single hard-coded threshold, OmniAgentPay supports flexible policy objects that operators attach to their wallets. This allows an enterprise use case (very strict) and a startup use case (more permissive) to coexist on the same platform.

4.2 Policy Object Schema
Operators configure a TrustPolicy object via the OmniAgentPay dashboard or API:

TrustPolicy Schema (JSON)
{
  "policy_id": "pol_prod_strict",
  "name": "Production Strict",
  "identity_required": true,          // Block if no ERC-8004 identity found
  "min_wts": 70,                       // Minimum Weighted Trust Score (0-100)
  "min_feedback_count": 3,             // Block if fewer than N feedback entries
  "require_attestations": ["kyb"],     // Require specific attestation types
  "org_whitelist": ["acme-corp"],      // Always allow agents from these orgs
  "address_blocklist": ["0xDEAD..."],  // Always block specific addresses
  "new_agent_action": "HOLD",          // APPROVE | HOLD | BLOCK for new agents
  "fraud_tag_action": "BLOCK",         // Always block if fraud tag present
  "unresolvable_action": "HOLD",       // Action if ERC-8004 call fails
  "high_value_threshold_usd": 500,     // Trigger stricter checks above this
  "high_value_min_wts": 85             // Min WTS for high-value payments
}

4.3 Policy Evaluation Logic
The Policy Engine evaluates checks in the following strict order. The first failing check wins and sets the verdict:

Priority	Check	Condition	Verdict
1	Address Blocklist	recipient in policy.address_blocklist	BLOCKED
2	Org Whitelist	agent.organization in policy.org_whitelist	APPROVED (skip rest)
3	Identity Check	identity_required == true AND no ERC-8004 found	BLOCKED
4	Fraud Tag Check	WTS.flags contains 'fraud' or 'scam'	BLOCKED (or HELD per config)
5	New Agent Check	WTS.new_agent == true	HELD (or per config)
6	Min Feedback Count	WTS.sample_size < policy.min_feedback_count	HELD
7	Min WTS Check	WTS.wts < policy.min_wts	BLOCKED
8	High-Value WTS Check	amount > threshold AND WTS.wts < high_value_min_wts	HELD
9	Attestation Check	required attestations missing from agent metadata	HELD
10	All Pass	No checks failed	APPROVED
 
5. SDK Interface Design
5.1 New SDK Methods
The integration surfaces through the existing OmniAgentPay SDK with minimal API surface changes. All new methods are backwards-compatible — existing pay() calls continue to work, defaulting to a 'permissive' policy if none is configured.

5.1.1 Attach a Trust Policy to a Wallet

SDK Example: Set Trust Policy
// Attach a policy to a wallet at configuration time
const client = new OmniAgentPay({
  walletId: 'wal_abc123',
  trustPolicy: {
    preset: 'strict',         // Use a built-in preset
    // OR provide a custom policy_id created in the dashboard
    // policyId: 'pol_prod_strict'
  }
});

5.1.2 Pay with Trust Gate Active (Automatic)

SDK Example: Standard Pay (Trust Gate Runs Automatically)
try {
  const result = await client.pay({
    to: '0xAgentB_Address',
    amount: '10.00',
    currency: 'USDC',
    memo: 'Data analysis task #42'
  });

  console.log(result.status);          // 'APPROVED'
  console.log(result.trust.wts);       // 82
  console.log(result.trust.flags);     // []
  console.log(result.txHash);          // '0x...'

} catch (err) {
  if (err.code === 'TRUST_BLOCKED') {
    console.log(err.reason);           // 'FRAUD_TAG'
    console.log(err.trust.wts);        // 12
    console.log(err.trust.flags);      // ['fraud']
  }
  if (err.code === 'TRUST_HELD') {
    console.log(err.holdId);           // 'hold_xyz789'
    console.log(err.reason);           // 'NEW_AGENT'
  }
}

5.1.3 Standalone Trust Lookup

SDK Example: Check an Agent's Trust Score Without Paying
// Useful for pre-screening before committing to hire an agent
const trust = await client.trust.lookup('0xAgentB_Address');

console.log(trust.identity_found);    // true
console.log(trust.wts);               // 82
console.log(trust.flags);             // []
console.log(trust.new_agent);         // false
console.log(trust.organization);      // 'Acme Corp'
console.log(trust.attestations);      // ['kyb', 'soc2']
console.log(trust.policy_verdict);    // 'APPROVED'

5.1.4 Simulate Payment with Trust Check

SDK Example: Simulate (No Real Money, Full Trust Check Runs)
const simulation = await client.simulate({
  to: '0xAgentB_Address',
  amount: '500.00',
  currency: 'USDC'
});

console.log(simulation.would_succeed);   // false
console.log(simulation.block_reason);    // 'HIGH_VALUE_WTS_FAIL'
console.log(simulation.trust.wts);       // 72  (below high-value threshold of 85)
console.log(simulation.estimated_fee);   // '$0.05'
 
6. Error Codes & Response Schema
6.1 Trust Gate Error Codes
Error Code	HTTP Status	Meaning	Suggested Action
TRUST_BLOCKED	402	Payment blocked by policy (e.g. fraud tag, low WTS)	Do not retry. Log and alert human operator.
TRUST_HELD	202	Payment queued for human review	Poll holdId status endpoint or await webhook.
TRUST_NO_IDENTITY	402	Recipient has no ERC-8004 identity	Inform recipient to register on ERC-8004.
TRUST_REGISTRY_ERROR	503	ERC-8004 registry call failed (RPC timeout etc.)	Trust Gate applies unresolvable_action policy.
TRUST_METADATA_ERROR	502	agentURI JSON fetch failed	Partial data used; identity confirmed but metadata skipped.
TRUST_POLICY_NOT_FOUND	400	Configured policy_id does not exist	Check wallet trust policy configuration.

6.2 Trust Check Result Object
Every payment response (success or error) includes a trust object for full observability:

TrustCheckResult Schema
{
  identity_found:    bool,      // Was ERC-8004 identity located?
  token_id:          string,    // ERC-721 token ID (if found)
  organization:      string,    // From agentURI metadata
  wts:               int,       // Weighted Trust Score 0-100 (null if no identity)
  sample_size:       int,       // Number of feedback signals used
  new_agent:         bool,      // True if fewer than 3 feedback entries
  flags:             string[],  // e.g. ['fraud', 'new_agent', 'low_wts']
  attestations:      string[],  // Attestations found in agent metadata
  policy_id:         string,    // Which policy was applied
  verdict:           string,    // APPROVED | BLOCKED | HELD
  block_reason:      string,    // Machine-readable reason (if BLOCKED/HELD)
  check_latency_ms:  int,       // Time taken for trust check
  cache_hit:         bool,      // Was result served from cache?
  checked_at:        ISO8601    // Timestamp of evaluation
}
 
7. Infrastructure & Performance
7.1 Trust Cache Design
To meet the 200ms p99 latency target, all ERC-8004 lookups are cached in Redis. Cache keys are deterministic based on the recipient address and the chain ID.

Cache Key Pattern	TTL	Invalidation Trigger
trust:{chainId}:{address}:identity	5 minutes	Manual purge via admin API
trust:{chainId}:{address}:reputation	2 minutes	Automatic on TTL expiry
trust:{chainId}:{address}:metadata	10 minutes	agentURI change detected
trust:policy:{policy_id}	60 minutes	Policy update via dashboard

Cache miss latency budget: Identity lookup (80ms) + Metadata fetch (60ms) + Reputation read (40ms) + Policy eval (10ms) = 190ms total, within the 200ms p99 target.

7.2 RPC Provider Strategy
ERC-8004 is deployed on Ethereum mainnet and EVM L2s. OmniAgentPay's Trust Gate will use a multi-provider fallback strategy to ensure reliability:
•	Primary: Alchemy (low latency, high reliability)
•	Fallback 1: Infura (automatic failover if Alchemy returns 5xx)
•	Fallback 2: Public RPC (last resort, rate-limited, used only to prevent full outage)
•	Chain selection: Auto-detect from recipient's registered chain ID in ERC-8004 metadata

7.3 Circuit Breaker Integration
The Trust Gate integrates with OmniAgentPay's existing Circuit Breaker infrastructure. If the ERC-8004 registry becomes unreachable, the circuit opens and the policy's unresolvable_action is applied (default: HOLD). This prevents the trust layer from becoming a payment outage vector.

Circuit Breaker Thresholds for ERC-8004
OPEN circuit if:  error rate > 20% in a 60-second window
HALF-OPEN after:  30 seconds (probe with a single test call)
CLOSE circuit if: 3 consecutive successful probes
While OPEN:       Apply unresolvable_action policy (HOLD by default)
 
8. Audit & Observability
8.1 TrustCheckEvent Schema
Every invocation of the Trust Gate — whether the payment proceeds or not — emits a structured event to the audit log. This is immutable and forms the compliance record for every trust decision.

TrustCheckEvent (Postgres / Event Bus)
{
  event_id:         uuid,
  payment_id:       string,       // Links to the parent payment attempt
  wallet_id:        string,       // OmniAgentPay wallet (sender)
  sender_address:   string,
  recipient_address: string,
  amount_usd:       decimal,
  currency:         string,
  chain_id:         int,
  policy_id:        string,
  verdict:          string,       // APPROVED | BLOCKED | HELD
  block_reason:     string,
  wts:              int,
  flags:            string[],
  identity_found:   bool,
  cache_hit:        bool,
  latency_ms:       int,
  rpc_provider:     string,       // Which provider served the lookup
  created_at:       timestamp
}

8.2 Metrics & Alerting
Metric	Type	Alert Threshold
trust_gate_latency_p99	Histogram	Alert if > 300ms for 5 min
trust_gate_block_rate	Counter	Alert if > 5% of payments in 10 min
trust_gate_hold_rate	Counter	Alert if > 10% of payments in 10 min
erc8004_rpc_error_rate	Counter	Alert if > 5% in 60 sec (circuit breaker trigger)
trust_cache_hit_rate	Gauge	Alert if < 60% (cache health degraded)
unresolved_holds_age	Gauge	Alert if any hold > 24 hrs without review
 
9. Security Considerations
9.1 Known Threat Vectors & Mitigations
Threat	Description	Mitigation
Sybil Attack	Bad actor creates many ERC-8004 identities to inflate reputation	Minimum feedback count gate; weighted scoring favors verified submitters; new_agent flag triggers HOLD
Identity Spoofing	Agent claims to be a legitimate org by copying metadata	Organization field is informational only — trust is anchored to on-chain token ownership, not claimed name
Metadata Manipulation	Agent points agentURI to malicious or misleading JSON	Metadata parsing is sandboxed; fields are schema-validated; unknown fields are ignored
Cache Poisoning	Attacker exploits cache to serve stale good reputation for a newly-fraudulent agent	Short TTLs (2-5 min); blocklist checks bypass cache entirely; fraud tag always triggers live re-fetch
RPC Manipulation	Compromised RPC provider returns false registry data	Multi-provider verification for high-value payments; provider signature validation where supported
Feedback Spam	Flooding reputation registry with fake positive signals	Recency decay; verified submitter weighting; fraud tags irreversible regardless of positive signal volume

9.2 Blocklist Management
OmniAgentPay maintains an internal address blocklist that is checked before any ERC-8004 lookup. This blocklist is populated from three sources:
•	Operator-configured blocklists (per wallet policy)
•	OmniAgentPay platform-level blocklist (known fraud addresses, managed by Trust & Safety team)
•	Real-time feeds from industry threat intelligence partners (e.g. Chainalysis, TRM Labs)
The platform-level blocklist is enforced even if an operator has not configured a custom policy. It cannot be overridden by any operator.
 
10. Implementation Plan
10.1 Phased Delivery
Sprint	Duration	Deliverables
Sprint 1	2 weeks	Identity Resolver + Trust Cache + ERC-8004 contract integration on testnet. Unit tests for all registry calls.
Sprint 2	2 weeks	Reputation Aggregator + WTS scoring algorithm. Policy Engine with preset policies (permissive, standard, strict). Integration tests.
Sprint 3	2 weeks	SDK interface changes (pay(), trust.lookup(), simulate() with trust). Dashboard UI for policy configuration. Error codes.
Sprint 4	1 week	Audit Logger + TrustCheckEvent schema. Metrics, alerting setup. Circuit Breaker integration for Trust Gate.
Sprint 5	1 week	Security review + red team simulation. Performance testing against 200ms p99 target. Mainnet deployment.

10.2 Definition of Done
•	All unit and integration tests pass (coverage > 90% for Trust Gate module)
•	p99 latency target of < 200ms validated under load (500 concurrent requests)
•	Security red team has completed sybil and spoofing simulation
•	SDK changelog and developer documentation published
•	Dashboard policy editor live in staging environment
•	Audit log verified to capture 100% of trust check events
•	Circuit breaker tested with simulated RPC outage
•	Mainnet ERC-8004 contract addresses confirmed and locked in config

10.3 Dependencies & Risks
Dependency / Risk	Type	Mitigation
ERC-8004 mainnet contract stability	External	Lock to specific contract address + ABI version; monitor for upgrades
IPFS agentURI availability	External	Timeout after 3s; treat metadata fetch failure as partial data, not full block
RPC provider rate limits	External	Negotiate enterprise tier; implement multi-provider fallback
Operator policy adoption	Business	Ship with sensible defaults; make strict policy opt-in not default
False positive blocks harming legitimate agents	Product	Hold (not Block) by default for ambiguous cases; provide appeal flow via dashboard

Appendix: Related Protocols

Protocol	Role in Ecosystem	OmniAgentPay Touch Point
ERC-8004	On-chain agent identity and reputation registry	Trust Gate reads identity + reputation registries pre-payment
x402	HTTP 402 Payment Required — toll booth for agent API access	OmniAgentPay executes payment; trust check on x402 service provider
A2A (Google)	Agent-to-agent communication protocol	ERC-8004 metadata advertises A2A endpoints; used in escrow flow
AP2 (Google)	Human-authorization mandate for agent purchases	OmniAgentPay validates AP2 signature in Phase 4 feature #9
UCP	Universal Commerce Protocol for agent shopping	OmniAgentPay pays UCP checkout invoices; trust check on UCP merchant

OmniAgentPay — Confidential & Internal Use Only
