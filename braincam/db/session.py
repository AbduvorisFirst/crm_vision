from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from braincam.config import settings
from braincam.db.models import Base

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Create sessionmaker
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def init_db():
    """Initializes tables in database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    """Dependency for obtaining async db session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
