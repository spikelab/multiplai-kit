# FastAPI Best Practices for AI Applications

Building production-ready FastAPI backends, with patterns specific to AI workloads.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Application Setup](#2-application-setup)
3. [Routing & Endpoints](#3-routing--endpoints)
4. [Pydantic Schemas](#4-pydantic-schemas)
5. [Dependency Injection](#5-dependency-injection)
6. [Async Patterns](#6-async-patterns)
7. [Error Handling](#7-error-handling)
8. [Background Tasks](#8-background-tasks)
9. [Streaming Responses](#9-streaming-responses)
10. [Testing](#10-testing)
11. [Anti-Patterns](#11-anti-patterns)

---

## 1. Project Structure

### Domain-Based Structure (Recommended)

```
src/
├── myapp/
│   ├── __init__.py
│   ├── main.py               # FastAPI app, lifespan
│   ├── config.py             # Pydantic settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py         # Router includes
│   │   └── deps.py           # Shared dependencies
│   ├── features/
│   │   ├── chat/
│   │   │   ├── __init__.py
│   │   │   ├── router.py     # Endpoints
│   │   │   ├── schemas.py    # Pydantic models
│   │   │   ├── service.py    # Business logic
│   │   │   └── exceptions.py # Custom exceptions
│   │   ├── embeddings/
│   │   │   └── ...
│   │   └── documents/
│   │       └── ...
│   └── shared/
│       ├── __init__.py
│       ├── exceptions.py     # Base exceptions
│       ├── middleware.py     # Logging, etc.
│       └── clients.py        # LLM clients
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
└── pyproject.toml
```

### Key Principles

1. **Separate concerns**: Router → Service → Client/DB
2. **One router per domain**: Group related endpoints
3. **Explicit imports**: Full paths, avoid `*` imports

```python
# Good
from src.myapp.features.chat import service as chat_service

# Avoid
from src.myapp.features.chat.service import *
```

---

## 2. Application Setup

### Main Application

```python
# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from myapp.config import get_settings
from myapp.api.routes import api_router
from myapp.shared.middleware import LoggingMiddleware
from myapp.shared.clients import init_clients, cleanup_clients


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    settings = get_settings()
    await init_clients(settings)
    yield
    # Shutdown
    await cleanup_clients()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware
    app.add_middleware(LoggingMiddleware)

    # Routes
    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
```

### Health Checks

```python
# api/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from myapp.api.deps import get_db

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness(db: Session = Depends(get_db)):
    """Check all dependencies are ready."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(e)},
        )
```

---

## 3. Routing & Endpoints

### Router Setup

```python
# features/chat/router.py
from fastapi import APIRouter, Depends, status

from myapp.features.chat import schemas, service
from myapp.api.deps import get_current_user

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


@router.post(
    "/completions",
    response_model=schemas.ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def create_completion(
    request: schemas.ChatRequest,
):
    return await service.create_completion(request)


@router.post("/completions/stream")
async def create_completion_stream(
    request: schemas.ChatRequest,
):
    return StreamingResponse(
        service.stream_completion(request),
        media_type="text/event-stream",
    )
```

### Include Routers

```python
# api/routes.py
from fastapi import APIRouter

from myapp.features.chat.router import router as chat_router
from myapp.features.embeddings.router import router as embeddings_router
from myapp.features.documents.router import router as documents_router

api_router = APIRouter()

api_router.include_router(chat_router)
api_router.include_router(embeddings_router)
api_router.include_router(documents_router)
```

### Path vs Query Parameters

```python
from typing import Annotated
from fastapi import Path, Query


@router.get("/documents/{document_id}")
async def get_document(
    # Path: resource identification
    document_id: Annotated[str, Path(description="Document ID")],
    # Query: filtering/options
    include_chunks: Annotated[bool, Query()] = False,
    format: Annotated[str | None, Query()] = None,
):
    ...
```

---

## 4. Pydantic Schemas

### Request/Response Pattern

```python
# features/chat/schemas.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str = Field(default="claude-sonnet-4-20250514")
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 256,
                }
            ]
        }
    )


class ChatResponse(BaseModel):
    id: str
    content: str
    model: str
    usage: dict[str, int]

    model_config = ConfigDict(from_attributes=True)


class ChatStreamChunk(BaseModel):
    content: str
    done: bool = False
```

### Validation

```python
from pydantic import BaseModel, Field, field_validator, model_validator


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=100)
    model: str = "text-embedding-3-small"

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, v: list[str]) -> list[str]:
        for i, text in enumerate(v):
            if not text.strip():
                raise ValueError(f"Text at index {i} is empty")
            if len(text) > 8000:
                raise ValueError(f"Text at index {i} exceeds 8000 chars")
        return v


class DateRangeRequest(BaseModel):
    start_date: str
    end_date: str

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")
        return self
```

### Separate Create/Update Schemas

```python
class DocumentBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str


class DocumentCreate(DocumentBase):
    """Create request - all required fields."""
    pass


class DocumentUpdate(BaseModel):
    """Update request - all optional."""
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = None


class DocumentResponse(DocumentBase):
    """Response - includes DB fields."""
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

---

## 5. Dependency Injection

### Database Session

```python
# api/deps.py
from collections.abc import Generator
from sqlalchemy.orm import Session

from myapp.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### LLM Client

```python
# api/deps.py
from functools import lru_cache
from anthropic import AsyncAnthropic

from myapp.config import get_settings


@lru_cache
def get_anthropic_client() -> AsyncAnthropic:
    settings = get_settings()
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        max_retries=settings.max_retries,
        timeout=settings.timeout,
    )
```

### Validation Dependencies

```python
# api/deps.py
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from myapp.features.documents.models import Document


async def valid_document_id(
    document_id: str,
    db: Session = Depends(get_db),
) -> Document:
    """Validate document exists and return it."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )
    return document


# Usage in router
@router.get("/documents/{document_id}")
async def get_document(
    document: Document = Depends(valid_document_id),
):
    return document  # Already validated and fetched
```

### Chained Dependencies

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # Decode token, fetch user
    ...


async def get_active_user(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


@router.get("/me")
async def get_me(user: User = Depends(get_active_user)):
    return user
```

---

## 6. Async Patterns

### When to Use Async

| Operation | Async? | Reason |
|-----------|--------|--------|
| LLM API calls | Yes | Network I/O |
| Database queries | Either | FastAPI handles both |
| File I/O | Either | `def` runs in threadpool |
| CPU-bound work | No | Use background task/worker |

### Async Endpoints

```python
# Good: Async for I/O
@router.post("/chat")
async def chat(request: ChatRequest):
    response = await client.messages.create(...)
    return response


# Good: Sync for blocking I/O (runs in threadpool)
@router.get("/files/{path}")
def read_file(path: str):
    with open(path) as f:
        return f.read()


# BAD: Blocking in async
@router.post("/bad")
async def bad_endpoint():
    time.sleep(5)  # Blocks event loop!
    return {"status": "done"}
```

### Running Sync Code from Async

```python
import asyncio


@router.post("/process")
async def process_document(doc_id: str):
    # Run CPU-bound work in thread
    result = await asyncio.to_thread(
        expensive_sync_function,
        doc_id,
    )
    return result
```

---

## 7. Error Handling

### Custom Exceptions

```python
# shared/exceptions.py
from fastapi import HTTPException, status


class AppException(Exception):
    def __init__(self, status_code: int, detail: str, error_code: str):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code


class DocumentNotFoundError(AppException):
    def __init__(self, document_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
            error_code="DOCUMENT_NOT_FOUND",
        )


class RateLimitExceededError(AppException):
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry after {retry_after}s",
            error_code="RATE_LIMIT_EXCEEDED",
        )
```

### Exception Handlers

```python
# main.py
from fastapi import Request
from fastapi.responses import JSONResponse

from myapp.shared.exceptions import AppException


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "detail": exc.detail,
            "path": str(request.url),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "detail": exc.errors(),
        },
    )
```

### Error Response Format

```json
{
    "error": "DOCUMENT_NOT_FOUND",
    "detail": "Document abc123 not found",
    "path": "/api/documents/abc123"
}
```

---

## 8. Background Tasks

### Simple Background Tasks

```python
from fastapi import BackgroundTasks


def log_request(request_id: str, duration: float):
    """Background task to log request metrics."""
    # Write to file, send to metrics service, etc.
    pass


@router.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
):
    start = time.time()
    response = await service.create_completion(request)
    duration = time.time() - start

    # Log in background (doesn't block response)
    background_tasks.add_task(log_request, response.id, duration)

    return response
```

### Long-Running Tasks

For tasks > few seconds, use a proper task queue:

```python
# With Celery or similar
from myapp.tasks import process_document_task


@router.post("/documents/{doc_id}/process")
async def process_document(doc_id: str):
    # Enqueue task
    task = process_document_task.delay(doc_id)
    return {"task_id": task.id, "status": "queued"}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = process_document_task.AsyncResult(task_id)
    return {"task_id": task_id, "status": task.status}
```

---

## 9. Streaming Responses

### Server-Sent Events for LLM

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse


async def stream_completion(request: ChatRequest):
    """Stream LLM response as SSE."""
    async with client.messages.stream(
        model=request.model,
        max_tokens=request.max_tokens,
        messages=[m.model_dump() for m in request.messages],
    ) as stream:
        async for text in stream.text_stream:
            yield f"data: {json.dumps({'content': text})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        stream_completion(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
```

### File Streaming

```python
from fastapi.responses import StreamingResponse


async def file_iterator(file_path: str, chunk_size: int = 8192):
    async with aiofiles.open(file_path, "rb") as f:
        while chunk := await f.read(chunk_size):
            yield chunk


@router.get("/files/{file_id}/download")
async def download_file(file_id: str):
    file_path = get_file_path(file_id)
    return StreamingResponse(
        file_iterator(file_path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={file_id}"},
    )
```

---

## 10. Testing

### Test Setup

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from myapp.main import app
from myapp.database import Base, get_db


@pytest.fixture
def db_session():
    """Fresh database for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    """Test client with overridden DB."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
```

### Integration Tests

```python
# tests/integration/test_chat.py
import pytest


class TestChatEndpoints:
    def test_create_completion(self, client):
        response = client.post(
            "/api/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "usage" in data

    def test_invalid_request(self, client):
        response = client.post(
            "/api/chat/completions",
            json={"messages": []},  # Empty messages
        )
        assert response.status_code == 422
```

### Mocking LLM Calls

```python
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_anthropic():
    with patch("myapp.features.chat.service.client") as mock:
        mock.messages.create = AsyncMock(
            return_value=MockResponse(
                content=[MockContent(text="Mocked response")],
                usage={"input_tokens": 10, "output_tokens": 20},
            )
        )
        yield mock


def test_chat_with_mock(client, mock_anthropic):
    response = client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Mocked response"
```

---

## 11. Anti-Patterns

### Critical Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Blocking in async | Halts event loop | Use `asyncio.to_thread()` |
| No response schema | Exposes internals | Always use `response_model` |
| God router | Unmaintainable | Split by domain |
| Hardcoded config | Inflexible | Use Pydantic settings |
| No validation | Security/bugs | Use Pydantic everywhere |

### Code Examples

```python
# BAD: Blocking in async
@router.post("/bad")
async def bad():
    time.sleep(5)  # Blocks!
    result = sync_db_call()  # Blocks!
    return result

# GOOD: Proper async
@router.post("/good")
async def good():
    await asyncio.sleep(5)
    result = await asyncio.to_thread(sync_db_call)
    return result


# BAD: No response model
@router.get("/users/{id}")
async def get_user(id: str, db: Session = Depends(get_db)):
    return db.query(User).get(id)  # Exposes ORM object

# GOOD: With response model
@router.get("/users/{id}", response_model=UserResponse)
async def get_user(id: str, db: Session = Depends(get_db)):
    return db.query(User).get(id)  # Serialized via Pydantic


# BAD: Everything in one file
# api.py with 50 endpoints

# GOOD: Domain-based split
# features/users/router.py
# features/documents/router.py
# features/chat/router.py
```

---

## Quick Reference

```python
# Create app
app = FastAPI(lifespan=lifespan)

# Add router
app.include_router(router, prefix="/api")

# Dependency
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoint
@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(
    item: ItemCreate,
    db: Session = Depends(get_db),
):
    return service.create(db, item)

# Streaming
return StreamingResponse(generator(), media_type="text/event-stream")

# Background task
background_tasks.add_task(func, arg1, arg2)
```

---

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [FastAPI Best Practices (GitHub)](https://github.com/zhanymkanov/fastapi-best-practices)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Starlette (ASGI)](https://www.starlette.io/)
