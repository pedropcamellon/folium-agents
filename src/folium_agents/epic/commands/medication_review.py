"""Epic patient medication review command."""

import argparse
import asyncio

from rich.console import Console

from folium_agents.epic.commands.protocol import EpicCommand
from folium_agents.epic.epic_cli import review_patient_medications


class MedicationReviewCommand:
    name = "medication-review"
    help = "review charted medications, allergies, and conditions"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--patient-id",
            required=True,
            help="FHIR ID of the patient selected during SMART authorization",
        )

    def run(self, args: argparse.Namespace, console: Console) -> None:
        asyncio.run(review_patient_medications(args.patient_id, console))


def create_command() -> EpicCommand:
    return MedicationReviewCommand()
