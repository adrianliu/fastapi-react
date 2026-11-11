"""The `claude -p` wrapper (spec 7): one typed function, `run_structured`.

    result = run_structured(prompt, LabelV1, llm_model="sonnet", purpose="label",
                            prompt_version="label-1")
    result.value  # a validated LabelV1

The prompt goes on stdin, `cwd` is `~/.hindcast/llm-cwd/`, and the answer is the JSON result's
`structured_output`, validated against the Pydantic model whose JSON Schema was passed to
`--json-schema`. One retry on timeout or failure; then `LLMError` with the last `result` text.
Every attempt sequence is recorded in `llm_calls` (unless `record=False`).

Tests must never run the real CLI: monkeypatch `hindcast.llm.runner.invoke_cli` (the subprocess
seam) or the `run_structured` name imported by the module under test.
"""

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from hindcast.config import llm_cwd
from hindcast.store.db import get_db, utc_now
from hindcast.types import JsonValue

# Default models per purpose (spec 7). All configurable through the `llm_model` argument.
DEFAULT_MODELS: dict[str, str] = {
    "label": "sonnet",
    "group": "opus",
    "distill": "opus",
    "extract": "opus",
    "task_write": "opus",
    "judge": "opus",
}

Purpose = Literal["label", "group", "distill", "extract", "task_write", "judge", "other"]


class LLMError(RuntimeError):
    """`claude -p` failed twice. `last_result` holds the last `result` text, if any."""

    def __init__(self, message: str, last_result: str | None = None) -> None:
        super().__init__(message)
        self.last_result = last_result


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class Result[T: BaseModel]:
    value: T
    model_used: str | None  # the key of `modelUsage`
    duration_ms: int
    usage: Usage
    total_cost_usd: float  # API list-price equivalent, not billed on a subscription
    input_sha256: str
    attempts: int
    llm_call_id: int | None  # row in llm_calls, None when record=False


@dataclass(frozen=True)
class CliOutput:
    returncode: int
    stdout: str
    stderr: str


def build_command(schema_json: str, llm_model: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--safe-mode",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--model",
        llm_model,
        "--json-schema",
        schema_json,
    ]


def invoke_cli(cmd: list[str], prompt: str, timeout_s: int) -> CliOutput:
    """Run the CLI. The subprocess seam that tests replace."""
    cwd = llm_cwd()
    cwd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # Never bill an API key by accident: `--safe-mode` keeps the subscription login.
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=timeout_s,
        check=False,
    )
    return CliOutput(proc.returncode, proc.stdout, proc.stderr)


def _as_int(value: JsonValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse[T: BaseModel](out: CliOutput, model: type[T]) -> tuple[T, str | None, Usage, float, int]:
    """Parse one CLI run. Raises LLMError with the result text on any failure (spec 7)."""
    try:
        data: JsonValue = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(
            f"claude -p exit {out.returncode}: output is not JSON: {out.stderr[-500:]}"
        ) from e
    if not isinstance(data, dict):
        raise LLMError("claude -p output is not a JSON object")
    result_text = data.get("result")
    last = result_text if isinstance(result_text, str) else None
    if out.returncode != 0:
        raise LLMError(f"claude -p exit {out.returncode}", last)
    if data.get("is_error") is True:
        raise LLMError("claude -p returned is_error", last)
    structured = data.get("structured_output")
    if structured is None:
        raise LLMError("claude -p returned no structured_output", last)
    try:
        value = model.model_validate(structured)
    except ValidationError as e:
        raise LLMError(f"structured_output failed validation: {e}", last) from e

    model_usage = data.get("modelUsage")
    model_used = next(iter(model_usage), None) if isinstance(model_usage, dict) else None
    u = data.get("usage")
    usage = (
        Usage(
            input_tokens=_as_int(u.get("input_tokens")),
            output_tokens=_as_int(u.get("output_tokens")),
            cache_read_tokens=_as_int(u.get("cache_read_input_tokens")),
            cache_creation_tokens=_as_int(u.get("cache_creation_input_tokens")),
        )
        if isinstance(u, dict)
        else Usage()
    )
    cost = data.get("total_cost_usd")
    duration = data.get("duration_ms")
    return (
        value,
        model_used,
        usage,
        float(cost) if isinstance(cost, int | float) else 0.0,
        _as_int(duration),
    )


def _record(
    *,
    purpose: str,
    job_id: int | None,
    llm_model: str,
    model_used: str | None,
    prompt_version: str | None,
    schema_name: str,
    schema_version: str | None,
    input_sha256: str,
    input_chars: int,
    status: str,
    attempts: int,
    error: str | None,
    duration_ms: int,
    usage: Usage,
    cost: float,
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO llm_calls (purpose, job_id, model_requested, model_used, prompt_version,"
            " schema_name, schema_version, input_sha256, input_chars, status, attempts, error,"
            " duration_ms, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,"
            " total_cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                purpose,
                job_id,
                llm_model,
                model_used,
                prompt_version,
                schema_name,
                schema_version,
                input_sha256,
                input_chars,
                status,
                attempts,
                error,
                duration_ms,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_creation_tokens,
                cost,
                utc_now(),
            ),
        )
    assert cur.lastrowid is not None
    return cur.lastrowid


def run_structured[T: BaseModel](
    prompt: str,
    model: type[T],
    *,
    llm_model: str,
    timeout_s: int = 900,
    purpose: Purpose = "other",
    prompt_version: str | None = None,
    schema_version: str | None = None,
    job_id: int | None = None,
    record: bool = True,
) -> Result[T]:
    """Ask `claude -p` for a `model` instance. Retries once; raises `LLMError` after that."""
    schema_json = json.dumps(model.model_json_schema())
    cmd = build_command(schema_json, llm_model)
    input_sha = hashlib.sha256(prompt.encode()).hexdigest()
    started = time.monotonic()
    last_error: LLMError | None = None
    attempts = 0
    for attempt in (1, 2):
        attempts = attempt
        try:
            out = invoke_cli(cmd, prompt, timeout_s)
            value, model_used, usage, cost, duration_ms = _parse(out, model)
        except subprocess.TimeoutExpired:
            last_error = LLMError(f"claude -p timed out after {timeout_s}s")
            continue
        except LLMError as e:
            last_error = e
            continue
        call_id = (
            _record(
                purpose=purpose,
                job_id=job_id,
                llm_model=llm_model,
                model_used=model_used,
                prompt_version=prompt_version,
                schema_name=model.__name__,
                schema_version=schema_version,
                input_sha256=input_sha,
                input_chars=len(prompt),
                status="ok",
                attempts=attempts,
                error=None,
                duration_ms=duration_ms,
                usage=usage,
                cost=cost,
            )
            if record
            else None
        )
        return Result(
            value=value,
            model_used=model_used,
            duration_ms=duration_ms,
            usage=usage,
            total_cost_usd=cost,
            input_sha256=input_sha,
            attempts=attempts,
            llm_call_id=call_id,
        )
    assert last_error is not None
    if record:
        _record(
            purpose=purpose,
            job_id=job_id,
            llm_model=llm_model,
            model_used=None,
            prompt_version=prompt_version,
            schema_name=model.__name__,
            schema_version=schema_version,
            input_sha256=input_sha,
            input_chars=len(prompt),
            status="error",
            attempts=attempts,
            error=f"{last_error}: {last_error.last_result or ''}"[:2000],
            duration_ms=int((time.monotonic() - started) * 1000),
            usage=Usage(),
            cost=0.0,
        )
    raise last_error
