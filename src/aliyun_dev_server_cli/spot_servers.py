import asyncio
from concurrent.futures import ThreadPoolExecutor
import select
from typing import Annotated, List
import typing
import inquirer
import inquirer.errors
from pydantic import BaseModel, Field
from alibabacloud_ecs20140526.models import (
    DescribeAvailableResourceResponseBodyAvailableZonesAvailableZone,
    DescribeAvailableResourceRequest,
    DescribePriceRequestSystemDisk,
    DescribePriceRequest,
    DescribePriceResponse,
    DescribePriceResponseBodyPriceInfoPrice,
    DescribeInstanceTypesResponseBodyInstanceTypesInstanceType as InstanceTypeInfo,
    RunInstancesRequest,
    RunInstancesRequestDataDisk,
    RunInstancesRequestSystemDisk,
    RunInstancesRequestTag,
)
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.pretty import pprint
from rich.rule import Rule
from rich.text import Text
import structlog
from itertools import chain
from rich.style import Style

from .aliyun import Client, ClientException
from .settings import SingleKeyDict, get_tag_from_single_key_dict


_log = structlog.get_logger(__name__)


InstanceTypeID = Annotated[str, Field(description="Instance type ID")]
ZoneID = Annotated[str, Field(description="Zone ID")]


class InstanceTypeZonePrice(BaseModel, arbitrary_types_allowed=True):
    instance_type_id: InstanceTypeID
    zone_id: ZoneID
    price: DescribePriceResponseBodyPriceInfoPrice
    instance_type: InstanceTypeInfo


def batch_describe_price(
    client: Client, region_id: str, instance_types: List[InstanceTypeInfo]
) -> List[InstanceTypeZonePrice]:
    zones = client.describe_available_resource(
        DescribeAvailableResourceRequest(
            region_id=region_id,
            destination_resource="InstanceType",
            spot_strategy="SpotAsPriceGo",
        )
    ).body.available_zones.available_zone

    def get_instance_types_available_in_zone(
        zone: DescribeAvailableResourceResponseBodyAvailableZonesAvailableZone,
    ):
        available_instance_types = zone.available_resources.available_resource[
            0
        ].supported_resources.supported_resource
        available_instance_types = [
            it for it in available_instance_types if it.status == "Available"
        ]
        available_instance_types = typing.cast(
            List[str], [it.value for it in available_instance_types]
        )
        return set(available_instance_types)

    instance_type_available_in_zones = [
        (typing.cast(str, zone.zone_id), get_instance_types_available_in_zone(zone))
        for zone in zones
    ]

    instance_type_zone_pairs = [
        [
            (it, zone_id)
            for it in instance_types
            if it.instance_type_id in instance_types_available
        ]
        for (zone_id, instance_types_available) in instance_type_available_in_zones
    ]

    # --- debug ---
    # pprint(instance_type_zone_pairs)
    # -------------

    instance_type_zone_pairs = list(chain.from_iterable(instance_type_zone_pairs))

    # --- debug ---
    # pprint(instance_type_zone_pairs)
    # pprint(len(instance_type_zone_pairs))
    # -------------

    system_disk_args = [
        DescribePriceRequestSystemDisk(category=system_disk_str)
        for system_disk_str in [
            "cloud_auto",
            "cloud_efficiency",
            "cloud_essd",
            "cloud_essd_entry",
            "cloud_ssd",
            "ephemeral_ssd",
        ]
    ]

    def describe_price_in_thread(
        instance_type: InstanceTypeInfo, zone_id: ZoneID
    ) -> InstanceTypeZonePrice | Exception:
        instance_type_id = typing.cast(str, instance_type.instance_type_id)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run():
            async def describe_price_async() -> DescribePriceResponse | Exception:
                _log.debug(
                    "describe_price_async:",
                    zone_id=zone_id,
                    region_id=region_id,
                    instance_type_id=instance_type_id,
                )

                error = None

                for system_disk_arg in system_disk_args:
                    try:
                        result = await client.describe_price_async(
                            DescribePriceRequest(
                                resource_type="Instance",
                                instance_type=instance_type_id,
                                region_id=region_id,
                                zone_id=zone_id,
                                system_disk=system_disk_arg,
                                spot_strategy="SpotAsPriceGo",
                            )
                        )
                        _log.debug(
                            "describe_price_async done:",
                            zone_id=zone_id,
                            region_id=region_id,
                            instance_type_id=instance_type_id,
                            system_disk=system_disk_arg.category,
                        )
                        return result
                    except Exception as err:
                        error = err
                        continue
                return error or Exception("this should not happen")

            result = await describe_price_async()
            if isinstance(result, Exception):
                return result

            price_info = InstanceTypeZonePrice(
                instance_type_id=instance_type_id,
                zone_id=zone_id,
                price=result.body.price_info.price,
                instance_type=instance_type,
            )

            return price_info

        result = loop.run_until_complete(run())
        loop.close()
        return result

    with ThreadPoolExecutor(max_workers=24) as executor:
        futures = [
            executor.submit(describe_price_in_thread, instance_type, zone_id)
            for (instance_type, zone_id) in instance_type_zone_pairs
        ]

        prices = [future.result() for future in futures]

    wrong_system_disk_prices = [
        price
        for price in prices
        if isinstance(price, ClientException)
        and price.data["Code"] == "InvalidSystemDiskCategory.ValueNotSupported"
    ]
    wrong_len = len(wrong_system_disk_prices)
    if wrong_len > 0:
        _log.debug(
            "found %i instance types with unsupported system disk category. Ignored them.",
            wrong_len,
        )

    prices = [price for price in prices if price not in wrong_system_disk_prices]

    exceptions = [price for price in prices if isinstance(price, Exception)]
    wrong_len = len(exceptions)
    if wrong_len > 0:
        _log.error(
            "found %i instance prices with exceptions.",
            wrong_len,
        )
        # raise all exceptions
        if wrong_len == 1:
            raise exceptions[0]
        else:
            # 创建一个包含所有原始异常信息的新异常
            exception_messages = "\n".join(
                [f"{type(e).__name__}: {str(e)}" for e in exceptions]
            )
            raise Exception(
                f"Found {wrong_len} instance prices with exceptions:\n{exception_messages}"
            )

    _log.debug(
        "found %i instance prices.",
        len(prices),
    )

    prices = typing.cast(List[InstanceTypeZonePrice], prices)
    prices.sort(key=lambda p: p.price.trade_price or 0)
    _log.debug(
        "minimum price: %s, maximum price: %s",
        prices[0].price.trade_price,
        prices[-1].price.trade_price,
    )

    # Prices sorted ascending
    return prices


