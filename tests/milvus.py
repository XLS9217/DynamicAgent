from pymilvus import MilvusClient


def test_milvus_lite():
    # Connect to Milvus Docker instance
    uri = "http://localhost:19530"

    print(f"--- Testing Milvus with Docker instance: {uri} ---")

    client = MilvusClient(uri=uri)

    # List collections
    collections = client.list_collections()
    print(f"Existing Collections: {collections}")

    # Create a test collection if it doesn't exist
    if "test_collection" not in collections:
        client.create_collection(
            collection_name="test_collection",
            dimension=128
        )
        print("Created test_collection")

    print("Success: Milvus Lite is working!")
    client.close()


if __name__ == "__main__":
    test_milvus_lite()