"""Epic sandbox patient lookup command."""

import argparse
import asyncio

from rich.console import Console

from folium_agents.epic.commands.protocol import EpicCommand
from folium_agents.epic.epic_cli import list_epic_patients


class PatientsCommand:
    name = "patients"
    help = "search for a sandbox Patient by FHIR ID"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--patient-id",
            required=True,
            help="FHIR ID of a sandbox test patient",
        )

    def run(self, args: argparse.Namespace, console: Console) -> None:
        asyncio.run(list_epic_patients(args.patient_id, console))


def create_command() -> EpicCommand:
    return PatientsCommand()
