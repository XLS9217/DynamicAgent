from .agent_operator_base import AgentOperator, agent_tool, description, flow
from ..service_handler import ServiceHandler


class RagOperator(AgentOperator):
    """Operator for retrieving and expanding knowledge from a configured bucket."""

    def __init__(self, bucket_name: str, top_k: int = 10):
        self.bucket_name = bucket_name
        self.top_k = top_k
        super().__init__()

    @description
    def get_description(self):
        return (
            "Retrieve relevant knowledge from the configured knowledge bucket and "
            "expand hidden knowledge node IDs when more detail is needed."
        )

    @flow
    def get_flow(self):
        return (
            "1. Use retrieve when the user asks a question that may need knowledge from the bucket.\n"
            "2. If retrieved fields contain <node_id>...</node_id>, collect all needed IDs and use expand_node_ids once before answering.\n"
            "3. Answer from retrieved or expanded knowledge instead of guessing."
        )

    @agent_tool(description="Retrieve relevant knowledge for the user's query from the configured bucket.")
    async def retrieve(self, query: str):
        """
        Retrieve relevant knowledge.

        :param query: The user's question or search query.
        """
        response = await ServiceHandler.retrieve(
            query=query,
            bucket_name=self.bucket_name,
            top_k=self.top_k,
        )
        return response.get("results", response)

    @agent_tool(description="Expand multiple knowledge node IDs from <node_id>...</node_id> placeholders.")
    async def expand_node_ids(self, node_ids: list[str]):
        """
        Expand knowledge node IDs into their stored values.

        :param node_ids: The knowledge node IDs to expand.
        """
        response = await ServiceHandler.expand_node_ids(
            bucket_name=self.bucket_name,
            node_ids=node_ids,
        )
        return response.get("results", response)
