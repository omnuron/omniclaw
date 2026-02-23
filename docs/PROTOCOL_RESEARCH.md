# Deep Research: Agentic Commerce Protocols (2025-2026)

> **Research Date**: January 2026
> **Scope**: Universal Commerce Protocol (UCP), Agent Payments Protocol (AP2), ERC-8004, x402
> **Context**: Strategic positioning for OmniClaw

---

## 1. Universal Commerce Protocol (UCP)
**"The Language of Agentic Commerce"**

*   **Origin**: Google (with Shopify, Etsy, Wayfair, Walmart).
*   **Core Purpose**: A standard for connecting AI surfaces (Google Search, Gemini, Custom Agents) to business backends (Catalogs, Inventory, Carts).
*   **Key Primitives**:
    1.  **Identity Linking**: Securely linking a user's AI agent identity to their merchant account.
    2.  **Cart Management**: Standardized way for agents to read/write to merchant carts.
    3.  **Checkout**: Handoff mechanism from agent to merchant payment flow.
*   **Relevance to OmniClaw**:
    *   UCP handles the *shopping journey* (finding product, adding to cart).
    *   UCP hands off to **AP2** for the actual payment authorization.
    *   **Opportunity**: OmniClaw can act as the **payment executor** for UCP checkouts when the merchant accepts crypto/USDC.

---

## 2. Agent Payments Protocol (AP2)
**"The Authorization Layer"**

*   **Origin**: Google + 60 partners (PayPal, Mastercard, Coinbase).
*   **Core Innovation**: **Verifiable Intent & Mandates**.
*   **Problem Solved**: "Hallucination-driven spending". How do you know the user *actually* wanted to buy this?
*   **Mechanism**:
    *   **Intent Mandate**: Signed cryptographic proof of user's request ("Buy running shoes under $100").
    *   **Cart Authorization**: Agent constructs a cart, user (or policy) signs it.
    *   **Payment Authorization**: The final trigger to move funds.
*   **Technical Flow**:
    1.  User delegates task → Creates **Intent Mandate**.
    2.  Agent finds item → Creates **Cart**.
    3.  Agent requests **Cart Authorization** (matches Intent?).
    4.  **Payment Processor** executes based on valid authorization.
*   **Relevance to OmniClaw**:
    *   **High Priority**. OmniClaw's "Safety Kernel" should **verify AP2 Mandates** before releasing funds.
    *   We are the "Payment Processor" in AP2 terminology if paying via USDC.

---

## 3. ERC-8004: Trustless Agents
**"The On-Chain Trust Layer"**

*   **Origin**: MetaMask, Google, Coinbase, Ethereum Foundation (EIP Draft Aug 2025).
*   **Core Purpose**: Decentralized registry for agent identity and reputation.
*   **Components**:
    1.  **Identity Registry (ERC-721)**: Agents are NFTs. `AgentID` links to metadata (capabilities, owner).
    2.  **Reputation Registry**: On-chain log of feedback signals (Success/Fail/Rating).
    3.  **Validation Registry**: Hooks for proving task completion (TEEs, zkML).
*   **Workflow**:
    *   Register Agent → Discover Peers → Execute Task → Validate → **Pay**.
*   **Relevance to OmniClaw**:
    *   **Identity**: We should use ERC-8004 `AgentID` for our wallet metadata.
    *   **Trust**: Before sending funds, OmniClaw can check the recipient's ERC-8004 Reputation Score.
    *   **Payment**: We are the settlement layer for ERC-8004 interactions.

---

## 4. x402 Protocol
**"The HTTP Execution Layer"**

*   **Origin**: Coinbase + x402 Foundation.
*   **Core Purpose**: "Payment Required" status code for the web.
*   **Mechanism**:
    *   **Request**: `GET /api/resource`
    *   **Response**: `402 Payment Required`
        *   Header: `X-Payment-Required` (or Body keys: `payTo`, `amount`, `asset`, `network`)
    *   **Retry**: `GET /api/resource`
        *   Header: `X-Payment-Signature` (Signed EIP-712 payload)
*   **Relevance to OmniClaw**:
    *   **Core Competency**: We *already* support this (`protocols/x402.py`).
    *   **Role**: We are the **Client SDK** that automates the 402 handshake.

---

## Synthesis: The OmniClaw Strategy

We are the **Execution Infrastructure** that bridges these layers.

1.  **The Shopping Layer (UCP)**: Agent finds items.
2.  **The Trust Layer (ERC-8004)**: Agent verifies the seller is legit.
3.  **The Auth Layer (AP2)**: Agent proves the user authorized this spend (Mandate).
4.  **The Payment Layer (x402/OmniClaw)**: **We actually move the USDC.**

### Our Unique Value Proposition
*   UCP/AP2 define *how to talk* and *how to authorize*.
*   ERC-8004 defines *who to trust*.
*   **OmniClaw defines *how to pay* (safely, atomically, on-chain).**

We are the **muscle** to their **brains**.
