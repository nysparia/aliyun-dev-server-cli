"""Debug utilities for the Aliyun Dev Server CLI."""

from alibabacloud_ecs20140526.models import (
    DescribeInstanceTypeFamiliesRequest,
    DescribeInstanceTypesRequest,
)
import structlog
from rich.pretty import pprint
from typing import List, Optional

from .aliyun import Client

_log = structlog.get_logger(__name__)


def describe_instance_type_families(client: Client, region_id: str):
    """Describe instance type families available in the specified region.
    
    Args:
        client: Alibaba Cloud ECS client instance
        region_id: Region ID to query instance type families for
    """
    instance_families = client.describe_instance_type_families(
        DescribeInstanceTypeFamiliesRequest(region_id=region_id)
    )
    pprint(instance_families.body.to_map())


def describe_instance_types(client: Client, instance_types_args: Optional[List[str]]):
    """Describe instance types, optionally filtered by specific instance type IDs.
    
    Args:
        client: Alibaba Cloud ECS client instance
        instance_types_args: Optional list of instance type IDs to filter results
    """
    instance_types = client.describe_instance_types(
        DescribeInstanceTypesRequest(
            instance_types=instance_types_args  # pyright: ignore
        )
    )
    instance_types = instance_types.body.instance_types.instance_type
    pprint(
        [instance_type.instance_type_id for instance_type in instance_types][:10],
        max_depth=2,
    )


def measure_describe_instance_types_time(client: Client, number: int = 1):
    """Measure the execution time of describe_instance_types function.
    
    Args:
        client: Alibaba Cloud ECS client instance
        number: Number of times to execute the function for timing
    """
    from timeit import timeit

    time_taken_1 = timeit(
        lambda: describe_instance_types(client, ["ecs.g6.xlarge", "ecs.g6.large"]),
        number=number,
    )
    time_taken_2 = timeit(lambda: describe_instance_types(client, None), number=number)
    _log.debug("time taken:", time_taken_1=time_taken_1, time_taken_2=time_taken_2)