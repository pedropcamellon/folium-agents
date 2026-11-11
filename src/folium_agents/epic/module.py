"""Epic module registration for the generic Folium Agents harness."""

import argparse
import asyncio
from collections.abc import Callable

from rich.console import Console

from folium_agents.core.module import HarnessModule
from folium_agents.epic.epic_cli import (
    discover_epic,
    list_epic_patients,
    logout_epic,
    review_patient_medications,
)

CommandHandler = Callable[[argparse.Namespace, Console], None]


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
        review_parser = actions.add_parser(
            "medication-review",
            help="review charted medications, allergies, and conditions",
        )
        review_parser.add_argument(
            "--patient-id",
            required=True,
            help="FHIR ID of the patient selected during SMART authorization",
        )

    def run(self, args: argparse.Namespace) -> None:
        handlers: dict[str, CommandHandler] = {
            "discover": self._run_discover,
            "logout": self._run_logout,
            "patients": self._run_patients,
            "medication-review": self._run_medication_review,
        }
        handler = handlers.get(args.action)
        if handler is None:
            raise ValueError(f"Unsupported Epic command: {args.action}")
        handler(args, Console())

    @staticmethod
    def _run_discover(_args: argparse.Namespace, console: Console) -> None:
        asyncio.run(discover_epic(console))

    @staticmethod
    def _run_logout(_args: argparse.Namespace, console: Console) -> None:
        logout_epic(console)

    @staticmethod
    def _run_patients(args: argparse.Namespace, console: Console) -> None:
        asyncio.run(list_epic_patients(args.patient_id, console))

    @staticmethod
    def _run_medication_review(args: argparse.Namespace, console: Console) -> None:
        asyncio.run(review_patient_medications(args.patient_id, console))


def create_module() -> EpicModule:
    return EpicModule()
