from abc import ABC, abstractmethod


class DataAccessor(ABC):
    """
    Abstract base class for all database accessors.

    All accessors must implement ensure_tables_exist() to create their
    required database tables/collections.
    """

    @classmethod
    @abstractmethod
    async def ensure_tables_exist(cls) -> bool:
        """
        Create required database tables/collections if they don't exist.

        :return: True if successful, False otherwise
        """
        raise NotImplementedError

    @classmethod
    async def ensure_all_tables_exist(cls) -> None:
        """Run ensure_tables_exist() for every registered DataAccessor subclass."""
        for subclass in cls.__subclasses__():
            await subclass.ensure_tables_exist()