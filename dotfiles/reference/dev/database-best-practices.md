# Database Best Practices

Patterns for database selection, SQLAlchemy, migrations, and connection management in Python applications.

---

## Database Selection

### SQLite

**Best for:** Local development, POC/MVP, single-user apps, embedded applications, testing.

```python
# Simple and zero-config
DATABASE_URL = "sqlite:///./data.db"

# In-memory for tests
DATABASE_URL = "sqlite:///:memory:"
```

**Strengths:**
- Zero ops, file-based, no server
- Good enough for surprising amounts of traffic (read-heavy)
- Perfect for prototyping
- Excellent for tests (fast, isolated)

**Limitations:**
- Single writer at a time (write contention)
- No concurrent connections for writes
- Limited data types
- No built-in user management

### PostgreSQL

**Best for:** Production applications, multi-user systems, complex queries, data integrity matters.

```python
# Standard connection
DATABASE_URL = "postgresql://user:pass@localhost:5432/dbname"

# Async with asyncpg
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/dbname"
```

**Strengths:**
- ACID compliance, excellent data integrity
- Rich data types (JSONB, arrays, full-text search)
- Concurrent connections, connection pooling
- Mature ecosystem, excellent tooling

**When to migrate from SQLite:**
- Multiple users writing concurrently
- Need for complex queries, joins, or full-text search
- Data integrity is critical
- Need horizontal scaling or replication

---

## SQLAlchemy Patterns

SQLAlchemy is the de facto standard for Python database access. Use SQLAlchemy 2.0 style.

### Engine and Session Setup

