from abc import ABC, abstractmethod


class DataAccessor(ABC):
    """
    Abstract base class for all database accessors.

    All accessors must implement _ensure_tables_exist() method
    to create their required database tables/collections.
    """

    @classmethod
    @abstractmethod
    async def ensure_tables_exist(cls) -> bool:
        """
        Create required database tables/collections if they don't exist.

        :return: True if successful, False otherwise
        """
        raise NotImplementedError