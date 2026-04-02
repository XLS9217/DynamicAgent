"""
Knowledge retrieval workflow for searching and reconstructing knowledge from the bucket.

Flow:
1. Decide similarity focus (embedding vs BM25) based on query
2. Embed the user query
3. Search Milvus for similar knowledge nodes (scoped to bucket) with weighted scoring
4. Group results by instance_id and merge into partial blueprints
"""
from workflow.workflow_base import WorkflowBase
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.knowledge.knowledge_node_accessor import KnowledgeNodeAccessor
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor

DECIDE_PROMPT = """Analyze this search query and decide which similarity method should be prioritized:

Query: {query}

Options:
- "embedding" - Use when the query is semantic, conceptual, or about meaning (e.g., "products for meetings", "collaboration tools")
- "bm25" - Use when the query is keyword-based, specific terms, or exact matches (e.g., "AirLink", "PIN code feature")
- "neutral" - Use when both semantic and keyword matching are equally important

Respond with ONLY one word: embedding, bm25, or neutral"""


class KnowledgeRetrieveWorkflow(WorkflowBase):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.bucket_name = ""
        self.top_k = 10
        self.knowledge_accessor = None
        self._embedding_weight = 0.5
        self._bm25_weight = 0.5

    async def build(self, query: str, bucket_name: str, top_k: int = 10, knowledge_accessor=None):
        self.query = query
        self.bucket_name = bucket_name
        self.top_k = top_k
        self.knowledge_accessor = knowledge_accessor
        return self

    async def _decide_similarity_focus(self):
        """
        Use LLM to decide whether to lean on embedding or BM25 similarity.

        Sets weights:
        - embedding: 0.75 embedding, 0.25 BM25
        - bm25: 0.25 embedding, 0.75 BM25
        - neutral: 0.5 embedding, 0.5 BM25 (default on failure)
        """
        self.append_log(f"Deciding similarity focus for query: {self.query}")

        prompt = DECIDE_PROMPT.format(query=self.query)
        try:
            response = await self.invoke_agent([{"role": "user", "content": prompt}])
            decision = response.strip().lower()

            if decision == "embedding":
                self._embedding_weight = 0.75
                self._bm25_weight = 0.25
                self.append_log(f"Decision: embedding (weights: ebd=0.75, bm25=0.25)")
            elif decision == "bm25":
                self._embedding_weight = 0.25
                self._bm25_weight = 0.75
                self.append_log(f"Decision: bm25 (weights: ebd=0.25, bm25=0.75)")
            else:
                # neutral or any other response
                self._embedding_weight = 0.5
                self._bm25_weight = 0.5
                self.append_log(f"Decision: neutral (weights: ebd=0.5, bm25=0.5)")
        except Exception as e:
            # On failure, default to neutral
            self._embedding_weight = 0.5
            self._bm25_weight = 0.5
            self.append_log(f"Decision failed, defaulting to neutral: {str(e)}")

    async def _retrieve(self) -> list[dict]:
        """
        Retrieve top_k similar knowledge nodes from Milvus using hybrid search.

        Returns:
            List of search results: [{"id": row_id, "instance_id": uuid, "value": text, "distance": float}, ...]
        """
        self.append_log(f"Embedding query: {self.query}")
        embeddings = await KnowledgeEngine.get_embeddings([self.query])
        query_embedding = embeddings[0]

        self.append_log(
            f"Searching Milvus for top {self.top_k} nodes in bucket {self.bucket_name} "
            f"(weights: ebd={self._embedding_weight}, bm25={self._bm25_weight})"
        )
        search_results = KnowledgeNodeAccessor.search(
            bucket_name=self.bucket_name,
            query_embedding=query_embedding,
            query_text=self.query,
            top_k=self.top_k,
            embedding_weight=self._embedding_weight,
            bm25_weight=self._bm25_weight,
        )

        self.append_log(f"Found {len(search_results)} results")
        return search_results

    async def _merge_bp_instance(self, search_results: list[dict]) -> list[dict]:
        """
        Merge search results into partial blueprint instances.

        For each instance:
        - Matched attributes have actual values
        - Unmatched attributes show: "This attribute is about {description}, knowledge node id <node_id>{uuid}</node_id>"
        - Identifier is always fetched with actual value

        Returns:
            List of instances (just filled_attributes dicts)
        """
        self.append_log("Grouping results by instance_id")

        # Group by instance_id
        instance_groups = {}
        for r in search_results:
            iid = r["instance_id"]
            if iid not in instance_groups:
                instance_groups[iid] = {"nodes": [], "total_distance": 0.0}
            instance_groups[iid]["nodes"].append(r)
            instance_groups[iid]["total_distance"] += r.get("distance", 0.0)

        # Calculate average distance per instance
        for iid, group in instance_groups.items():
            group["avg_distance"] = group["total_distance"] / len(group["nodes"])

        self.append_log(f"Found {len(instance_groups)} unique instances")

        # Reconstruct partial blueprints
        self.append_log("Reconstructing partial blueprints")
        reconstructed = []

        # Get all instances data once for efficiency
        all_instances_data = await self.knowledge_accessor.get_all_instances(self.bucket_name)

        for iid, group in instance_groups.items():
            # Get blueprint_instance rows for this instance
            instances = await self.knowledge_accessor.get_instances_by_instance_id(iid)
            if not instances:
                continue

            # Find blueprint_id from all_instances_data
            blueprint_id = None
            for inst_data in all_instances_data:
                if inst_data["instance_id"] == iid:
                    blueprint_id = inst_data["blueprint_id"]
                    break

            if not blueprint_id:
                continue

            # Get blueprint schema
            blueprint = await self.knowledge_accessor.get_blueprint(blueprint_id)
            if not blueprint:
                continue

            attributes = await self.knowledge_accessor.get_attributes(blueprint_id)

            # Map row_ids to attribute names and get descriptions
            row_id_to_attr = {}
            attr_name_to_desc = {}
            for inst in instances:
                for attr in attributes:
                    if inst.attribute_id == attr.id:
                        row_id_to_attr[inst.id] = attr.name
                        attr_name_to_desc[attr.name] = attr.description
                        break

            # Build filled_attributes
            filled_attributes = {}

            # Initialize all attributes with description + node_id
            for inst in instances:
                attr_name = row_id_to_attr.get(inst.id)
                if attr_name:
                    description = attr_name_to_desc.get(attr_name, "")
                    filled_attributes[attr_name] = f"This attribute is about {description}, knowledge node id <node_id>{inst.id}</node_id>"

            # Fill in values from search results
            for node in group["nodes"]:
                attr_name = row_id_to_attr.get(node["id"])
                if attr_name:
                    filled_attributes[attr_name] = node["value"]

            # Ensure identifier is always fetched
            identifier_name = next((k for k, v in blueprint.attributes.items() if v.is_identifier), None)
            if identifier_name and filled_attributes.get(identifier_name, "").startswith("This attribute"):
                for inst in instances:
                    attr_name = row_id_to_attr.get(inst.id)
                    if attr_name == identifier_name:
                        entities = KnowledgeNodeAccessor.get_by_ids(self.bucket_name, [inst.id])
                        if entities:
                            filled_attributes[identifier_name] = entities[0]["value"]
                        break

            # Log metadata
            self.append_log(
                f"Reconstructed instance: {blueprint.name} (id={iid}, blueprint_id={blueprint_id}, "
                f"avg_distance={group['avg_distance']:.4f}, match_count={len(group['nodes'])})"
            )

            reconstructed.append(filled_attributes)

        self.append_log(f"Reconstructed {len(reconstructed)} instances")
        return reconstructed

    async def execute(self) -> list[dict]:
        """
        Execute retrieval workflow.

        Returns:
            List of instances with filled_attributes
        """
        self.append_log("Knowledge retrieval started")

        # Step 1: Decide similarity focus
        await self._decide_similarity_focus()

        # Step 2: Retrieve with weighted scoring
        search_results = await self._retrieve()

        # Step 3: Merge into partial blueprints
        reconstructed = await self._merge_bp_instance(search_results)

        self.append_log("Knowledge retrieval completed")
        return reconstructed