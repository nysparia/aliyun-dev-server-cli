import pathlib
import re
from typing import Annotated, List, Optional, Tuple, override
from pydantic import (
    AfterValidator,
    BaseModel,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .aliyun import Config, Client

__home_dir = pathlib.Path.home()
_config_file = __home_dir / ".config" / "aliyun-dev-server-cli.config.toml"
__local_config_file = pathlib.Path("config.toml")
_config_files = [_config_file, __local_config_file]


def validate_cpu_range(v: Tuple[int, int]):
    if v[0] > v[1]:
        raise ValueError(f"cpu count range must be in ascending order: {v}")
    return v


def validate_memory_range(v: Tuple[float, float]):
    if v[0] > v[1]:
        raise ValueError(f"memory GiB range must be in ascending order: {v}")
    return v


def validate_single_key_dict(v: dict[str, str]) -> dict[str, str]:
    """Validate that a dictionary contains exactly one key-value pair."""
    if len(v) != 1:
        raise ValueError(f"Dictionary must contain exactly one key-value pair, got {len(v)} keys: {list(v.keys())}")
    return v


SingleKeyDict = Annotated[dict[str, str], AfterValidator(validate_single_key_dict)]


CPUCountRange = Annotated[
    Tuple[NonNegativeInt, NonNegativeInt], AfterValidator(validate_cpu_range)
]
MemoryGiBRange = Annotated[
    Tuple[NonNegativeFloat, NonNegativeFloat], AfterValidator(validate_memory_range)
]


class DevServerCreationSettings(BaseModel):
    image_name_pattern: str
    cpu_count_range: CPUCountRange = (16, 32)
    memory_size_range: MemoryGiBRange = (16, 32)
    # convenient instance type checklist to accelerate the price fetching
    instance_types_checklist: Optional[List[str]] = None
    resource_group_name: str = "dev-resource-group"
    included_automation_tag: SingleKeyDict = {
        "nysparis:nysparis:automation-usage": "dev"
    }
    excluded_automation_tag: SingleKeyDict = {
        "nysparis:nysparis:automation-usage": "none"
    }


class SpotInstanceCreationSettings(BaseModel):
    dev_server: DevServerCreationSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", cli_parse_args=True)

    access_key_id: str
    access_key_secret: SecretStr
    region_id: str = "cn-hangzhou"

    spot_instance_creation: SpotInstanceCreationSettings

    def get_aliyun_client(self) -> Client:
        config = Config(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret.get_secret_value(),
            region_id=self.region_id,
        )
        return Client(config)

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:

        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls, _config_files),
        )

    @staticmethod
    def ensure_config_exist():
        config_file = _config_file
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.touch(exist_ok=True)

    @staticmethod
    def new():
        return Settings()  # pyright: ignore
