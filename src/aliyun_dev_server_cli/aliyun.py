"""Aliyun client wrappers for Resource Manager and VPC services.

This module provides simplified interfaces for interacting with Aliyun's Resource Manager
and VPC services, specifically tailored for the dev server CLI application.
"""

from itertools import groupby
import logging
from typing import List, Literal
import typing
from alibabacloud_ecs20140526.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_ecs20140526.models import (
    DescribeDisksRequest,
    DescribeSecurityGroupsRequest,
    DescribeSecurityGroupsRequestTag,
    DescribeSnapshotsRequest,
    DescribeSnapshotsRequestTag,
    DescribeDisksResponseBodyDisksDisk as DiskDescription,
    ModifyDiskAttributeRequest,
    TagResourcesRequest,
    TagResourcesRequestTag,
)
from alibabacloud_tea_openapi.exceptions import ClientException
from alibabacloud_resourcemanager20200331.client import (
    Client as AliyunResourceManagerClient,
)
from alibabacloud_resourcemanager20200331.models import ListResourceGroupsRequest
from alibabacloud_vpc20160428.client import Client as AliyunVPCClient
from alibabacloud_vpc20160428.models import (
    DescribeVpcsRequest,
    DescribeVpcsRequestTag,
    DescribeVSwitchesRequest,
    DescribeVSwitchesResponseBodyVSwitchesVSwitch as VSwitchInfo,
    DescribeVSwitchesResponseBodyVSwitchesVSwitchTagsTag as VSwitchTag,
)
from rich import region
import structlog

from .types import DiskType, SingleKeyDict, get_tag_from_single_key_dict

_ = Client
_ = ClientException


class ResourceManagerClient:
    """Client for managing Aliyun Resource Manager operations.

    This client simplifies interactions with Aliyun's Resource Manager service,
    particularly for fetching resource group information by name.
    """

    def __init__(
        self, access_key_id: str, access_key_secret: str, resource_group_name: str
    ):
        """Initialize the ResourceManagerClient.

        Args:
            access_key_id: Aliyun access key ID for authentication
            access_key_secret: Aliyun access key secret for authentication
            resource_group_name: Name of the resource group to manage
        """
        self.client = AliyunResourceManagerClient(
            Config(access_key_id=access_key_id, access_key_secret=access_key_secret)
        )
        self._resource_group_id = self._fetch_resource_group_id(resource_group_name)

    def resource_group_id(self) -> str:
        """Get the resource group ID.

        Returns:
            The ID of the resource group
        """
        return self._resource_group_id

    def _fetch_resource_group_id(self, resource_group_name: str) -> str:
        """Fetch the resource group ID by name.

        Args:
            resource_group_name: Name of the resource group to fetch

        Returns:
            The ID of the resource group

        Raises:
            ValueError: If no resource group or multiple resource groups are found,
                or if the resource group status is not OK
        """
        # Query Aliyun Resource Manager for resource groups matching the provided name
        resource_groups = self.client.list_resource_groups(
            ListResourceGroupsRequest(name=resource_group_name)
        )
        resource_groups = resource_groups.body.resource_groups.resource_group

        # Validate that exactly one resource group was found
        if len(resource_groups) > 1:
            raise ValueError(
                f'Multiple resources matching the name "{resource_group_name}" were found'
            )
        elif len(resource_groups) == 0:
            raise ValueError(f'Resource group "{resource_group_name}" cannot be found')

        resource_group = resource_groups[0]

        # Verify that the resource group is in an OK status
        if resource_group.status != "OK":
            raise ValueError(
                f'The status of resource group "{resource_group_name}" is {resource_group.status}, but OK is expected'
            )

        id = resource_group.id
        if not isinstance(id, str):
            raise ValueError("Retrieved non-string resource group ID")

        return id


