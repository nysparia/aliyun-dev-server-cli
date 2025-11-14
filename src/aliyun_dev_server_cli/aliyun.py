from itertools import groupby
import logging
from typing import List
import typing
from alibabacloud_ecs20140526.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_ecs20140526.models import DescribeSnapshotsRequest
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
import structlog

_ = Client
_ = ClientException


class ResourceManagerClient:
    def __init__(
        self, access_key_id: str, access_key_secret: str, resource_group_name: str
    ):
        self.client = AliyunResourceManagerClient(
            Config(access_key_id=access_key_id, access_key_secret=access_key_secret)
        )
        self._resource_group_id = self._fetch_resource_group_id(resource_group_name)

    def resource_group_id(self) -> str:
        return self._resource_group_id

    def _fetch_resource_group_id(self, resource_group_name: str) -> str:
        resource_groups = self.client.list_resource_groups(
            ListResourceGroupsRequest(name=resource_group_name)
        )
        resource_groups = resource_groups.body.resource_groups.resource_group

        if len(resource_groups) > 1:
            raise ValueError(
                f'this shouldn\'t happened, multiple resources matching the name "{resource_group_name}"  were found'
            )
        elif len(resource_groups) == 0:
            raise ValueError(
                f'given resource group "{resource_group_name}" can\'t be found'
            )

        resource_group = resource_groups[0]

        if resource_group.status != "OK":
            raise ValueError(
                f'the status of given resource group "{resource_group_name}" is {resource_group.status}, but OK is expected'
            )

        id = resource_group.id
        if not isinstance(id, str):
            raise ValueError(
                f"this shouldn't happened, retrieved non-str resource group id"
            )

        return id


class VPCClient:
    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        region_id: str,
        resource_group_id: str,
        # use this tag to filter suitable VPC but not used in VSwitch filtering
        included_automation_tag: dict[str, str],
        # use this tag to filter suitable VSwitch under the target VPC but not used in VPC filtering
        excluded_automation_tag: dict[str, str],
    ) -> None:
        self.client = AliyunVPCClient(
            Config(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                region_id=region_id,
            )
        )
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
        return [
            DescribeVpcsRequestTag(key=key, value=value)
            for (key, value) in tags.items()
        ]

    def describe_matched_vpc(self):
        vpcs = self.client.describe_vpcs(
            DescribeVpcsRequest(
                region_id=self.region_id,
                tag=self.included_automation_tag,
                resource_group_id=self.resource_group_id,
            )
        )
        vpcs = vpcs.body.vpcs.vpc

        if len(vpcs) == 0:
            raise ValueError(
                f"vpcs matching resource group id {self.resource_group_id} and tag {self._original_included_automation_tag} "
                + f"under region id {self.region_id} are not found"
            )
        elif len(vpcs) > 1:
            self.logger.warning(
                "Multiple VPCs (%i) matching the requirements were found. Using the most recently created one.",
                len(vpcs),
            )
            vpcs.sort(key=lambda x: str(x.creation_time), reverse=True)

        vpc = vpcs[0]
        return vpc

    def describe_matched_vswitches(self) -> List[VSwitchInfo]:
        vpc_info = self.describe_matched_vpc()
        vpc_id = vpc_info.vpc_id
        if not isinstance(vpc_id, str):
            raise ValueError(
                f"this shouldn't happened, retrieved non-str vpc-id: {vpc_id}"
            )
        result = self.client.describe_vswitches(DescribeVSwitchesRequest(vpc_id=vpc_id))
        result = result.body.v_switches.v_switch

        self.logger.debug("fetched vswitches:", vswitches=result)

        return result

    def get_suitable_vswitch(self, zone_id: str) -> VSwitchInfo:
        vswitches = self.describe_matched_vswitches()
        vswitches.sort(key=lambda x: typing.cast(str, x.zone_id))
        grouped_vswitches = groupby(
            vswitches, key=lambda x: typing.cast(str, x.zone_id)
        )
        grouped_vswitches = {key: list(g) for key, g in grouped_vswitches}
        suitable_vswitches = grouped_vswitches[zone_id]
        suitable_vswitches = [
            it for it in suitable_vswitches if not self._shall_exclude(it.tags.tag)
        ]

        if len(suitable_vswitches) == 0:
            raise ValueError(
                f"no vswitch matching fetched vpc under zone id {zone_id} was found"
            )
        elif len(suitable_vswitches) > 1:
            self.logger.warning(
                "Multiple VSwitches (%i) matching the requirements were found. Using the most recently created one.",
                len(suitable_vswitches),
            )
            suitable_vswitches.sort(key=lambda x: str(x.creation_time), reverse=True)

        return suitable_vswitches[0]

    def _shall_exclude(self, tags_from_item: List[VSwitchTag]):
        excluded_tag, excluded_tag_value = next(
            iter(self.excluded_automation_tag.items())
        )
        return any(
            tag.key == excluded_tag and tag.value == excluded_tag_value
            for tag in tags_from_item
        )