```python
# src/myapp/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

class Base(DeclarativeBase):
    """Base class for all models."""
    pass

# Sync engine
engine = create_engine(
    settings.database_url,
    echo=settings.debug,  # Log SQL in development
    pool_pre_ping=True,   # Verify connections before use
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

def get_db():
    """Dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Async Setup (Recommended for FastAPI)

```python
# src/myapp/database.py
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# Use asyncpg for PostgreSQL
engine = create_async_engine(
    settings.database_url,  # postgresql+asyncpg://...
    echo=settings.debug,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency for FastAPI."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Model Definition (2.0 Style)

```python
# src/myapp/models/user.py
from datetime import datetime
from typing import Optional
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from myapp.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    posts: Mapped[list["Post"]] = relationship(back_populates="author")

    def __repr__(self) -> str:
        return f"<User {self.email}>"
```

### Query Patterns (2.0 Style)

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

# Get by ID
async def get_user(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# Get by field
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

# List with pagination
async def list_users(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    result = await db.execute(
        select(User)
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    return list(result.scalars().all())

# Create
async def create_user(db: AsyncSession, user_data: UserCreate) -> User:
    user = User(**user_data.model_dump())
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# Update
async def update_user(
    db: AsyncSession,
    user: User,
    updates: UserUpdate,
) -> User:
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user

# Delete
async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()
```

---

## Repository Pattern

For larger applications, encapsulate database access in repository classes.

```python
# src/myapp/repositories/base.py
from typing import Generic, TypeVar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.database import Base

ModelT = TypeVar("ModelT", bound=Base)

class BaseRepository(Generic[ModelT]):
    """Base repository with common CRUD operations."""

    def __init__(self, db: AsyncSession, model: type[ModelT]):
        self.db = db
        self.model = model

    async def get(self, id: int) -> ModelT | None:
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ModelT]:
        result = await self.db.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.db.delete(obj)
        await self.db.commit()
```

```python
# src/myapp/repositories/user.py
from sqlalchemy import select

from myapp.models import User
from myapp.repositories.base import BaseRepository

class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, User)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_active_users(self) -> list[User]:
        result = await self.db.execute(
            select(User).where(User.is_active == True)
        )
        return list(result.scalars().all())
```

```python
# Usage in FastAPI
@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    user = await repo.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

---

## Migrations with Alembic

Alembic handles schema migrations. Always use migrations, even for SQLite in development.

### Setup

```bash
# Install
uv add alembic

# Initialize
alembic init alembic
```

### Configure alembic.ini and env.py

```python
# alembic/env.py
from myapp.database import Base
from myapp.models import *  # Import all models
from myapp.config import settings

# Set the database URL
config.set_main_option("sqlalchemy.url", settings.database_url)

# Set target metadata for autogenerate
target_metadata = Base.metadata
```

### Migration Commands

```bash
# Create migration from model changes
alembic revision --autogenerate -m "Add users table"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history
```

### Migration Best Practices

```python
# alembic/versions/001_add_users_table.py
"""Add users table

Revision ID: 001
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

def downgrade() -> None:
    op.drop_index("ix_users_email")
    op.drop_table("users")
```

**Rules:**
1. Always write both `upgrade()` and `downgrade()`
2. Review autogenerated migrations before applying
3. Test migrations in development before production
4. Never edit migrations after they've been applied to production
5. Use descriptive migration messages

---

## Connection Pooling

### SQLAlchemy Pool Configuration

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    database_url,
    poolclass=QueuePool,
    pool_size=5,           # Maintained connections
    max_overflow=10,       # Additional connections when needed
    pool_timeout=30,       # Seconds to wait for connection
    pool_recycle=1800,     # Recycle connections after 30 min
    pool_pre_ping=True,    # Verify connection before use
)
```

### External Pooling (Production)

For high-traffic production, use PgBouncer or similar:

```python
# Connection to PgBouncer
DATABASE_URL = "postgresql://user:pass@localhost:6432/dbname"

# Disable SQLAlchemy pooling (PgBouncer handles it)
engine = create_engine(
    database_url,
    poolclass=NullPool,  # No SQLAlchemy pooling
)
```

---

## Testing with Databases

### SQLite In-Memory for Unit Tests

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from myapp.database import Base

@pytest.fixture
def db():
    """Fresh database for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
```

### Async Testing

```python
# tests/conftest.py
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from myapp.database import Base

@pytest_asyncio.fixture
async def db():
    """Async database session for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
```

### Integration Tests with Real Database

```python
# tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres():
    """Real PostgreSQL for integration tests."""
    with PostgresContainer("postgres:15") as pg:
        yield pg.get_connection_url()

@pytest.fixture
def db(postgres):
    """Session with real PostgreSQL."""
    engine = create_engine(postgres)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
```

---

## Common Patterns

### Soft Deletes

```python
from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

class User(Base, SoftDeleteMixin):
    __tablename__ = "users"
    # ... fields

# Query active only
select(User).where(User.deleted_at.is_(None))
```

### Timestamps Mixin

```python
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

### Optimistic Locking

```python
from sqlalchemy.orm import Mapped, mapped_column

class OptimisticLockMixin:
    version: Mapped[int] = mapped_column(default=1)

# Usage
async def update_with_lock(db: AsyncSession, user: User, updates: dict):
    current_version = user.version
    user.version += 1
    for k, v in updates.items():
        setattr(user, k, v)

    result = await db.execute(
        update(User)
        .where(User.id == user.id, User.version == current_version)
        .values(**updates, version=user.version)
    )
    if result.rowcount == 0:
        raise ConcurrentModificationError("Record was modified")
    await db.commit()
```

---

## SQLite to PostgreSQL Migration

When graduating from SQLite to PostgreSQL:

### 1. Update Dependencies

```bash
uv add asyncpg  # For async PostgreSQL
# or
uv add psycopg2-binary  # For sync PostgreSQL
```

### 2. Update Database URL

```python
# config.py
class Settings(BaseSettings):
    database_url: str = "sqlite:///./data.db"  # Default for dev

# .env.production
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

### 3. Handle SQLite-Specific Code

```python
# Things that work differently:

# Boolean handling (SQLite stores as 0/1)
# PostgreSQL has native BOOLEAN

# JSON fields
# SQLite: use JSON type or store as TEXT
# PostgreSQL: use JSONB for indexing

# Auto-increment
# SQLite: INTEGER PRIMARY KEY
# PostgreSQL: SERIAL or IDENTITY

# String comparison
# SQLite: case-insensitive by default
# PostgreSQL: case-sensitive
```

### 4. Data Migration

```bash
# Export from SQLite
sqlite3 data.db .dump > backup.sql

# Or use a migration tool
uv add pgloader
pgloader sqlite:///data.db postgresql://user:pass@host/db
```

---

## Quick Reference

### Dependencies

```bash
# Core
uv add sqlalchemy

# Async support
uv add sqlalchemy[asyncio] aiosqlite  # SQLite async
uv add sqlalchemy[asyncio] asyncpg    # PostgreSQL async

# Migrations
uv add alembic

# Testing
uv add --dev pytest-asyncio testcontainers
```

### Common Imports

```python
from sqlalchemy import create_engine, select, update, delete
from sqlalchemy.orm import Session, sessionmaker, relationship, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
```