class SpotServerSelector:
    def __init__(self) -> None:
        self.console = Console()

    def select_prompt(self, total: int):
        result = Text(
            f"Total {total} spot server types available, ",
        )
        result.append("select the server you want to create", style="bright_yellow")
        return result

    def print_rule(self):
        self.console.print(Rule(style="green"))

    def display_servers(self, servers: List[InstanceTypeZonePrice]):
        green = Style(color="green")
        purple = Style(color="bright_magenta")
        yellow = Style(color="bright_yellow")

        panels = []
        for i, server in enumerate(servers):
            content = Text(style=green)
            instance_type_id = server.instance_type_id
            instance_category = server.instance_type.instance_category
            cpu_count = server.instance_type.cpu_core_count
            content.append("cpu_count=")
            content.append(str(cpu_count), style=yellow)
            content.append(" ")
            cpu_freq = server.instance_type.cpu_speed_frequency
            content.append("cpu_freq=")
            content.append(str(cpu_freq), style=purple)
            content.append(" ")
            cpu_turbo_freq = server.instance_type.cpu_turbo_frequency
            content.append("cpu_turbo_freq=")
            style = purple
            if cpu_turbo_freq:
                style = yellow
            content.append(str(cpu_turbo_freq), style=style)
            price = server.price.trade_price
            content.append(" ")
            content.append("price=")
            content.append(f"{price:.3f}", style=yellow)

            content.append("\n")

            memory_size = server.instance_type.memory_size
            content.append("memory_size=")
            content.append(str(memory_size), style=yellow)
            arch = server.instance_type.cpu_architecture
            content.append(" ")
            content.append("arch=")
            content.append(str(arch), style=yellow)
            zone_id = server.zone_id
            content.append(" ")
            content.append("zone_id=")
            content.append(str(zone_id), style=purple)

            panel = Panel(
                content,
                title=f"({i}) {instance_type_id} ({instance_category})",
                title_align="left",
            )
            panels.append(panel)

        self.print_rule()
        self.console.print(Columns(panels, equal=True, expand=True))
        # self.console.print(self.select_prompt(len(servers)))

    def select_server(self, servers: List[InstanceTypeZonePrice]):
        def validate_selection(_ans, v: str):
            try:
                value = int(v)
            except ValueError:
                raise inquirer.errors.ValidationError(
                    "", reason="input must be an integer"
                )
            if value <= -1 or value >= len(servers):
                raise inquirer.errors.ValidationError(
                    "", reason=f"input must be between 0 and {len(servers) - 1}"
                )
            return True

        self.print_rule()

        message = str(self.select_prompt(len(servers)))
        selected = inquirer.prompt(
            [
                inquirer.Text(
                    "selected",
                    message=message,
                    validate=validate_selection,
                )
            ]
        )
        selected = int(typing.cast(dict[str, str], selected)["selected"])
        self.print_rule()
        return selected

    pass


class SpotServerCreator:
    def __init__(self, client: Client) -> None:
        self.client = client

    def create_server(
        self,
        region_id: str,
        resource_group_id: str,
        vswitch_id: str,
        instance_type_id: str,
        image_id: str,
        system_disk_size: int,
        system_disk_category: str,
        data_disk_size: int,
        data_disk_category: str,
        data_disk_snapshot_id: str,
        security_group_id: str,
        instance_name: str,
        description: str,
        automation_tag: SingleKeyDict,
    ):
        region_id = self.client._region_id
        automation_tag_key, automation_tag_value = get_tag_from_single_key_dict(automation_tag)

        # Maintain parameter order consistent with the Alibaba Cloud buy page UI
        request = RunInstancesRequest(
            instance_charge_type="PostPaid",
            region_id=region_id,
            v_switch_id=vswitch_id,
            instance_type=instance_type_id,
            spot_strategy="SpotAsPriceGo",
            spot_duration=0,
            spot_interruption_behavior="Stop",
            image_id=image_id,
            system_disk=RunInstancesRequestSystemDisk(
                size=str(system_disk_size),
                category=system_disk_category,
                performance_level="PL0",
            ),
            data_disk=[
                RunInstancesRequestDataDisk(
                    size=data_disk_size,
                    category=data_disk_category,
                    snapshot_id=data_disk_snapshot_id,
                )
            ],
            security_group_id=security_group_id,
            password_inherit=True,
            resource_group_id=resource_group_id,
            instance_name=instance_name,
            description=description,
            tag=[
                RunInstancesRequestTag(
                    key=automation_tag_key, value=automation_tag_value
                )
            ],
        )
        # self.client.run_instances()
