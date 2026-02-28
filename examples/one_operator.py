import asyncio
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from dynamic_agent_client.src.client import DynamicAgentClient
from dynamic_agent_client.src.operator.agent_operator_base import AgentOperator, agent_tool, description, flow


class MathOperator(AgentOperator):

    @description
    def math_description(self) -> str:
        return "A math operator that performs vector operations."

    @flow
    def math_flow(self) -> str:
        return "1. Receive two vectors\n2. Compute the requested operation\n3. Return the result"

    @agent_tool(description="Compute dot product of two vectors")
    def dot_product(self, vector_a: list[float], vector_b: list[float]) -> float:
        """
        :param vector_a: The first vector
        :param vector_b: The second vector
        """
        print(f"dot_product Received vectors: {vector_a} and {vector_b}")
        if len(vector_a) != len(vector_b):
            raise ValueError("Vectors must be the same length for dot product")
        return sum(a * b for a, b in zip(vector_a, vector_b))

    @agent_tool(description="Compute cross product of two 3D vectors")
    def cross_product(self, vector_a: list[float], vector_b: list[float]) -> list[float]:
        """
        :param vector_a: The first 3D vector
        :param vector_b: The second 3D vector
        """
        print(f"cross_product Received vectors: {vector_a} and {vector_b}")
        if len(vector_a) != 3 or len(vector_b) != 3:
            raise ValueError("Cross product requires 3D vectors")
        a1, a2, a3 = vector_a
        b1, b2, b3 = vector_b
        return [
            a2 * b3 - a3 * b2,
            a3 * b1 - a1 * b3,
            a1 * b2 - a2 * b1,
        ]


async def main():
    port = os.getenv("PORT", "7777")

    # 1. Connect to the service and create a session
    client = await DynamicAgentClient.create(
        setting="You are a helpful math assistant.",
        server_addr=f"http://localhost:{port}",
    )
    print(f"Session created: {client.session_id}")

    # 2. Register the MathOperator
    op = MathOperator()
    result = await client.add_operator(op)
    print(f"Operator registered: {result}")

    # 3. Ask for a cross product
    response = await client.trigger("Calculate the cross product of [6.234, 22.61, 3.61234] and [4, 5, 6], then calculate the dot product of the result and [0.82, 0.2412, 0.111].")
    print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(main())
