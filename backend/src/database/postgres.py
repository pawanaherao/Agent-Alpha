import asyncpg
from typing import Optional
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

class PostgresClient:
    """
    AsyncPG wrapper for PostgreSQL interactions.
    Handles connection pooling and transaction management.
    """
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initialize the connection pool."""
        try:
            self.pool = await asyncpg.create_pool(
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                database=settings.POSTGRES_DB,
                host=settings.POSTGRES_HOST,
                min_size=5,
                max_size=20
            )
            logger.info("Connected to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self):
        """Close the connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected from PostgreSQL")

    async def fetch(self, query: str, *args):
        """Fetch multiple rows."""
        if not self.pool:
            logger.warning(f"MOCK DB: Fetching {query[:20]}...")
            return []
        async with self.pool.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        """Fetch a single row."""
        if not self.pool:
            logger.warning(f"MOCK DB: Fetching Row {query[:20]}...")
            return None
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def execute(self, query: str, *args):
        """Execute a command."""
        if not self.pool:
            logger.warning(f"MOCK DB: Executing {query[:20]}...")
            return "MOCK_SUCCESS"
        async with self.pool.acquire() as connection:
            return await connection.execute(query, *args)

db = PostgresClient()
