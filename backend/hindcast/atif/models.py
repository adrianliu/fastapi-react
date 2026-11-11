"""ATIF Pydantic models, vendored from Harbor 0.25.0 (`harbor.models.trajectories`).

The backend must not import Harbor (it lives in a separate uv tool venv), so the models are copied
here with `Any` replaced by `JsonValue`. Behaviour matches Harbor's validators: unknown keys are
rejected everywhere (`extra="forbid"`), agent-only fields are rejected on other sources, step ids
are sequential from 1, and observation `source_call_id`s must reference the step's tool calls.

The loader accepts ATIF-v1.0 to v1.8; export writes `ATIF-v1.7` (spec 2).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hindcast.types import JsonObject

EXPORT_SCHEMA_VERSION = "ATIF-v1.7"

SchemaVersion = Literal[
    "ATIF-v1.0",
    "ATIF-v1.1",
    "ATIF-v1.2",
    "ATIF-v1.3",
    "ATIF-v1.4",
    "ATIF-v1.5",
    "ATIF-v1.6",
    "ATIF-v1.7",
    "ATIF-v1.8",
]

AudioMediaType = Literal[
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
    "audio/webm",
    "audio/aiff",
]

_AUDIO_MEDIA_TYPE_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/mpga": "audio/mpeg",
    "audio/x-mpeg": "audio/mpeg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-aac": "audio/aac",
    "audio/x-flac": "audio/flac",
    "audio/x-aiff": "audio/aiff",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Agent(_Model):
    name: str
    version: str
    model_name: str | None = None
    tool_definitions: list[JsonObject] | None = None
    extra: JsonObject | None = None


class ImageSource(_Model):
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    path: str


class AudioSource(_Model):
    media_type: AudioMediaType
    path: str
    duration_sec: float | None = Field(default=None, ge=0)

    @field_validator("media_type", mode="before")
    @classmethod
    def normalize_media_type(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return _AUDIO_MEDIA_TYPE_ALIASES.get(normalized, normalized)
        return value


class ContentPart(_Model):
    type: Literal["text", "image", "audio"]
    text: str | None = None
    source: ImageSource | AudioSource | None = None

    @model_validator(mode="after")
    def validate_content_type(self) -> "ContentPart":
        if self.type == "text":
            if self.text is None:
                raise ValueError("'text' field is required when type='text'")
            if self.source is not None:
                raise ValueError("'source' field is not allowed when type='text'")
            return self
        if self.source is None:
            raise ValueError(f"'source' field is required when type='{self.type}'")
        if self.text is not None:
            raise ValueError(f"'text' field is not allowed when type='{self.type}'")
        expected = ImageSource if self.type == "image" else AudioSource
        if not isinstance(self.source, expected):
            raise ValueError(
                f"type='{self.type}' requires a {expected.__name__}, but the "
                f"source's media_type is {self.source.media_type!r}"
            )
        return self


class Metrics(_Model):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    prompt_token_ids: list[int] | None = None
    completion_token_ids: list[int] | None = None
    logprobs: list[float] | None = None
    extra: JsonObject | None = None


class FinalMetrics(_Model):
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    total_cached_tokens: int | None = None
    total_cost_usd: float | None = None
    total_steps: int | None = Field(default=None, ge=0)
    extra: JsonObject | None = None


class SubagentTrajectoryRef(_Model):
    trajectory_id: str | None = None
    session_id: str | None = None
    trajectory_path: str | None = None
    extra: JsonObject | None = None

    @model_validator(mode="after")
    def validate_is_resolvable(self) -> "SubagentTrajectoryRef":
        if self.trajectory_id is None and self.trajectory_path is None:
            raise ValueError(
                "SubagentTrajectoryRef must be resolvable: set either `trajectory_id` "
                "or `trajectory_path`"
            )
        return self


class ObservationResult(_Model):
    source_call_id: str | None = None
    content: str | list[ContentPart] | None = None
    subagent_trajectory_ref: list[SubagentTrajectoryRef] | None = None
    extra: JsonObject | None = None


class Observation(_Model):
    results: list[ObservationResult]


class ToolCall(_Model):
    tool_call_id: str
    function_name: str
    arguments: JsonObject
    extra: JsonObject | None = None


_AGENT_ONLY_FIELDS = (
    "model_name",
    "reasoning_effort",
    "reasoning_content",
    "tool_calls",
    "metrics",
)


class Step(_Model):
    step_id: int = Field(ge=1)
    timestamp: str | None = None
    source: Literal["system", "user", "agent"]
    model_name: str | None = None
    reasoning_effort: str | float | None = None
    message: str | list[ContentPart]
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    observation: Observation | None = None
    metrics: Metrics | None = None
    is_copied_context: bool | None = None
    llm_call_count: int | None = Field(default=None, ge=0)
    extra: JsonObject | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(f"Invalid ISO 8601 timestamp: {e}") from e
        return v

    @model_validator(mode="after")
    def validate_agent_only_fields(self) -> "Step":
        if self.source != "agent":
            for name in _AGENT_ONLY_FIELDS:
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"Field '{name}' is only applicable when source is 'agent', "
                        f"but source is '{self.source}'"
                    )
        return self

    @model_validator(mode="after")
    def validate_llm_call_count_zero_fields(self) -> "Step":
        if self.llm_call_count == 0 and self.source == "agent":
            for name in ("metrics", "reasoning_content"):
                if getattr(self, name) is not None:
                    raise ValueError(f"Field '{name}' must be absent when llm_call_count is 0")
        return self


class Trajectory(_Model):
    schema_version: SchemaVersion = "ATIF-v1.8"
    session_id: str | None = None
    trajectory_id: str | None = None
    agent: Agent
    steps: list[Step] = Field(min_length=1)
    notes: str | None = None
    final_metrics: FinalMetrics | None = None
    continued_trajectory_ref: str | None = None
    extra: JsonObject | None = None
    subagent_trajectories: list["Trajectory"] | None = None

    def to_json_dict(self, exclude_none: bool = True) -> JsonObject:
        return self.model_dump(exclude_none=exclude_none, mode="json")

    @model_validator(mode="after")
    def validate_step_ids(self) -> "Trajectory":
        for i, step in enumerate(self.steps):
            if step.step_id != i + 1:
                raise ValueError(
                    f"steps[{i}].step_id: expected {i + 1} (sequential from 1), got {step.step_id}"
                )
        return self

    @model_validator(mode="after")
    def validate_embedded_subagent_trajectory_ids(self) -> "Trajectory":
        if not self.subagent_trajectories:
            return self
        seen: set[str] = set()
        for i, sub in enumerate(self.subagent_trajectories):
            if sub.trajectory_id is None:
                raise ValueError(f"subagent_trajectories[{i}].trajectory_id is required")
            if sub.trajectory_id in seen:
                raise ValueError(
                    f"subagent_trajectories[{i}].trajectory_id {sub.trajectory_id!r} is not unique"
                )
            seen.add(sub.trajectory_id)
        return self

    @model_validator(mode="after")
    def validate_tool_call_references(self) -> "Trajectory":
        for step in self.steps:
            if step.observation is None:
                continue
            ids = {tc.tool_call_id for tc in step.tool_calls or []}
            for result in step.observation.results:
                if result.source_call_id is not None and result.source_call_id not in ids:
                    raise ValueError(
                        f"Observation result references source_call_id "
                        f"'{result.source_call_id}' which is not found in "
                        f"step {step.step_id}'s tool_calls"
                    )
        return self
