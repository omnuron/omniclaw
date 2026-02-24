# Technical Spec: OmniClaw Resilience Layer (Circuit Breakers)

> **Status:** Draft
> **Phase:** 2 (Resilience & Distribution)
> **Author:** Abiorh Claw (CTO)

## 1. Objective
To ensure **OmniClaw** never drops a payment due to transient infrastructure failures (e.g., Circle API downtime, Blockchain congestion, RPC timeouts).

**Goal:** Transform "Network Error" -> "Queued for Retry" automatically.

---

## 2. Architecture: The "Resilience Shell"

We will wrap the core `Execution Adapters` (Transfer, x402, Gateway) inside a **Resilience Shell**.

```mermaid
graph TD
    A[Agent Call pay()] --> B{Safety Kernel}
    B -->|Allowed| C[Resilience Shell]
    
    subgraph "Resilience Shell"
        C --> D{Circuit Breaker State?}
        D -->|CLOSED / Normal| E[Attempt Execution]
        D -->|OPEN / Broken| F[Queue for Later]
        
        E -->|Success| G[Return Success]
        E -->|Transient Fail| H[Retry Policy (Backoff)]
        H -->|Max Retries Exceeded| I[Trip Circuit -> OPEN]
        I --> F
    end
    
    F --> J[Persistent Job Queue (Redis)]
    J --> K[Recovery Worker]
    K -->|Poll| D
```

---

## 3. Component 1: Distributed Circuit Breaker
Unlike a standard local library (like `pybreaker`), our agents might run across multiple containers. We need a **Distributed Circuit Breaker** backed by Redis.

**Key States:**
1.  **CLOSED (Green):** Normal operation. Traffic flows.
2.  **OPEN (Red):** Failure threshold exceeded (e.g., 5 failures in 10s). Fast-fail all requests immediately.
3.  **HALF-OPEN (Yellow):** After `recovery_timeout`, let 1 request through to test connection.

**Storage Schema (Redis):**
*   `circuit:{service_name}:failures`: Counter (TTL 1 min).
*   `circuit:{service_name}:state`: "OPEN" | "CLOSED" | "HALF-OPEN".
*   `circuit:{service_name}:recovery_ts`: Timestamp when we retry.

**Services to Protect:**
*   `circle_api` (The most critical dependency).
*   `chain_rpc:{network_id}` (Base, Eth, etc.).
*   `x402_facilitator`.

---

## 4. Component 2: Intelligent Retry (Tenacity)
We will use the **`tenacity`** library for robust local retries *before* tripping the circuit.

**Policy:**
*   **Wait:** Exponential Backoff (Wait 1s, 2s, 4s, 8s...).
*   **Stop:** After 5 attempts OR 30 seconds.
*   **Retry On:** `NetworkError`, `500`, `502`, `503`, `504`.
*   **NEVER Retry On:** `400` (Bad Request), `401` (Auth), `402` (Payment Required - logic handled elsewhere).

---

## 5. Component 3: Store-and-Forward (The "Outbox")
If the Circuit is **OPEN** (System Down), we do not crash. We **Queue**.

**The Outbox Pattern:**
1.  Agent calls `pay()`.
2.  Circuit is OPEN.
3.  OmniClaw saves request to `outbox:{wallet_id}` (Redis List).
4.  Returns `status="queued"` to Agent.
5.  **Background Worker:** Monitors `outbox`, checks Circuit state, and processes when CLOSED.

---

## 6. Implementation Plan

### Step 1: Core Dependencies
Add `tenacity` and `redis` (if not present) to `pyproject.toml`.

### Step 2: `src/omniclaw/resilience/circuit.py`
Implement the `DistributedCircuitBreaker` class.

### Step 3: `src/omniclaw/resilience/retry.py`
Define standard retry decorators (`@retry_payment_api`).

### Step 4: Adapter Integration
Wrap `CircleAdapter.execute()` with:
```python
@circuit_breaker(service="circle_api")
@retry_policy
async def execute(...):
    ...
```

---

## 7. Success Criteria
*   **Test:** Simulate Circle API 500 errors.
*   **Result:** Agent does not crash. Request waits/retries.
*   **Test:** Simulate 100% outage.
*   **Result:** Circuit trips to OPEN. Subsequent calls fail immediately (saving latency) and are Queued.