class VPCClient:
    """Client for managing Aliyun VPC operations.

    This client simplifies interactions with Aliyun's VPC service,
    particularly for finding suitable VPCs and VSwitches based on tags and resource groups.
    """

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        region_id: str,
        resource_group_id: str,
        # use this tag to filter suitable VPC and security group but not used in VSwitch filtering
        included_automation_tag: dict[str, str],
        # use this tag to filter suitable VSwitch under the target VPC but not used in VPC filtering and security group
        excluded_automation_tag: dict[str, str],
    ) -> None:
        """Initialize the VPCClient.

        Args:
            access_key_id: Aliyun access key ID for authentication
            access_key_secret: Aliyun access key secret for authentication
            region_id: Region ID where the VPC is located
            resource_group_id: ID of the resource group to filter VPCs
            included_automation_tag: Tag to filter suitable VPCs (not used for VSwitch filtering)
            excluded_automation_tag: Tag to filter suitable VSwitches under the target VPC (not used for VPC filtering)
        """
        config = Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=region_id,
        )
        self.client = AliyunVPCClient(config=config)
        self.ecs_client = Client(config=config)
        self.region_id = region_id
        self.resource_group_id = resource_group_id
        self.included_automation_tag = VPCClient._dict_tags_to_request_tags(
            included_automation_tag
        )
        self.excluded_automation_tag = excluded_automation_tag
        self._original_included_automation_tag = included_automation_tag
        self.logger = structlog.get_logger()

    @staticmethod
    def _dict_tags_to_request_tags(
        tags: dict[str, str],
    ) -> List[DescribeVpcsRequestTag]:
        """Convert a dictionary of tags to Aliyun request tags.

        Args:
            tags: Dictionary of tags to convert

        Returns:
            List of Aliyun DescribeVpcsRequestTag objects
        """
        return [
            DescribeVpcsRequestTag(key=key, value=value)
            for (key, value) in tags.items()
        ]

    @staticmethod
    def _dict_tags_to_security_groups_request_tags(
        tags: dict[str, str],
    ) -> List[DescribeSecurityGroupsRequestTag]:
        """Convert a dictionary of tags to Aliyun security group request tags.

        Args:
            tags: Dictionary of tags to convert

        Returns:
            List of Aliyun DescribeSecurityGroupsRequestTag objects
        """
        return [
            DescribeSecurityGroupsRequestTag(key=key, value=value)
            for (key, value) in tags.items()
        ]

    def describe_matched_vpc(self):
        """Describe VPCs that match the specified criteria.

        Returns:
            The matched VPC information

        Raises:
            ValueError: If no matching VPCs are found
        """
        # Query Aliyun VPC service for VPCs matching our criteria
        vpcs = self.client.describe_vpcs(
            DescribeVpcsRequest(
                region_id=self.region_id,
                tag=self.included_automation_tag,
                resource_group_id=self.resource_group_id,
            )
        )
        vpcs = vpcs.body.vpcs.vpc

        # Handle cases where we find zero or multiple matching VPCs
        if len(vpcs) == 0:
            raise ValueError(
                f"VPCs matching resource group ID {self.resource_group_id} and tag {self._original_included_automation_tag} "
                + f"under region ID {self.region_id} are not found"
            )
        elif len(vpcs) > 1:
            self.logger.warning(
                "Multiple VPCs (%i) matching the requirements were found. Using the most recently created one.",
                len(vpcs),
            )
            # Sort by creation time to select the most recent one
            vpcs.sort(key=lambda x: str(x.creation_time), reverse=True)

        # Return the first (most recent) VPC from our sorted list
        vpc = vpcs[0]
        return vpc

    def describe_matched_vswitches(self, vpc_id: str) -> List[VSwitchInfo]:
        """Describe VSwitches that match the specified VPC.

        Args:
            vpc_id: The ID of the VPC to find VSwitches for

        Returns:
            List of matched VSwitch information
        """
        # Query Aliyun VPC service for VSwitches in the matched VPC
        result = self.client.describe_vswitches(DescribeVSwitchesRequest(vpc_id=vpc_id))
        result = result.body.v_switches.v_switch

        self.logger.debug(
            "describe_matched_vswitches fetched %i vswitches.", len(result)
        )

        return result

    def get_suitable_vswitch(self, zone_id: str, vpc_id: str) -> VSwitchInfo:
        """Get a suitable VSwitch for the specified zone.

        Args:
            zone_id: Zone ID to find a suitable VSwitch for

        Returns:
            Suitable VSwitch information

        Raises:
            ValueError: If no suitable VSwitch is found for the zone
        """
        # Get all VSwitches that match our VPC
        vswitches = self.describe_matched_vswitches(vpc_id)

        # Sort and group VSwitches by zone ID
        vswitches.sort(key=lambda x: typing.cast(str, x.zone_id))
        grouped_vswitches = groupby(
            vswitches, key=lambda x: typing.cast(str, x.zone_id)
        )
        grouped_vswitches = {key: list(g) for key, g in grouped_vswitches}

        # Filter to only VSwitches in the requested zone
        suitable_vswitches = grouped_vswitches[zone_id]

        # Further filter out VSwitches that match our exclusion tags
        suitable_vswitches = [
            it
            for it in suitable_vswitches
            if not self._shall_exclude(it.tags.tag if it.tags else [])
        ]

        # Handle cases where we find zero or multiple suitable VSwitches
        if len(suitable_vswitches) == 0:
            raise ValueError(
                f"No VSwitch matching the fetched VPC under zone ID {zone_id} was found"
            )
        elif len(suitable_vswitches) > 1:
            self.logger.warning(
                "Multiple VSwitches (%i) matching the requirements were found. Using the most recently created one.",
                len(suitable_vswitches),
            )
            # Sort by creation time to select the most recent one
            suitable_vswitches.sort(key=lambda x: str(x.creation_time), reverse=True)

        # Return the first (most recent) suitable VSwitch
        return suitable_vswitches[0]

    def _shall_exclude(self, tags_from_item: List[VSwitchTag]) -> bool:
        """Determine if an item should be excluded based on its tags.

        Args:
            tags_from_item: List of tags from the item to check

        Returns:
            True if the item should be excluded, False otherwise
        """
        # Extract the exclusion tag key and value we're looking for
        excluded_tag, excluded_tag_value = get_tag_from_single_key_dict(
            self.excluded_automation_tag
        )

        # Check if any of the item's tags match our exclusion criteria
        return any(
            tag.key == excluded_tag and tag.value == excluded_tag_value
            for tag in tags_from_item
        )

    def describe_security_group(self, vpc_id: str):
        """Describe security groups that match the specified VPC and tags.

        Args:
            vpc_id: The ID of the VPC to find security groups for

        Returns:
            The matched security group information

        Raises:
            ValueError: If no matching security groups are found
        """
        security_groups = self.ecs_client.describe_security_groups(
            DescribeSecurityGroupsRequest(
                region_id=self.region_id,
                vpc_id=vpc_id,
                tag=VPCClient._dict_tags_to_security_groups_request_tags(
                    self._original_included_automation_tag
                ),
            )
        )
        security_groups = security_groups.body.security_groups.security_group

        self.logger.debug(
            "describe_security_group fetched %i security groups.", len(security_groups)
        )

        # Handle cases where we find zero or multiple matching security groups
        if len(security_groups) == 0:
            raise ValueError(
                f"Security groups matching tag {self._original_included_automation_tag} "
                + f"under VPC ID {vpc_id} and region ID {self.region_id} are not found"
            )
        elif len(security_groups) > 1:
            self.logger.warning(
                "Multiple security groups (%i) matching the requirements were found. Using the most recently created one.",
                len(security_groups),
            )
            # Sort by creation time to select the most recent one
            security_groups.sort(key=lambda x: str(x.creation_time), reverse=True)

        # Return the first (most recent) security group from our sorted list
        security_group = security_groups[0]
        return security_group


