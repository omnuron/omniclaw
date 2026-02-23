"""
Example: Gemini Agent with OmniClaw
---------------------------------------
Demonstrates how to integrate OmniClaw with Google's Gemini models
using Function Calling to enable autonomous agentic payments on Arc.

Targeting: "Best use of Gemini" & "Best Trustless AI Agent" tracks.

Requirements:
    pip install google-generativeai
"""

import asyncio
import logging

try:
    import google.generativeai as genai
except ImportError:
    print("⚠️  google-generativeai not installed. This is a code example.")
    genai = None

from omniclaw import Network, OmniClaw  # noqa: E402

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemini_agent")


async def pay_tool(recipient: str, amount: str, purpose: str = "Payment") -> dict:
    """
    Executes a USDC payment on Arc.

    Args:
        recipient: The wallet address or URL to pay.
        amount: The amount of USDC to send.
        purpose: Human-readable reason for the payment.
    """
    logger.info(f"🤖 Agent invoking pay_tool: {amount} USDC -> {recipient}")

    # Initialize OmniClaw (Auto-config from env)
    # Using Arc Testnet for Hackathon
    async with OmniClaw(network=Network.ARC_TESTNET) as client:
        # 1. Get Wallet (Simulation)
        # In prod, you'd load the specific agent's wallet
        wallets = await client.list_wallets()
        if not wallets:
            return {"error": "No agent wallet available"}

        agent_wallet = wallets[0]

        # 2. Add Guardrails (Dynamic Safety)
        # Ensure we don't spend too much per prompt
        await client.add_single_tx_guard(agent_wallet.id, max_amount="50.00", name="prompt_safety")

        # 3. Execute Payment
        result = await client.pay(
            wallet_id=agent_wallet.id,
            recipient=recipient,
            amount=amount,
            purpose=purpose,
            wait_for_completion=True,
        )

        if result.success:
            return {
                "status": "success",
                "tx_hash": result.blockchain_tx,
                "network": "Arc Check-Testnet",  # Arc Check
            }
        else:
            return {"status": "failure", "error": str(result.error)}


async def run_agent_loop(user_prompt: str):
    """Simulates a Gemini Agent Loop processing a payment request."""

    print(f"User: {user_prompt}")

    # 1. Define Tools for Gemini
    # tools_def = [pay_tool]

    # 2. Simulate Gemini Response (since we don't have a real API key in this context)
    # In reality: response = model.generate_content(prompt, tools=tools_def)
    print("🤖 Gemini: Thinking...")
    await asyncio.sleep(1.0)

    # Mocking Gemini's decision to call the tool
    if "pay" in user_prompt.lower() and "coffee" in user_prompt.lower():
        print("🤖 Gemini: I detected a payment intent. Invoking `pay_tool`...")

        tool_args = {
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",  # Coffee Shop
            "amount": "5.00",
            "purpose": "Coffee for user",
        }

        # 3. Execute Tool
        result = await pay_tool(**tool_args)

        # 4. Generate Final Response
        print(f"🤖 Gemini: Payment complete! Transaction Hash: {result.get('tx_hash')}")
    else:
        print(
            "🤖 Gemini: I can help you buy things on Arc with USDC. Try asking me to buy a coffee."
        )


if __name__ == "__main__":
    # Example prompts
    asyncio.run(run_agent_loop("Can you please pay 5 USDC for my coffee?"))
