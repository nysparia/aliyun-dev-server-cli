from alibabacloud_ecs20140526.models import (
    DescribeImagesRequest,
    DescribeInstanceTypesRequest,
)
import structlog

from .settings import Settings
from .aliyun import *
from .servers import SpotServerSelector, batch_describe_price

_log = structlog.get_logger(__name__)


def main():
    """Main entry point for the Aliyun Dev Server CLI application."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    Settings.ensure_config_exist()
    settings = Settings.new()
    region_id = settings.region_id
    dev_server_creation_settings = settings.spot_instance_creation.dev_server
    _log.debug("current settings:", extra=settings)

    client = settings.get_aliyun_client()

    # debug.describe_instance_type_families(client, region_id)

    # debug.measure_describe_instance_types_time(client)

    # Retrieve instance types matching the configured cpu and memory range requirements
    server_settings = dev_server_creation_settings
    instance_types = client.describe_instance_types(
        DescribeInstanceTypesRequest(
            minimum_cpu_core_count=server_settings.cpu_count_range[0],
            maximum_cpu_core_count=server_settings.cpu_count_range[1],
            minimum_memory_size=server_settings.memory_size_range[0],
            maximum_memory_size=server_settings.memory_size_range[1],
        )
    )
    instance_types = instance_types.body.instance_types.instance_type
    _log.debug(
        "%i instance types satisfied the range requirements: ",
        len(instance_types),
        instance_type_ids=[it.instance_type_id for it in instance_types],
    )

    prices = batch_describe_price(
        client,
        region_id,
        instance_types,
    )

    # Select target instance type to create
    spot_server_selector = SpotServerSelector()
    spot_server_selector.display_servers(prices)
    server_selected = spot_server_selector.select_server(prices)
    server_selected = prices[server_selected]
    _log.debug(
        "selected server: %s, %s",
        server_selected.instance_type.instance_type_id,
        server_selected.zone_id,
    )

    # Retrieve images matching the configured pattern
    images = client.describe_images(
        DescribeImagesRequest(
            region_id=region_id,
            image_name=dev_server_creation_settings.image_name_pattern,
        )
    )
    images = images.body.images.image
    image = images[0]
    _log.debug(
        "found %i images, use the first (newest).",
        len(images),
        images=[image.image_name for image in images],
    )

    access_key_id = settings.access_key_id
    access_key_secret = settings.access_key_secret
    resource_group_name = dev_server_creation_settings.resource_group_name
    resource_manager_client = ResourceManagerClient(
        access_key_id, access_key_secret.get_secret_value(), resource_group_name
    )
    resource_group_id = resource_manager_client.resource_group_id()
    # included_automation_tag = 


if __name__ == "__main__":
    main()
