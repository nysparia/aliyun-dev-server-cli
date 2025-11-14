import pprint
from alibabacloud_ecs20140526.models import (
    DescribeImagesRequest,
    DescribeInstanceTypesRequest,
)
import structlog
from rich.pretty import pprint

from .settings import Settings
from .aliyun import *
from .spot_servers import SpotServerCreator, SpotServerSelector, batch_describe_price
from .types import SingleKeyDict, get_tag_from_single_key_dict

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

    # Retrieve the vswitch matching the configured pattern
    access_key_id = settings.access_key_id
    access_key_secret = settings.access_key_secret
    resource_group_name = dev_server_creation_settings.resource_group_name
    resource_manager_client = ResourceManagerClient(
        access_key_id, access_key_secret.get_secret_value(), resource_group_name
    )
    resource_group_id = resource_manager_client.resource_group_id()

    included_automation_tag = dev_server_creation_settings.included_automation_tag
    excluded_automation_tag = dev_server_creation_settings.excluded_automation_tag
    vpc_client = VPCClient(
        access_key_id,
        access_key_secret.get_secret_value(),
        region_id,
        resource_group_id,
        included_automation_tag,
        excluded_automation_tag,
    )

    vpc = vpc_client.describe_matched_vpc()
    vpc_id = typing.cast(str, vpc.vpc_id)
    vswitch = vpc_client.get_suitable_vswitch(server_selected.zone_id, vpc_id)
    security_group = vpc_client.describe_security_group(vpc_id)

    # Retrieve the image matching the configured pattern
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

    # Retrieve the matched data disk snapshot
    instance_identifier_tag = dev_server_creation_settings.instance_identifier_tag()
    data_disk_identifier_tag = dev_server_creation_settings.data_disk_identifier_tag
    snapshot_client = SnapshotClient(
        client,
        region_id=region_id,
        resource_group_id=resource_group_id,
        included_automation_tag=included_automation_tag,
        instance_identifier_tag=instance_identifier_tag,
        data_disk_identifier_tag=data_disk_identifier_tag,
    )

    snapshot = snapshot_client.describe_latest_matched_snapshot("data")

    spot_server_creator = SpotServerCreator(
        client=client,
        region_id=region_id,
        resource_group_id=resource_group_id,
        included_automation_tag=included_automation_tag,
        instance_identifier_tag=instance_identifier_tag,
    )

    vswitch_id = typing.cast(str, vswitch.v_switch_id)
    image_id = typing.cast(str, image.image_id)
    snapshot_id = typing.cast(str, snapshot.snapshot_id)
    security_group_id = typing.cast(str, security_group.security_group_id)

    _log.debug("creating instance...")

    created_instance_ids = spot_server_creator.create_server(
        vswitch_id=vswitch_id,
        instance_type_id=server_selected.instance_type_id,
        image_id=image_id,
        system_disk_size=20,
        system_disk_category=server_selected.disk_category,
        data_disk_size=20,
        data_disk_category=server_selected.disk_category,
        data_disk_snapshot_id=snapshot_id,
        security_group_id=security_group_id,
        instance_name=dev_server_creation_settings.instance_automation_identifier,
        description="created by nysparis aliyun dev server cli",
        # dry_run=True,
    )

    assert len(created_instance_ids) == 1

    block_storage_client = BlockStorageClient(client, region_id)
    created_disks = block_storage_client.describe_disks(created_instance_ids[0])

    assert len(created_disks) == 2
    data_disks = block_storage_client.filter_disk_by_disk_type(created_disks, "data")
    assert len(data_disks) == 1

    # enable performance bursting for created disks if suitable
    block_storage_client.toggle_bursting(created_disks, True)

    # Tag the data disk using the data disk identifier for future identification
    block_storage_client.tag_data_disks(created_disks, data_disk_identifier_tag)


if __name__ == "__main__":
    main()
