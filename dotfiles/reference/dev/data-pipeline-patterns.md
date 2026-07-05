# Data Pipeline Patterns for AI Workloads

Patterns for building robust data pipelines: chunking, embeddings, batch processing, and fault-tolerant pipelines.

---

## Table of Contents

1. [Pipeline Architecture](#1-pipeline-architecture)
2. [Chunking Strategies](#2-chunking-strategies)
3. [Embedding Generation](#3-embedding-generation)
4. [Batch Processing](#4-batch-processing)
5. [Checkpointing & Resume](#5-checkpointing--resume)
6. [Error Handling](#6-error-handling)
7. [Progress Tracking](#7-progress-tracking)
8. [Production Patterns](#8-production-patterns)

---

## 1. Pipeline Architecture

### Typical AI Data Pipeline

```
┌─────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌────────┐
│ Ingest  │───▶│ Transform │───▶│   Chunk    │───▶│  Embed   │───▶│ Store  │
└─────────┘    └──────────┘    └────────────┘    └──────────┘    └────────┘
     │              │               │                 │              │
     └──────────────┴───────────────┴─────────────────┴──────────────┘
                              Checkpoint at each stage
```

### Pipeline Class Pattern

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class PipelineConfig:
    input_dir: Path
    output_dir: Path
    checkpoint_dir: Path
    batch_size: int = 100
    resume: bool = True


class PipelineStage(ABC):
    """Base class for pipeline stages."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    @abstractmethod
    def process(self, item):
        """Process a single item."""
        pass

    @abstractmethod
    def checkpoint_key(self, item) -> str:
        """Return unique key for checkpointing."""
        pass


class Pipeline:
    """Orchestrates pipeline stages."""

    def __init__(self, config: PipelineConfig, stages: list[PipelineStage]):
        self.config = config
        self.stages = stages
        self.checkpoint = CheckpointManager(config.checkpoint_dir)

    def run(self, items: list):
        for stage in self.stages:
            logger.info(f"Running stage: {stage.__class__.__name__}")
            items = self._run_stage(stage, items)
        return items

    def _run_stage(self, stage: PipelineStage, items: list) -> list:
        results = []
        for item in items:
            key = stage.checkpoint_key(item)
            if self.config.resume and self.checkpoint.exists(key):
                result = self.checkpoint.load(key)
            else:
                result = stage.process(item)
                self.checkpoint.save(key, result)
            results.append(result)
        return results
```

---

## 2. Chunking Strategies

### Fixed-Size Chunking

```python
def chunk_fixed_size(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """Split text into fixed-size chunks with overlap."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks
```

### Sentence-Based Chunking

```python
import re


def chunk_by_sentences(
    text: str,
    max_chunk_size: int = 1000,
    min_chunk_size: int = 100,
) -> list[str]:
    """Split text by sentences, grouping into chunks."""
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = []
    current_size = 0

    for sentence in sentences:
        sentence_size = len(sentence)

        if current_size + sentence_size > max_chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_size = 0

        current_chunk.append(sentence)
        current_size += sentence_size

    # Don't forget the last chunk
    if current_chunk:
        chunk_text = " ".join(current_chunk)
        if len(chunk_text) >= min_chunk_size:
            chunks.append(chunk_text)
        elif chunks:
            # Append to previous chunk if too small
            chunks[-1] += " " + chunk_text

    return chunks
```

### Semantic Chunking

```python
from sentence_transformers import SentenceTransformer
import numpy as np


class SemanticChunker:
    """Split text based on semantic similarity."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def chunk(
        self,
        text: str,
        similarity_threshold: float = 0.5,
        min_chunk_size: int = 100,
    ) -> list[str]:
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) < 2:
            return [text]

        # Get embeddings
        embeddings = self.model.encode(sentences)

        # Find breakpoints based on similarity
        chunks = []
        current_chunk = [sentences[0]]

        for i in range(1, len(sentences)):
            # Cosine similarity between consecutive sentences
            sim = np.dot(embeddings[i-1], embeddings[i]) / (
                np.linalg.norm(embeddings[i-1]) * np.linalg.norm(embeddings[i])
            )

            if sim < similarity_threshold:
                # Low similarity = new chunk
                chunk_text = " ".join(current_chunk)
                if len(chunk_text) >= min_chunk_size:
                    chunks.append(chunk_text)
                current_chunk = []

            current_chunk.append(sentences[i])

        # Last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
```

### Document-Aware Chunking

```python
import re


def chunk_markdown(text: str, max_chunk_size: int = 1500) -> list[dict]:
    """Chunk markdown preserving structure."""
    chunks = []

    # Split by headers
    sections = re.split(r'\n(#{1,6}\s+[^\n]+)\n', text)

    current_chunk = ""
    current_header = ""

    for i, section in enumerate(sections):
        if re.match(r'^#{1,6}\s+', section):
            current_header = section.strip()
            continue

        # Add header to section
        section_with_header = f"{current_header}\n\n{section}" if current_header else section

        if len(current_chunk) + len(section_with_header) > max_chunk_size:
            if current_chunk:
                chunks.append({
                    "content": current_chunk.strip(),
                    "header": current_header,
                })
            current_chunk = section_with_header
        else:
            current_chunk += "\n\n" + section_with_header

    if current_chunk.strip():
        chunks.append({
            "content": current_chunk.strip(),
            "header": current_header,
        })

    return chunks
```

### Choosing a Chunking Strategy

| Strategy | Best For | Chunk Size |
|----------|----------|------------|
| Fixed-size | Simple documents, logs | 500-1000 chars |
| Sentence-based | Articles, prose | 500-1500 chars |
| Semantic | Technical docs, mixed content | Varies |
| Document-aware | Markdown, structured docs | 1000-2000 chars |

**Rule of thumb**: Start with 10-20% overlap for fixed-size chunks.

---

## 3. Embedding Generation

### Basic Embedding with OpenAI

```python
from openai import OpenAI
import numpy as np

client = OpenAI()


def embed_texts(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """Generate embeddings for a list of texts."""
    response = client.embeddings.create(
        model=model,
        input=texts,
    )
    return [item.embedding for item in response.data]


def embed_single(text: str) -> list[float]:
    """Generate embedding for a single text."""
    return embed_texts([text])[0]
```

### Batched Embedding with Rate Limiting

```python
import asyncio
from openai import AsyncOpenAI

client = AsyncOpenAI()


async def embed_batch_async(
    texts: list[str],
    model: str = "text-embedding-3-small",
    batch_size: int = 100,
    delay_between_batches: float = 0.5,
) -> list[list[float]]:
    """Generate embeddings in batches with rate limiting."""
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        response = await client.embeddings.create(
            model=model,
            input=batch,
        )

        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

        # Rate limit
        if i + batch_size < len(texts):
            await asyncio.sleep(delay_between_batches)

    return all_embeddings
```

### Local Embeddings with Sentence Transformers

```python
from sentence_transformers import SentenceTransformer
import numpy as np


class LocalEmbedder:
    """Generate embeddings locally."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts. Returns numpy array of shape (n_texts, embedding_dim)."""
        return self.model.encode(texts, show_progress_bar=True)

    def embed_single(self, text: str) -> np.ndarray:
        return self.model.encode([text])[0]
```

### Embedding Pipeline Stage

```python
from dataclasses import dataclass
import numpy as np


@dataclass
class ChunkedDocument:
    id: str
    chunks: list[str]
    metadata: dict


@dataclass
class EmbeddedDocument:
    id: str
    chunks: list[str]
    embeddings: np.ndarray
    metadata: dict


class EmbeddingStage(PipelineStage):
    """Pipeline stage for generating embeddings."""

    def __init__(self, config: PipelineConfig, embedder):
        super().__init__(config)
        self.embedder = embedder

    def process(self, doc: ChunkedDocument) -> EmbeddedDocument:
        embeddings = self.embedder.embed(doc.chunks)
        return EmbeddedDocument(
            id=doc.id,
            chunks=doc.chunks,
            embeddings=embeddings,
            metadata=doc.metadata,
        )

    def checkpoint_key(self, doc: ChunkedDocument) -> str:
        return f"embed_{doc.id}"
```

---

## 4. Batch Processing

### Generator-Based Processing

```python
from collections.abc import Generator, Iterable
from typing import TypeVar

T = TypeVar("T")


def batched(iterable: Iterable[T], batch_size: int) -> Generator[list[T], None, None]:
    """Yield batches from an iterable."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


# Usage
for batch in batched(documents, batch_size=100):
    process_batch(batch)
```

### Parallel Processing with ThreadPoolExecutor

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import structlog

logger = structlog.get_logger()


def process_parallel(
    items: list,
    process_fn: Callable,
    max_workers: int = 4,
) -> list:
    """Process items in parallel using threads."""
    results = [None] * len(items)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(process_fn, item): i
            for i, item in enumerate(items)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error(f"Failed item {idx}: {e}")
                results[idx] = None

    return results
```

### Async Batch Processing

```python
import asyncio


async def process_batch_async(
    items: list,
    process_fn,
    batch_size: int = 10,
    max_concurrent: int = 5,
) -> list:
    """Process items in async batches with concurrency limit."""
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async def process_with_semaphore(item):
        async with semaphore:
            return await process_fn(item)

    for batch in batched(items, batch_size):
        batch_results = await asyncio.gather(
            *[process_with_semaphore(item) for item in batch],
            return_exceptions=True,
        )
        results.extend(batch_results)

    return results
```

---

## 5. Checkpointing & Resume

### Simple File-Based Checkpointing

```python
import json
from pathlib import Path
import hashlib


class CheckpointManager:
    """Manage checkpoints for pipeline stages."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> Path:
        # Hash long keys to prevent filesystem issues
        hashed = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.checkpoint_dir / f"{hashed}.json"

    def exists(self, key: str) -> bool:
        return self._key_to_path(key).exists()

    def save(self, key: str, data):
        path = self._key_to_path(key)
        with open(path, "w") as f:
            json.dump({"key": key, "data": data}, f)

    def load(self, key: str):
        path = self._key_to_path(key)
        with open(path) as f:
            return json.load(f)["data"]

    def clear(self):
        for path in self.checkpoint_dir.glob("*.json"):
            path.unlink()
```

### Checkpointing with numpy arrays

```python
import numpy as np
from pathlib import Path


class NumpyCheckpoint:
    """Checkpoint manager that handles numpy arrays."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, embeddings: np.ndarray, metadata: dict):
        path = self.checkpoint_dir / f"{key}.npz"
        np.savez(path, embeddings=embeddings, metadata=np.array([metadata]))

    def load(self, key: str) -> tuple[np.ndarray, dict]:
        path = self.checkpoint_dir / f"{key}.npz"
        data = np.load(path, allow_pickle=True)
        return data["embeddings"], data["metadata"][0]

    def exists(self, key: str) -> bool:
        return (self.checkpoint_dir / f"{key}.npz").exists()
```

### Progress-Based Checkpointing

```python
from dataclasses import dataclass, asdict
import json
from pathlib import Path


@dataclass
class PipelineProgress:
    total_items: int
    processed_items: int
    current_stage: str
    last_processed_id: str | None = None


class ProgressCheckpoint:
    """Track and resume pipeline progress."""

    def __init__(self, checkpoint_file: Path):
        self.checkpoint_file = Path(checkpoint_file)

    def save(self, progress: PipelineProgress):
        with open(self.checkpoint_file, "w") as f:
            json.dump(asdict(progress), f)

    def load(self) -> PipelineProgress | None:
        if not self.checkpoint_file.exists():
            return None
        with open(self.checkpoint_file) as f:
            return PipelineProgress(**json.load(f))

    def clear(self):
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
```

### Resumable Pipeline

```python
class ResumablePipeline:
    """Pipeline that can resume from last checkpoint."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.progress = ProgressCheckpoint(config.checkpoint_dir / "progress.json")
        self.item_checkpoints = CheckpointManager(config.checkpoint_dir / "items")

    def run(self, items: list):
        # Check for existing progress
        existing_progress = self.progress.load()

        if existing_progress and self.config.resume:
            logger.info(
                f"Resuming from {existing_progress.processed_items}/{existing_progress.total_items}"
            )
            start_idx = existing_progress.processed_items
        else:
            start_idx = 0

        progress = PipelineProgress(
            total_items=len(items),
            processed_items=start_idx,
            current_stage="processing",
        )

        for i, item in enumerate(items[start_idx:], start=start_idx):
            try:
                self.process_item(item)
                progress.processed_items = i + 1
                progress.last_processed_id = str(item.id)
                self.progress.save(progress)

            except Exception as e:
                logger.error(f"Failed at item {i}: {e}")
                raise

        progress.current_stage = "complete"
        self.progress.save(progress)
```

---

## 6. Error Handling

### Retry with Backoff

```python
import asyncio
import random
from functools import wraps


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
):
    """Decorator for retry with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(
                            base_delay * (exponential_base ** attempt) + random.uniform(0, 1),
                            max_delay,
                        )
                        logger.warning(
                            f"Attempt {attempt + 1} failed, retrying in {delay:.1f}s",
                            error=str(e),
                        )
                        await asyncio.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


# Usage
@retry_with_backoff(max_retries=5)
async def call_api(data):
    ...
```

### Dead Letter Queue Pattern

```python
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path


@dataclass
class FailedItem:
    item_id: str
    error: str
    timestamp: str
    attempt: int
    item_data: dict


class DeadLetterQueue:
    """Store failed items for later inspection/retry."""

    def __init__(self, dlq_dir: Path):
        self.dlq_dir = Path(dlq_dir)
        self.dlq_dir.mkdir(parents=True, exist_ok=True)

    def add(self, item_id: str, error: Exception, item_data: dict, attempt: int = 1):
        failed = FailedItem(
            item_id=item_id,
            error=str(error),
            timestamp=datetime.now().isoformat(),
            attempt=attempt,
            item_data=item_data,
        )
        path = self.dlq_dir / f"{item_id}_{datetime.now().timestamp()}.json"
        with open(path, "w") as f:
            json.dump(asdict(failed), f, indent=2)

    def get_all(self) -> list[FailedItem]:
        items = []
        for path in self.dlq_dir.glob("*.json"):
            with open(path) as f:
                items.append(FailedItem(**json.load(f)))
        return items

    def retry_all(self, process_fn) -> tuple[int, int]:
        """Retry all failed items. Returns (success_count, fail_count)."""
        success = 0
        fail = 0
        for item in self.get_all():
            try:
                process_fn(item.item_data)
                # Remove from DLQ on success
                # ...
                success += 1
            except Exception:
                fail += 1
        return success, fail
```

---

## 7. Progress Tracking

### Progress Bar with Rich

```python
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn


def process_with_progress(items: list, process_fn):
    """Process items with progress bar."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        task = progress.add_task("Processing...", total=len(items))

        results = []
        for item in items:
            result = process_fn(item)
            results.append(result)
            progress.update(task, advance=1)

        return results
```

### Async Progress with Logging

```python
import structlog
import asyncio

logger = structlog.get_logger()


async def process_with_logging(
    items: list,
    process_fn,
    batch_size: int = 100,
) -> list:
    """Process items with progress logging."""
    total = len(items)
    results = []

    for i, batch in enumerate(batched(items, batch_size)):
        batch_results = await asyncio.gather(
            *[process_fn(item) for item in batch],
            return_exceptions=True,
        )

        results.extend(batch_results)
        processed = min((i + 1) * batch_size, total)

        logger.info(
            "Processing progress",
            processed=processed,
            total=total,
            percent=round(processed / total * 100, 1),
        )

    return results
```

---

## 8. Production Patterns

### Complete Pipeline Example

```python
import asyncio
from dataclasses import dataclass
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class Document:
    id: str
    content: str
    metadata: dict


@dataclass
class ProcessedDocument:
    id: str
    chunks: list[str]
    embeddings: list[list[float]]
    metadata: dict


class DocumentPipeline:
    """Complete document processing pipeline."""

    def __init__(
        self,
        output_dir: Path,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: str = "text-embedding-3-small",
        batch_size: int = 100,
        resume: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self.resume = resume

        self.checkpoint = CheckpointManager(self.output_dir / "checkpoints")
        self.dlq = DeadLetterQueue(self.output_dir / "dlq")

    async def process(self, documents: list[Document]) -> list[ProcessedDocument]:
        """Process documents through the pipeline."""
        results = []
        failed = 0

        for i, doc in enumerate(documents):
            # Check checkpoint
            if self.resume and self.checkpoint.exists(doc.id):
                logger.debug(f"Skipping {doc.id} (cached)")
                results.append(self.checkpoint.load(doc.id))
                continue

            try:
                processed = await self._process_document(doc)
                self.checkpoint.save(doc.id, processed)
                results.append(processed)

            except Exception as e:
                logger.error(f"Failed to process {doc.id}: {e}")
                self.dlq.add(doc.id, e, {"content": doc.content})
                failed += 1

            # Log progress every batch_size items
            if (i + 1) % self.batch_size == 0:
                logger.info(
                    "Progress",
                    processed=i + 1,
                    total=len(documents),
                    failed=failed,
                )

        logger.info(
            "Pipeline complete",
            total=len(documents),
            success=len(results),
            failed=failed,
        )

        return results

    async def _process_document(self, doc: Document) -> ProcessedDocument:
        """Process a single document."""
        # Chunk
        chunks = chunk_fixed_size(
            doc.content,
            chunk_size=self.chunk_size,
            overlap=self.chunk_overlap,
        )

        # Embed
        embeddings = await embed_batch_async(
            chunks,
            model=self.embedding_model,
        )

        return ProcessedDocument(
            id=doc.id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=doc.metadata,
        )


# Usage
async def main():
    pipeline = DocumentPipeline(
        output_dir=Path("./output"),
        resume=True,
    )

    documents = [
        Document(id="doc1", content="...", metadata={}),
        Document(id="doc2", content="...", metadata={}),
    ]

    results = await pipeline.process(documents)
```

### CLI Interface

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["click", "rich", "structlog"]
# ///

import asyncio
import click
from pathlib import Path


@click.command()
@click.argument("input_dir", type=click.Path(exists=True))
@click.option("--output", "-o", default="./output", help="Output directory")
@click.option("--batch-size", default=100, help="Batch size")
@click.option("--resume/--no-resume", default=True, help="Resume from checkpoint")
def main(input_dir: str, output: str, batch_size: int, resume: bool):
    """Process documents through the AI pipeline."""
    pipeline = DocumentPipeline(
        output_dir=Path(output),
        batch_size=batch_size,
        resume=resume,
    )

    # Load documents
    documents = load_documents(Path(input_dir))

    # Run pipeline
    results = asyncio.run(pipeline.process(documents))

    click.echo(f"Processed {len(results)} documents")


if __name__ == "__main__":
    main()
```

---

## Quick Reference

```python
# Chunking
chunks = chunk_fixed_size(text, chunk_size=1000, overlap=200)
chunks = chunk_by_sentences(text, max_chunk_size=1000)

# Embedding
embeddings = embed_texts(chunks, model="text-embedding-3-small")
embeddings = await embed_batch_async(chunks, batch_size=100)

# Batching
for batch in batched(items, batch_size=100):
    process_batch(batch)

# Checkpointing
checkpoint = CheckpointManager(Path("./checkpoints"))
checkpoint.save("key", data)
data = checkpoint.load("key")

# Progress
with Progress() as progress:
    task = progress.add_task("Processing", total=len(items))
    progress.update(task, advance=1)
```

---

## Resources

- [LangChain Text Splitters](https://python.langchain.com/docs/modules/data_connection/document_transformers/)
- [Sentence Transformers](https://www.sbert.net/)
- [OpenAI Embeddings Guide](https://platform.openai.com/docs/guides/embeddings)
- [Rich Progress](https://rich.readthedocs.io/en/latest/progress.html)
