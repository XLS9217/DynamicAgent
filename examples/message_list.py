import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from dynamic_agent_client.src.client import DynamicAgentClient

messages = [
    {"role": "user", "content": "Hey, have you seen the SSD prices lately? They seem to be going up."},
    {"role": "assistant", "content": "Yeah, SSD prices have been climbing over the past few months. NAND flash supply has tightened."},
    {"role": "user", "content": "What's causing the supply shortage?"},
    {"role": "assistant", "content": "Several NAND manufacturers cut production last year to reduce losses. Now demand is recovering but supply hasn't caught up."},
    {"role": "user", "content": "So it's basically a supply-demand imbalance?"},
    {"role": "assistant", "content": "Exactly. Reduced wafer starts plus growing demand from AI servers and data centers are pushing prices up."},
    {"role": "user", "content": "How much have prices increased so far?"},
    {"role": "assistant", "content": "Depending on the model, consumer SSDs have gone up roughly 10-20% in the last quarter alone."},
    {"role": "user", "content": "Do you think it will keep going up?"},
    {"role": "assistant", "content": "Analysts expect another 5-15% increase next quarter. Manufacturers are ramping production but it takes time."},
    {"role": "user", "content": "Should I buy an SSD now before it gets worse?"},
    {"role": "assistant", "content": "If you need one soon, buying now is reasonable. Prices likely won't drop back to last year's lows anytime soon."},
    {"role": "user", "content": "What capacity would you recommend for a general use PC?"},
    {"role": "assistant", "content": "1TB is the sweet spot for most people. Enough for OS, apps, and games without breaking the bank."},
    {"role": "user", "content": "Any brand recommendations?"},
    {"role": "assistant", "content": "Samsung 990 EVO, WD Black SN770, and Crucial P3 Plus are all solid choices with good price-to-performance."},
    {"role": "user", "content": "Thanks, that's really helpful. I'll grab one this week."},
    {"role": "assistant", "content": "Good call. Keep an eye on deal sites too, flash sales still pop up occasionally."},
]


async def main():
    port = os.getenv("PORT", "7777")

    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    client = await DynamicAgentClient.create(
        setting="You are a knowledgeable hardware advisor.",
        messages=messages,
    )
    print(f"Session created: {client.session_id}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    response = await client.trigger(
        "Given our conversation, summarize the key takeaways about the SSD price situation in 3 bullet points.",
        on_stream=on_stream,
    )
    print()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())