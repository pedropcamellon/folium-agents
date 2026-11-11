"""Epic SMART/FHIR capability inspection command."""

import argparse
import asyncio

from rich.console import Console

from folium_agents.epic.commands.protocol import EpicCommand
from folium_agents.epic.epic_cli import discover_epic


class DiscoverCommand:
    name = "discover"
    help = "inspect Epic SMART/FHIR capabilities"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace, console: Console) -> None:
        asyncio.run(discover_epic(console))


def create_command() -> EpicCommand:
    return DiscoverCommand()
