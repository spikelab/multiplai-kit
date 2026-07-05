# Python Async Patterns for LLM APIs

Best practices for async programming with LLM APIs, including rate limiting, retries, streaming, and mixing sync/async code.

---

## Table of Contents

1. [Async Fundamentals](#1-async-fundamentals)
2. [LLM Client Setup](#2-llm-client-setup)
3. [Rate Limiting & Retries](#3-rate-limiting--retries)
4. [Streaming Responses](#4-streaming-responses)
5. [Concurrent API Calls](#5-concurrent-api-calls)
6. [Mixing Sync and Async](#6-mixing-sync-and-async)
7. [Error Handling](#7-error-handling)
8. [Production Patterns](#8-production-patterns)

---

## 1. Async Fundamentals

### When to Use Async

| Task Type | Use Async? | Reason |
|-----------|------------|--------|
| LLM API calls | Yes | Network I/O bound |
| Multiple concurrent requests | Yes | Parallelism without threads |
| Single blocking operation | Either | Async overhead may not help |
| CPU-intensive work | No | GIL blocks, use multiprocessing |
| File I/O | Either | Use `aiofiles` if async |

### The Golden Rule

**Never block the event loop.** If you must call blocking code from async, offload to a thread.

```python
# BAD: Blocks event loop
async def bad_example():
    time.sleep(5)  # Blocks everything!
    result = sync_db_query()  # Also blocks!

# GOOD: Non-blocking
async def good_example():
    await asyncio.sleep(5)  # Yields control
    result = await asyncio.to_thread(sync_db_query)  # Runs in thread
```

---

## 2. LLM Client Setup

### Anthropic Client

```python
import os
from anthropic import Anthropic, AsyncAnthropic

# Sync client
client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    max_retries=3,  # Built-in retry with exponential backoff
    timeout=120.0,  # Timeout in seconds
)

# Async client (for async code)
async_client = AsyncAnthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    max_retries=3,
    timeout=120.0,
)
```

### OpenAI Client

```python
from openai import OpenAI, AsyncOpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=3,
    timeout=60.0,
)

async_client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=3,
    timeout=60.0,
)
```

### Client as Dependency (FastAPI)

```python
from functools import lru_cache
from anthropic import AsyncAnthropic
from fastapi import Depends


@lru_cache
def get_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic()


async def generate_response(
    prompt: str,
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

---

## 3. Rate Limiting & Retries

### Built-in Retries (Recommended)

Both Anthropic and OpenAI SDKs have built-in retry with exponential backoff:

```python
# Configure at client level
client = AsyncAnthropic(max_retries=5)

# Or per-request
response = await client.with_options(max_retries=10).messages.create(...)
```

**Retried automatically:**
- Connection errors
- 408 Request Timeout
- 429 Rate Limit
- 5xx Server Errors

### Custom Retry with Tenacity

For more control, use the `tenacity` library:

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from anthropic import RateLimitError, APIConnectionError


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
)
async def call_llm_with_retry(prompt: str) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

### Rate Limiting with Semaphores

Limit concurrent requests to avoid hitting rate limits:

```python
import asyncio

# Limit to 10 concurrent requests
semaphore = asyncio.Semaphore(10)


async def rate_limited_call(prompt: str) -> str:
    async with semaphore:
        return await call_llm(prompt)


async def process_many(prompts: list[str]) -> list[str]:
    tasks = [rate_limited_call(p) for p in prompts]
    return await asyncio.gather(*tasks)
```

### Token Bucket Rate Limiter

For precise rate control:

```python
import asyncio
import time


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1):
        async with self._lock:
            now = time.monotonic()
            # Add tokens based on time passed
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return

            # Wait for tokens
            wait_time = (tokens - self.tokens) / self.rate
            await asyncio.sleep(wait_time)
            self.tokens = 0


# Usage: 10 requests per second, burst of 20
limiter = TokenBucket(rate=10, capacity=20)


async def rate_limited_call(prompt: str) -> str:
    await limiter.acquire()
    return await call_llm(prompt)
```

---

## 4. Streaming Responses

### Anthropic Streaming

```python
# High-level streaming (recommended)
async def stream_response(prompt: str) -> AsyncGenerator[str, None]:
    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


# Usage
async def main():
    async for chunk in stream_response("Tell me a story"):
        print(chunk, end="", flush=True)
```

### OpenAI Streaming

```python
async def stream_openai(prompt: str) -> AsyncGenerator[str, None]:
    stream = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

### FastAPI Streaming Response

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post("/chat/stream")
async def chat_stream(prompt: str):
    async def generate():
        async with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )
```

### Collecting Streamed Response

```python
async def stream_and_collect(prompt: str) -> tuple[str, list[str]]:
    """Stream response while collecting full text."""
    chunks = []

    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            chunks.append(text)
            yield text  # Stream to caller

    full_text = "".join(chunks)
    return full_text
```

---

## 5. Concurrent API Calls

### asyncio.gather for Multiple Calls

```python
async def process_batch(prompts: list[str]) -> list[str]:
    """Process multiple prompts concurrently."""
    tasks = [call_llm(p) for p in prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle results
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Failed prompt {i}: {result}")
            processed.append(None)
        else:
            processed.append(result)

    return processed
```

### Batched Processing with Rate Limiting

```python
async def process_with_batches(
    items: list[str],
    batch_size: int = 10,
    delay_between_batches: float = 1.0,
) -> list[str]:
    """Process items in batches with delays."""
    results = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        logger.info(f"Processing batch {i // batch_size + 1}")

        batch_results = await asyncio.gather(
            *[call_llm(item) for item in batch],
            return_exceptions=True,
        )
        results.extend(batch_results)

        # Delay before next batch (except for last)
        if i + batch_size < len(items):
            await asyncio.sleep(delay_between_batches)

    return results
```

### asyncio.TaskGroup (Python 3.11+)

```python
async def process_with_taskgroup(prompts: list[str]) -> list[str]:
    """Process with structured concurrency."""
    results = []

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(call_llm(p)) for p in prompts]

    # All tasks completed (or one raised an exception)
    return [t.result() for t in tasks]
```

---

## 6. Mixing Sync and Async

### Calling Async from Sync

```python
import asyncio


def sync_function():
    """Entry point from sync code."""
    result = asyncio.run(async_function())
    return result


# For multiple calls, reuse the event loop
def sync_batch_process(items: list[str]) -> list[str]:
    async def process_all():
        return await asyncio.gather(*[async_call(i) for i in items])

    return asyncio.run(process_all())
```

### Calling Sync from Async

```python
import asyncio


async def async_with_sync_call():
    """Call blocking sync code from async."""
    # Run in thread pool (doesn't block event loop)
    result = await asyncio.to_thread(blocking_sync_function, arg1, arg2)
    return result


# With custom executor
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)


async def async_with_executor():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, blocking_function, arg)
    return result
```

### Common Pattern: Sync Wrapper for Async Library

```python
class LLMClient:
    """Client with both sync and async interfaces."""

    def __init__(self):
        self._async_client = AsyncAnthropic()

    async def generate_async(self, prompt: str) -> str:
        response = await self._async_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def generate(self, prompt: str) -> str:
        """Sync wrapper for async method."""
        return asyncio.run(self.generate_async(prompt))
```

---

## 7. Error Handling

### Anthropic Exceptions

```python
from anthropic import (
    APIConnectionError,
    RateLimitError,
    APIStatusError,
    BadRequestError,
    AuthenticationError,
)


async def robust_call(prompt: str) -> str | None:
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    except AuthenticationError:
        logger.error("Invalid API key")
        raise

    except RateLimitError as e:
        logger.warning(f"Rate limited, retry after: {e.response.headers.get('retry-after')}")
        raise

    except BadRequestError as e:
        logger.error(f"Bad request: {e.message}")
        return None

    except APIConnectionError:
        logger.error("Connection failed")
        raise

    except APIStatusError as e:
        logger.error(f"API error {e.status_code}: {e.message}")
        raise
```

### Timeout Handling

```python
import asyncio


async def call_with_timeout(prompt: str, timeout: float = 30.0) -> str:
    try:
        return await asyncio.wait_for(
            call_llm(prompt),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"Call timed out after {timeout}s")
        raise
```

### Circuit Breaker Pattern

```python
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: timedelta = timedelta(seconds=30)

    failures: int = 0
    last_failure: datetime | None = None
    state: str = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failures += 1
        self.last_failure = datetime.now()
        if self.failures >= self.failure_threshold:
            self.state = "open"

    def record_success(self):
        self.failures = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if datetime.now() - self.last_failure > self.recovery_timeout:
                self.state = "half-open"
                return True
            return False
        return True  # half-open allows one attempt


circuit_breaker = CircuitBreaker()


async def call_with_circuit_breaker(prompt: str) -> str:
    if not circuit_breaker.can_execute():
        raise Exception("Circuit breaker is open")

    try:
        result = await call_llm(prompt)
        circuit_breaker.record_success()
        return result
    except Exception as e:
        circuit_breaker.record_failure()
        raise
```

---

## 8. Production Patterns

### Request Logging

```python
import structlog
import time

logger = structlog.get_logger()


async def call_llm_with_logging(
    prompt: str,
    request_id: str | None = None,
) -> str:
    log = logger.bind(
        request_id=request_id,
        prompt_length=len(prompt),
    )

    start = time.perf_counter()
    log.info("Starting LLM call")

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "LLM call completed",
            duration_ms=round(duration_ms, 2),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

        return response.content[0].text

    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        log.error(
            "LLM call failed",
            duration_ms=round(duration_ms, 2),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
```

### Caching Responses

```python
from functools import lru_cache
import hashlib


def cache_key(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:16]


# Simple in-memory cache
_cache: dict[str, str] = {}


async def call_llm_cached(
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    use_cache: bool = True,
) -> str:
    key = cache_key(prompt, model)

    if use_cache and key in _cache:
        logger.debug("Cache hit", cache_key=key)
        return _cache[key]

    response = await call_llm(prompt, model)

    if use_cache:
        _cache[key] = response

    return response
```

### Graceful Shutdown

```python
import signal


class LLMService:
    def __init__(self):
        self.client = AsyncAnthropic()
        self._shutdown = False

    async def process_queue(self, queue: asyncio.Queue):
        while not self._shutdown:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
                await self.process_item(item)
            except asyncio.TimeoutError:
                continue

    def shutdown(self):
        self._shutdown = True


service = LLMService()


def handle_shutdown(signum, frame):
    logger.info("Shutting down gracefully...")
    service.shutdown()


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)
```

---

## Quick Reference

```python
# Basic async call
response = await client.messages.create(...)

# Streaming
async with client.messages.stream(...) as stream:
    async for text in stream.text_stream:
        print(text)

# Rate limiting with semaphore
semaphore = asyncio.Semaphore(10)
async with semaphore:
    await call_llm(prompt)

# Concurrent calls
results = await asyncio.gather(*tasks, return_exceptions=True)

# Call sync from async
result = await asyncio.to_thread(blocking_func, arg)

# Call async from sync
result = asyncio.run(async_func())

# Timeout
result = await asyncio.wait_for(call(), timeout=30)
```

---

## Resources

- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [Tenacity (Retry Library)](https://tenacity.readthedocs.io/)
- [Python asyncio Docs](https://docs.python.org/3/library/asyncio.html)
