"""Common types and utilities for the aliyun dev server CLI.

This module contains common type definitions and utility functions
that are used across different modules to avoid circular imports.
"""

from typing import Annotated, Dict, Literal, Tuple
from pydantic import AfterValidator


def validate_single_key_dict(v: dict[str, str]) -> dict[str, str]:
    """Validate that a dictionary contains exactly one key-value pair."""
    if len(v) != 1:
        raise ValueError(
            f"Dictionary must contain exactly one key-value pair, got {len(v)} keys: {list(v.keys())}"
        )
    return v


SingleKeyDict = Annotated[dict[str, str], AfterValidator(validate_single_key_dict)]


def get_tag_from_single_key_dict(v: SingleKeyDict) -> Tuple[str, str]:
    """Extract the single key-value pair from a SingleKeyDict."""
    return next(iter(v.items()))

DiskType = Literal["system", "data"]