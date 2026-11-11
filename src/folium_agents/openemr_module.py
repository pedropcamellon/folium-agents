"""OpenEMR module registration for the generic Folium Agents harness."""

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from folium_agents.core.module import HarnessModule
from folium_agents.openemr import OpenEMRConfig, OpenEMRFhirClient


class OpenEMRModule(HarnessModule):
    name = "openemr"

    @staticmethod
    def _load_environment() -> None:
        repository_root = Path(__file__).resolve().parents[2]
        load_dotenv(repository_root / ".env", override=False)

    def register_commands(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True)
        actions.add_parser("check", help="check the OpenEMR FHIR connection")
        patient_parser = actions.add_parser(
            "patients",
            help="list a bounded page of OpenEMR Patient IDs",
        )
        patient_parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="patient page size (1-100)",
        )

    def run(self, args: argparse.Namespace) -> None:
        self._load_environment()
        console = Console()
        client = OpenEMRFhirClient(OpenEMRConfig.from_environment())
        if args.action == "check":
            capability = asyncio.run(client.get_capability_statement())
            console.print(
                f"Connected to OpenEMR FHIR "
                f"{capability.fhir_version} ({capability.status})."
            )
            return
        if args.action == "patients":
            if not 1 <= args.limit <= 100:
                raise ValueError("Patient page size must be between 1 and 100.")
            result = asyncio.run(client.list_patient_ids(limit=args.limit))
            total = result.total if result.total is not None else "unknown"
            table = Table(
                title=f"Patient IDs ({len(result.patient_ids)} shown; total: {total})"
            )
            table.add_column("Patient ID")
            for patient_id in result.patient_ids:
                table.add_row(patient_id)
            console.print(table)
            return
        raise ValueError(f"Unsupported OpenEMR command: {args.action}")


def create_module() -> OpenEMRModule:
    return OpenEMRModule()