class SnapshotClient:
    def __init__(
        self,
        client: Client,
        region_id: str,
        resource_group_id: str,
        included_automation_tag: SingleKeyDict,
        instance_identifier_tag: SingleKeyDict,
        data_disk_identifier_tag: SingleKeyDict,
    ):
        self.client = client
        self.region_id = region_id
        self.resource_group_id = resource_group_id
        self.included_automation_tag = included_automation_tag
        self.instance_identifier_tag = instance_identifier_tag
        self.data_disk_identifier_tag = data_disk_identifier_tag

        automation_tag = self._dict_to_request_tag(self.included_automation_tag)
        instance_identifier = self._dict_to_request_tag(self.instance_identifier_tag)
        data_disk_identifier = self._dict_to_request_tag(self.data_disk_identifier_tag)

        self.tags = [automation_tag, instance_identifier, data_disk_identifier]
        self._original_tags = [
            self.included_automation_tag,
            self.instance_identifier_tag,
            self.data_disk_identifier_tag,
        ]

    def describe_matched_snapshots(self, source_disk_type: DiskType = "data"):
        snapshots = self.client.describe_snapshots(
            DescribeSnapshotsRequest(
                region_id=self.region_id,
                resource_group_id=self.resource_group_id,
                source_disk_type=source_disk_type,
                tag=self.tags,
            )
        )
        snapshots = snapshots.body.snapshots.snapshot
        return snapshots

    @staticmethod
    def _dict_to_request_tag(tag: SingleKeyDict) -> DescribeSnapshotsRequestTag:
        tag_key, tag_value = get_tag_from_single_key_dict(tag)
        return DescribeSnapshotsRequestTag(key=tag_key, value=tag_value)

    def describe_latest_matched_snapshot(self, source_disk_type: DiskType = "data"):
        snapshots = self.describe_matched_snapshots(source_disk_type)
        if len(snapshots) == 0:
            raise ValueError(
                f"No snapshots matching tag {self._original_tags} "
                + f"with source disk type '{source_disk_type}' "
                + f"under region ID {self.region_id} and resource group ID {self.resource_group_id} are found"
            )
        elif len(snapshots) > 1:
            logger = structlog.get_logger()
            logger.info(
                "Multiple snapshots (%i) matching the requirements were found. Using the most recently created one.",
                len(snapshots),
            )
        snapshots.sort(key=lambda x: str(x.creation_time), reverse=True)
        return snapshots[0]


