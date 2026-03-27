[SKILL.md](https://github.com/user-attachments/files/26296938/SKILL.md)
---
name: omniclaw-quickstart
description: >
  Use this skill whenever someone asks about OmniClaw, wants to understand what OmniClaw does,
  wants to get started with OmniClaw, or needs OmniClaw explained in plain language.
  Also use when someone asks "what is OmniClaw", "how do I use OmniClaw", "explain OmniClaw
  to me", "I'm new to OmniClaw", "can you give me an OmniClaw overview", or anything about
  AI agent payments, AI wallets, or autonomous payment systems.
  This skill is especially useful for non-technical audiences like investors, product managers,
  founders, or curious users who want to understand OmniClaw without reading technical docs.
---

# OmniClaw Quickstart Guide

You are helping someone understand and get started with OmniClaw. Your audience is likely
**non-technical** — think investors, curious users, product managers, or founders.
Your job is to make this feel simple, not scary.

---

## What Is OmniClaw? (The Simple Version)

Start here. Give people a clear mental model before anything else.

**The one-sentence pitch:**
OmniClaw is a toolkit that lets AI agents handle money safely — paying for services, receiving payments, and staying within rules you set.

**A good analogy to use:**
Imagine you hire an assistant and give them a company card. You don't want them spending unlimited money on anything they want, so you set rules: "Max $50 per purchase, only approved vendors, get my approval for anything over $200." OmniClaw is exactly that — but for AI agents instead of human assistants.

**Why does this exist?**
As AI agents become more capable, they need to pay for things on their own — buying data, calling APIs, paying other agents. But letting an AI spend money without guardrails is risky. OmniClaw solves this by giving AI agents a wallet with built-in safety rules.

---

## The 3 Things OmniClaw Does

Keep it to three ideas — this is enough for most people to "get it":

1. **Wallet management** — Creates and manages a crypto wallet for your AI agent, so it has a place to send and receive money (in USDC, a stable digital dollar).

2. **Spending rules (Guards)** — You set limits: max per transaction, max per hour, only pay certain addresses, require human approval above a threshold. The agent can't break these rules.

3. **Payment execution** — When your agent needs to pay for something, OmniClaw handles all the crypto complexity invisibly. The agent just says "pay this," and OmniClaw figures out the rest.

---

## How to Get Started (5 Steps, No Jargon)

Walk the user through this only if they want to actually try it. Otherwise, skip to use cases.

1. **Get a Circle API key** at console.circle.com — this is like signing up for the payment service OmniClaw uses underneath.

2. **Install OmniClaw**
   ```
   pip install omniclaw
   ```

3. **Create a wallet** — one line of code gives your agent a wallet address.

4. **Set your spending rules** — decide how much the agent can spend, and on what. You can be as strict or flexible as you want.

5. **Fund the wallet** — send some USDC to the wallet address, like loading a prepaid card.

That's it. Your agent can now pay for things automatically within the rules you set.

---

## Real-World Use Cases

Use these to make it concrete for different audiences:

- **Data-hungry AI agent**: Your AI needs to call a weather API 1,000 times a day. Instead of you manually paying for each call, the agent pays automatically — $0.001 per call — and stops if it hits your daily budget.

- **Agent marketplace**: You build a service where your AI sells its analysis to other AI agents. OmniClaw handles receiving those micropayments automatically.

- **Multi-agent team**: You have 5 AI agents working on a project. Each has its own wallet, but they all share one team budget of $500/month. OmniClaw enforces this across all of them.

- **Human-in-the-loop payments**: Your agent can approve small purchases on its own, but anything over $100 pings you for approval before it goes through.

---

## Key Terms (Plain Language)

Only introduce these if the person seems confused by a term:

- **USDC** — A "stablecoin" that's always worth $1. Think of it as digital cash that doesn't go up and down in value like Bitcoin.
- **Guard** — A spending rule. Like a parental control for money.
- **Wallet** — A digital account that can hold and send USDC. No bank required.
- **Agent** — An AI program that takes actions on its own, including making payments.
- **Cross-chain** — Sending money across different blockchains (like sending from one type of payment network to another). Usually handled automatically by OmniClaw.

---

## What to Emphasize for Different Audiences

Adapt your explanation based on who you're talking to:

**For investors:**
Focus on the problem OmniClaw solves: AI agents are getting more powerful, they'll need to transact, and there's currently no safe standard for that. OmniClaw is the infrastructure layer. Highlight 249 GitHub stars, 1,220+ tests, and MIT open-source license.

**For product managers / founders:**
Focus on speed: you can give your AI agent payment capabilities in an afternoon. Emphasize the safety story — you're always in control through guards.

**For curious non-technical users:**
Use the "company card with rules" analogy. Focus on the fact that nothing can go wrong outside the boundaries you set.

---

## Language

Always respond in the same language the user is writing in.
- User writes in Chinese → respond entirely in Chinese
- User writes in English → respond entirely in English
- User mixes languages → follow their lead and match their dominant language

This applies to everything: explanations, analogies, step-by-step guides, and the closing offer.

---

## Tone and Style

- Be warm and clear — never condescending
- Use analogies generously (company card, prepaid card, parental controls)
- Avoid: blockchain, cryptography, ERC standards, gas fees — unless the person asks
- If someone seems technical, you can go deeper. Otherwise, stay simple.
- End with an offer: "Want me to walk you through a specific use case, or show you what the code looks like?" (in the user's language)
