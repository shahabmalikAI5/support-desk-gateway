import os

from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=os.environ["DATABASE_URL"],
            min_size=1,
            max_size=4,
            open=True,
        )
        await _pool.open()
        await _pool.wait()
    return _pool
