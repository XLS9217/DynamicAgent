"""
Smoke test one registered operator with a random linear algebra task.

The script builds a random integer matrix/vector case, computes the expected
matrix-vector product locally, asks the agent to use the operator, verifies the
operator method executed with the same result, then deletes the test session.
"""
import asyncio
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient, AgentOperator, agent_tool, description, flow
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.session_accessor import SessionAccessor

load_dotenv()


SESSION_ID = "smoke-one-operator"


class LinearAlgebraOperator(AgentOperator):

    def __init__(self):
        self.probe_calls = []
        super().__init__()

    @description
    def linear_algebra_description(self) -> str:
        return "A linear algebra operator for matrix and vector calculations."

    @flow
    def matrix_vector_flow(self) -> str:
        return "Use matrix_vector_product when asked to multiply a matrix by a vector."

    @agent_tool(description="Multiply a matrix by a vector")
    def matrix_vector_product(self, matrix: list[list[int]], vector: list[int]) -> list[int]:
        """
        :param matrix: The integer matrix, represented as a list of rows
        :param vector: The integer vector
        """
        result = [sum(row[i] * vector[i] for i in range(len(vector))) for row in matrix]
        self.probe_calls.append({
            "tool": "matrix_vector_product",
            "matrix": matrix,
            "vector": vector,
            "result": result,
        })
        return result


def build_case() -> tuple[list[list[int]], list[int], list[int]]:
    rng = random.Random()
    matrix = [[rng.randint(-9, 9) for _ in range(3)] for _ in range(3)]
    vector = [rng.randint(-9, 9) for _ in range(3)]
    expected = [sum(row[i] * vector[i] for i in range(len(vector))) for row in matrix]
    return matrix, vector, expected


async def main():
    await PgInstance.initialize()
    await RedisInstance.initialize()

    client = None
    tool_calls = []

    try:
        await SessionAccessor.delete_session(SESSION_ID)

        matrix, vector, expected = build_case()
        print(f"matrix: {matrix}")
        print(f"vector: {vector}")
        print(f"expected: {expected}")

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        client = await DynamicAgentClient.create(
            setting=(
                "You are a concise assistant. Use available tools for linear algebra. "
                "Do not calculate matrix operations mentally."
            ),
            session_id=SESSION_ID,
        )
        assert client.session_id == SESSION_ID
        assert client.messages == [], "fresh smoke session should start empty"

        client.on_tool_call(lambda tool_name, arguments: tool_calls.append((tool_name, arguments)))

        operator = LinearAlgebraOperator()
        result = await client.add_operator(operator)
        print(f"operator registered: {result}")

        response = await client.trigger(
            f"Use the linear algebra tool to multiply matrix {matrix} by vector {vector}. "
            "Reply with only the resulting vector."
        )
        print(f"response: {response}")

        assert tool_calls, "expected the linear algebra tool to be called"
        assert tool_calls[0][0] == "LinearAlgebraOperator_matrix_vector_product"
        assert operator.probe_calls, "expected LinearAlgebraOperator.matrix_vector_product to execute"
        assert operator.probe_calls[0]["result"] == expected
        for value in expected:
            assert str(value) in response, f"expected response to include {value}"

        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()

        await SessionAccessor.delete_session(SESSION_ID)
        await PgInstance.close()
        await RedisInstance.close()
        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
