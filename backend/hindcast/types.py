"""Shared JSON types. Use these instead of `Any` for free-form JSON (ATIF `extra`, job params)."""

from pydantic import JsonValue

JsonObject = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonValue"]
