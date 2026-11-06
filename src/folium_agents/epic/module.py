"""Epic module registration for the generic Folium Agents harness."""

import argparse
import asyncio

from rich.console import Console

from folium_agents.core.module import HarnessModule
from folium_agents.epic.epic_cli import (
    discover_epic,
    list_epic_patients,
    logout_epic,
)


class EpicModule(HarnessModule):
    name = "epic"

    def register_commands(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True)
        actions.add_parser("discover", help="inspect Epic SMART/FHIR capabilities")
        actions.add_parser("logout", help="remove the saved Epic token")
        patient_parser = actions.add_parser(
            "patients",
            help="search for a sandbox Patient by FHIR ID",
        )
        patient_parser.add_argument(
            "--patient-id",
            required=True,
            help="FHIR ID of a sandbox test patient",
        )

    def run(self, args: argparse.Namespace) -> None:
        console = Console()
        if args.action == "discover":
            asyncio.run(discover_epic(console))
        elif args.action == "logout":
            logout_epic(console)
        elif args.action == "patients":
            asyncio.run(list_epic_patients(args.patient_id, console))
        else:
            raise ValueError(f"Unsupported Epic command: {args.action}")


def create_module() -> EpicModule:
    return EpicModule()
