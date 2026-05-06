"""
Interactive CLI for managing buckets: list and delete.
"""
import asyncio
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance


async def main():
    await PgInstance.initialize()
    MilvusInstance.initialize()

    while True:
        print("\n=== Bucket Management ===")
        buckets = await KnowledgeAccessor.get_bucket_list()

        if not buckets:
            print("No buckets found.")
            break

        print("\nAvailable buckets:")
        for idx, bucket in enumerate(buckets, 1):
            desc = f" - {bucket.description}" if bucket.description else ""
            print(f"{idx}. {bucket.name}{desc}")

        print("\n0. Exit")

        try:
            choice = input("\nSelect bucket number to delete (or 0 to exit): ").strip()
            if choice == "0":
                print("Exiting.")
                break

            idx = int(choice) - 1
            if idx < 0 or idx >= len(buckets):
                print("Invalid selection.")
                continue

            selected = buckets[idx]
            confirm = input(f"\nDelete bucket '{selected.name}'? This will remove all blueprints and knowledge. (yes/no): ").strip().lower()

            if confirm == "yes":
                print(f"Deleting bucket '{selected.name}'...")
                await KnowledgeAccessor.delete_bucket(selected.name)
                print(f"Bucket '{selected.name}' deleted successfully.")
            else:
                print("Deletion cancelled.")

        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Error: {e}")

    await PgInstance.close()
    MilvusInstance.close()


if __name__ == "__main__":
    asyncio.run(main())