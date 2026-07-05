# MLX Local Inference Best Practices

Running LLMs locally on Apple Silicon using MLX and mlx-lm.

---

## Table of Contents

1. [Why MLX](#1-why-mlx)
2. [Installation](#2-installation)
3. [Loading Models](#3-loading-models)
4. [Basic Inference](#4-basic-inference)
5. [Streaming Generation](#5-streaming-generation)
6. [Quantization](#6-quantization)
7. [Memory Management](#7-memory-management)
8. [Performance Optimization](#8-performance-optimization)
9. [Integration Patterns](#9-integration-patterns)
10. [Production Considerations](#10-production-considerations)

---

## 1. Why MLX

MLX is Apple's machine learning framework optimized for Apple Silicon. Key advantages:

| Feature | Benefit |
|---------|---------|
| Unified Memory | Zero-copy between CPU and GPU |
| Lazy Evaluation | Automatic operation fusion |
| Native Performance | Optimized for M-series chips |
| Python-First | NumPy-like API |

### When to Use MLX

- Local inference on Mac (M1/M2/M3/M4/M5)
- Privacy-sensitive applications
- Offline operation
- Avoiding API costs for development
- Quick prototyping

### Memory Requirements

| Model Size | BF16 Memory | 4-bit Quantized |
|------------|-------------|-----------------|
| 7B | ~14GB | ~4GB |
| 13B | ~26GB | ~7GB |
| 30B (MoE) | ~60GB | ~18GB |
| 70B | ~140GB | ~40GB |

**Rule of thumb**: Your Mac needs RAM ≥ model size in the precision you're using.

---

## 2. Installation

```bash
# Add to project
uv add mlx mlx-lm

# Or install globally for CLI use
uv tool install mlx-lm
```

Verify installation:
```python
import mlx.core as mx
print(mx.default_device())  # Should show 'gpu' on Apple Silicon
```

---

## 3. Loading Models

### From Hugging Face

```python
from mlx_lm import load

# Load model and tokenizer
model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")

# With custom tokenizer config
model, tokenizer = load(
    "mlx-community/Qwen2.5-7B-Instruct-4bit",
    tokenizer_config={
        "eos_token": "<|endoftext|>",
        "trust_remote_code": True,
    },
)
```

### Pre-quantized Models

The [mlx-community](https://huggingface.co/mlx-community) on Hugging Face has many pre-converted models:

```python
# Popular models (4-bit quantized)
model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")
model, tokenizer = load("mlx-community/Llama-3.2-3B-Instruct-4bit")
model, tokenizer = load("mlx-community/Mistral-7B-Instruct-v0.3-4bit")
model, tokenizer = load("mlx-community/gemma-2-9b-it-4bit")
```

### Local Models

```python
# Load from local path
model, tokenizer = load("./models/my-model")
```

---

## 4. Basic Inference

### Simple Generation

```python
from mlx_lm import load, generate

model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")

# Generate text
response = generate(
    model,
    tokenizer,
    prompt="Explain quantum computing in simple terms.",
    max_tokens=256,
    temp=0.7,
)
print(response)
```

### Chat Format

```python
from mlx_lm import load, generate


def chat(model, tokenizer, messages: list[dict]) -> str:
    """Generate response using chat format."""
    # Apply chat template
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    return generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=512,
        temp=0.7,
    )


# Usage
model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
]

response = chat(model, tokenizer, messages)
print(response)
```

### Generation Parameters

```python
response = generate(
    model,
    tokenizer,
    prompt=prompt,
    max_tokens=512,        # Maximum tokens to generate
    temp=0.7,              # Temperature (0 = deterministic)
    top_p=0.9,             # Nucleus sampling
    repetition_penalty=1.1, # Penalize repetition
    repetition_context_size=20,  # Context for repetition check
)
```

---

## 5. Streaming Generation

### Basic Streaming

```python
from mlx_lm import load, stream_generate


def stream_chat(model, tokenizer, prompt: str):
    """Stream tokens as they're generated."""
    for response in stream_generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=512,
        temp=0.7,
    ):
        # response.text contains the new token
        print(response.text, end="", flush=True)
    print()  # Newline at end


model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")
stream_chat(model, tokenizer, "Tell me a short story about a robot.")
```

### Async Streaming Wrapper

```python
import asyncio
from collections.abc import AsyncGenerator
from mlx_lm import load, stream_generate


async def async_stream(
    model,
    tokenizer,
    prompt: str,
    max_tokens: int = 512,
) -> AsyncGenerator[str, None]:
    """Async wrapper for MLX streaming."""
    # Run in thread to not block event loop
    def sync_stream():
        for response in stream_generate(
            model, tokenizer, prompt=prompt, max_tokens=max_tokens
        ):
            yield response.text

    loop = asyncio.get_event_loop()

    # Process in batches to maintain responsiveness
    for token in sync_stream():
        yield token
        await asyncio.sleep(0)  # Yield control to event loop
```

---

## 6. Quantization

### Why Quantize?

| Precision | Memory | Speed | Quality |
|-----------|--------|-------|---------|
| BF16 | 2 bytes/param | Baseline | Best |
| 8-bit | 1 byte/param | Faster | Very good |
| 4-bit | 0.5 bytes/param | Fastest | Good |

### Converting Models

```bash
# Command line
uv run python -m mlx_lm.convert \
    --hf-path mistralai/Mistral-7B-Instruct-v0.3 \
    -q \
    --q-bits 4 \
    --q-group-size 64 \
    --mlx-path ./models/mistral-7b-4bit
```

```python
# Python API
from mlx_lm import convert

convert(
    hf_path="mistralai/Mistral-7B-Instruct-v0.3",
    mlx_path="./models/mistral-7b-4bit",
    quantize=True,
    q_bits=4,
    q_group_size=64,
)
```

### Mixed Precision

Keep sensitive layers at higher precision:

```bash
# Keep embeddings and lm_head at 6-bit, rest at 4-bit
uv run python -m mlx_lm.convert \
    --hf-path meta-llama/Llama-3.2-3B-Instruct \
    -q \
    --q-bits 4 \
    --q-bits-embeddings 6 \
    --mlx-path ./models/llama-3.2-3b-mixed
```

---

## 7. Memory Management

### Unified Memory Benefits

On Apple Silicon, CPU and GPU share memory:

```python
import mlx.core as mx

# Arrays live in shared memory
x = mx.array([1, 2, 3])  # Accessible by both CPU and GPU

# No explicit transfers needed
# This is different from CUDA where you copy to/from GPU
```

### Memory Estimation

```python
def estimate_memory(model_params: int, bits: int = 16) -> float:
    """Estimate memory in GB for a model."""
    bytes_per_param = bits / 8
    return (model_params * bytes_per_param) / (1024**3)


# Examples
print(f"7B at 16-bit: {estimate_memory(7e9, 16):.1f} GB")   # ~13 GB
print(f"7B at 4-bit: {estimate_memory(7e9, 4):.1f} GB")     # ~3.3 GB
print(f"70B at 4-bit: {estimate_memory(70e9, 4):.1f} GB")   # ~33 GB
```

### KV Cache Management

For long contexts, manage the key-value cache:

```python
# Limit KV cache size (useful for memory-constrained systems)
response = generate(
    model,
    tokenizer,
    prompt=long_prompt,
    max_tokens=1024,
    max_kv_size=512,  # Rotating cache of 512 tokens
)
```

### Clearing Memory

```python
import gc
import mlx.core as mx


def clear_memory():
    """Clear MLX memory cache."""
    gc.collect()
    mx.metal.clear_cache()
```

---

## 8. Performance Optimization

### Compilation

Use `mx.compile` for repeated operations:

```python
import mlx.core as mx


@mx.compile
def forward_pass(model, inputs):
    return model(inputs)


# First call compiles, subsequent calls are faster
output = forward_pass(model, inputs)
```

### Prompt Caching

For repeated prefixes (e.g., system prompts):

```python
from mlx_lm import load, generate

model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")

# First call caches the system prompt
system_prompt = "You are a helpful assistant specialized in Python."

# Subsequent calls with same prefix reuse the cache
for user_query in queries:
    full_prompt = f"{system_prompt}\n\nUser: {user_query}\nAssistant:"
    response = generate(model, tokenizer, prompt=full_prompt, max_tokens=256)
```

### Batch Processing

```python
def batch_generate(
    model,
    tokenizer,
    prompts: list[str],
    max_tokens: int = 256,
) -> list[str]:
    """Process multiple prompts (sequentially for now)."""
    # Note: MLX doesn't have native batching yet
    # Process sequentially but benefit from warm cache
    return [
        generate(model, tokenizer, prompt=p, max_tokens=max_tokens)
        for p in prompts
    ]
```

### Performance Tips

1. **Use pre-quantized models** from mlx-community
2. **Keep models loaded** - loading is slow, inference is fast
3. **Use appropriate quantization** - 4-bit for most use cases
4. **Limit KV cache** for very long contexts
5. **Compile hot paths** with `@mx.compile`

---

## 9. Integration Patterns

### LangChain Integration

```python
from langchain_community.llms import MLXPipeline

llm = MLXPipeline.from_model_id(
    model_id="mlx-community/Qwen2.5-7B-Instruct-4bit",
    pipeline_kwargs={"max_tokens": 512, "temp": 0.7},
)

response = llm.invoke("What is machine learning?")
```

### FastAPI Integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from mlx_lm import load, generate


# Global model state
class ModelState:
    model = None
    tokenizer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model on startup
    ModelState.model, ModelState.tokenizer = load(
        "mlx-community/Qwen2.5-7B-Instruct-4bit"
    )
    yield
    # Cleanup on shutdown
    ModelState.model = None
    ModelState.tokenizer = None


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    max_tokens: int = 256


@app.post("/chat")
async def chat(request: ChatRequest):
    # Run inference in thread to not block
    import asyncio

    response = await asyncio.to_thread(
        generate,
        ModelState.model,
        ModelState.tokenizer,
        prompt=request.message,
        max_tokens=request.max_tokens,
    )
    return {"response": response}
```

### CLI Tool

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-lm", "rich"]
# ///

import sys
from mlx_lm import load, stream_generate
from rich.console import Console

console = Console()

MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"


def main():
    console.print(f"[bold]Loading {MODEL}...[/bold]")
    model, tokenizer = load(MODEL)
    console.print("[green]Ready![/green]\n")

    while True:
        try:
            prompt = console.input("[bold blue]You:[/bold blue] ")
            if prompt.lower() in ("exit", "quit"):
                break

            console.print("[bold green]Assistant:[/bold green] ", end="")
            for response in stream_generate(model, tokenizer, prompt=prompt):
                console.print(response.text, end="")
            console.print("\n")

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
```

---

## 10. Production Considerations

### Model Selection

| Use Case | Recommended Model |
|----------|-------------------|
| General chat | Qwen2.5-7B-Instruct-4bit |
| Coding | Qwen2.5-Coder-7B-Instruct-4bit |
| Fast responses | Llama-3.2-3B-Instruct-4bit |
| High quality | Llama-3.1-70B-Instruct-4bit (needs 64GB+ RAM) |

### Error Handling

```python
from mlx_lm import load, generate


class MLXInferenceError(Exception):
    pass


def safe_generate(model, tokenizer, prompt: str, **kwargs) -> str:
    try:
        return generate(model, tokenizer, prompt=prompt, **kwargs)
    except MemoryError:
        raise MLXInferenceError("Out of memory - try a smaller model or shorter context")
    except Exception as e:
        raise MLXInferenceError(f"Generation failed: {e}")
```

### Monitoring

```python
import time
import structlog

logger = structlog.get_logger()


def generate_with_metrics(model, tokenizer, prompt: str, **kwargs) -> str:
    start = time.perf_counter()
    prompt_tokens = len(tokenizer.encode(prompt))

    response = generate(model, tokenizer, prompt=prompt, **kwargs)

    response_tokens = len(tokenizer.encode(response))
    duration = time.perf_counter() - start
    tokens_per_second = response_tokens / duration

    logger.info(
        "MLX generation complete",
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        duration_s=round(duration, 2),
        tokens_per_second=round(tokens_per_second, 1),
    )

    return response
```

---

## Quick Reference

```python
from mlx_lm import load, generate, stream_generate

# Load model
model, tokenizer = load("mlx-community/Qwen2.5-7B-Instruct-4bit")

# Generate
response = generate(model, tokenizer, prompt="Hello", max_tokens=256)

# Stream
for r in stream_generate(model, tokenizer, prompt="Hello"):
    print(r.text, end="")

# Chat format
messages = [{"role": "user", "content": "Hello"}]
prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
response = generate(model, tokenizer, prompt=prompt)
```

---

## Resources

- [MLX Documentation](https://ml-explore.github.io/mlx/)
- [mlx-lm GitHub](https://github.com/ml-explore/mlx-lm)
- [MLX Community Models](https://huggingface.co/mlx-community)
- [Apple MLX Research](https://machinelearning.apple.com/research/exploring-llms-mlx-m5)
