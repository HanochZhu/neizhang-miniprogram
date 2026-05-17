from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.config import settings


engine = create_async_engine(
    settings.database_url,
    echo=False,
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode for SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def stream_with_db(stream_factory):
    """Wrap an async SSE generator so DB writes commit after the stream finishes.

    StreamingResponse must not use Depends(get_db): the session is torn down
    before the generator runs, so flush() without commit loses all data.
    """
    import json
    import logging
    _logger = logging.getLogger(__name__)

    async with async_session_factory() as session:
        try:
            async for chunk in stream_factory(session):
                yield chunk
            await session.commit()
        except Exception as exc:
            await session.rollback()
            _logger.exception("stream_with_db error: %s", exc)
            # Yield an error frame and a stop frame so the client gets a
            # proper end-of-stream signal instead of ERR_INCOMPLETE_CHUNKED_ENCODING.
            yield f"data: {json.dumps({'type': 'error', 'content': '服务器内部错误，请重试'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'message_stop'}, ensure_ascii=False)}\n\n"
