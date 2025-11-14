import pprint
from alibabacloud_ecs20140526.models import (
    DescribeImagesRequest,
    DescribeInstanceTypesRequest,
)
import structlog
from rich.pretty import pprint

from .engine import Engine
from .settings import Settings
from .aliyun import *
from .spot_servers import SpotServerCreator, SpotServerSelector, batch_describe_price
from .types import SingleKeyDict, get_tag_from_single_key_dict

_log = structlog.get_logger(__name__)


def main():
    settings = Settings.new()
    engine = Engine(settings=settings)

    server_selected = engine.select_instance_type()
    engine.relaunch_dev_server(server_selected=server_selected)


if __name__ == "__main__":
    main()