class BlockStorageClient:
    def __init__(self, client: Client, region_id: str) -> None:
        self.client = client
        self.region_id = region_id
        self.logger = structlog.get_logger()

    def describe_disks(self, ecs_instance_id: str) -> List[DiskDescription]:
        disks = self.client.describe_disks(
            DescribeDisksRequest(region_id=self.region_id, instance_id=ecs_instance_id)
        )
        disks = disks.body.disks.disk
        return disks

    @staticmethod
    def filter_disk_by_disk_type(disks: List[DiskDescription], type: DiskType):
        return [disk for disk in disks if disk.type == type]

    def toggle_bursting(self, disks: List[DiskDescription], enabled: bool):
        """Toggle bursting mode for supported disks.

        Only cloud-auto disks (auto-PL) support bursting mode. Other disk types will be ignored.

        Args:
            disks: List of disk descriptions to potentially modify
            enabled: Whether to enable or disable bursting mode

        Returns:
            The number of disks for which bursting mode was modified
        """
        # Filter to only cloud_auto disks as they are the only ones supporting bursting
        disk_ids = [disk.disk_id for disk in disks if disk.category == "cloud_auto"]
        disk_ids = typing.cast(List[str], disk_ids)
        self.client.modify_disk_attribute(
            ModifyDiskAttributeRequest(disk_ids=disk_ids, bursting_enabled=enabled)
        )

        self.logger.debug(
            "toggle bursting_enabled to %s for %i disk(s).",
            enabled,
            len(disk_ids),
            disk_ids=disk_ids,
        )

        return len(disk_ids)

    def tag_data_disks(
        self, disks: List[DiskDescription], data_disk_identifier_tag: SingleKeyDict
    ):
        """Tag data disks with the specified identifier tag for future identification.

        Filters the provided disks to only include data disks, then tags the specified
        identifier tag to these disks.

        Args:
            disks: List of disk descriptions to potentially tag
            data_disk_identifier_tag: The tag to apply to data disks for identification

        Returns:
            The number of data disks that were tagged
        """
        key, value = get_tag_from_single_key_dict(data_disk_identifier_tag)
        data_disks = self.filter_disk_by_disk_type(disks=disks, type="data")
        data_disk_ids = [disk.disk_id for disk in data_disks]
        data_disk_ids = typing.cast(List[str], data_disk_ids)
        self.client.tag_resources(
            TagResourcesRequest(
                region_id=self.region_id,
                resource_type="disk",
                resource_id=data_disk_ids,
                tag=[TagResourcesRequestTag(key=key, value=value)],
            )
        )

        self.logger.debug(
            "tag %i data disk(s).",
            len(data_disk_ids),
            data_disk_ids=data_disk_ids,
            tag=data_disk_identifier_tag,
        )

        return len(data_disk_ids)


if __name__ == "__main__":
    from dotenv import load_dotenv
    import os
    from .settings import Settings

    load_dotenv()

    settings = Settings.new()
    client = settings.get_aliyun_client()
    block_storage_client = BlockStorageClient(client, settings.region_id)

    # Requires an instance with exactly one data disk.
    # Both system disk and data disk must use cloud_auto storage category.
    ecs_instance_id = os.getenv("ecs_instance_id")

    assert isinstance(ecs_instance_id, str)

    disks = block_storage_client.describe_disks(ecs_instance_id=ecs_instance_id)
    data_disks = block_storage_client.filter_disk_by_disk_type(disks, "data")

    assert len(data_disks) == 1 and data_disks[0].type == "data"

    block_storage_client.toggle_bursting(disks, True)
    num_toggled = block_storage_client.toggle_bursting(disks, False)

    assert num_toggled == 2

    num_tagged = block_storage_client.tag_data_disks(
        disks=disks, data_disk_identifier_tag={"nysparis:test:tag1": "true"}
    )

    assert num_tagged == 1
