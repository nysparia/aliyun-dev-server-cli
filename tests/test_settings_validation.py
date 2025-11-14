"""Test script to verify that the single key dict validation works correctly."""

import pytest
from aliyun_dev_server_cli.settings import DevServerCreationSettings


def test_valid_single_key_dict():
    """Test that a valid single key dict passes validation."""
    settings = DevServerCreationSettings(
        image_name_pattern="test-pattern",
        included_automation_tag={"key1": "value1"},
        excluded_automation_tag={"key2": "value2"}
    )
    assert settings.included_automation_tag == {"key1": "value1"}
    assert settings.excluded_automation_tag == {"key2": "value2"}


def test_invalid_empty_dict():
    """Test that an empty dict fails validation."""
    with pytest.raises(ValueError, match="Dictionary must contain exactly one key-value pair"):
        DevServerCreationSettings(
            image_name_pattern="test-pattern",
            included_automation_tag={},
            excluded_automation_tag={"key": "value"}
        )


def test_invalid_multiple_keys_dict():
    """Test that a dict with multiple keys fails validation."""
    with pytest.raises(ValueError, match="Dictionary must contain exactly one key-value pair"):
        DevServerCreationSettings(
            image_name_pattern="test-pattern",
            included_automation_tag={"key1": "value1", "key2": "value2"},
            excluded_automation_tag={"key": "value"}
        )


def test_default_values():
    """Test that default values are set correctly."""
    settings = DevServerCreationSettings(
        image_name_pattern="test-pattern"
    )
    assert settings.included_automation_tag == {"nysparis:automation-usage": "dev"}
    assert settings.excluded_automation_tag == {"nysparis:automation-usage": "none"}