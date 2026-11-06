import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from folium_agents.epic import EpicConfig, EpicSmartClient
from folium_agents.openemr import OpenEMRConfig, OpenEMRFhirClient


def _load_environment() -> None:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env", override=False)


async def _run(command: str, limit: int, console: Console) -> None:
    if command == "epic-discover":
        config = EpicConfig.from_environment()
        smart = await EpicSmartClient(config).discover()
        console.print(f"Epic SMART authorization endpoint: {smart.authorization_endpoint}")
        console.print(f"Epic SMART token endpoint: {smart.token_endpoint}")
        console.print(
            "PKCE S256: "
            f"{'supported' if 'S256' in smart.code_challenge_methods_supported else 'not supported'}"
        )
        return

    client = OpenEMRFhirClient(OpenEMRConfig.from_environment())
    if command == "patients":
        result = await client.list_patient_ids(limit=limit)
        total = result.total if result.total is not None else "unknown"
        table = Table(title=f"Patient IDs ({len(result.patient_ids)} shown; total: {total})")
        table.add_column("Patient ID", style="cyan")
        for patient_id in result.patient_ids:
            table.add_row(patient_id)
        console.print(table)
        return

    capability = await client.get_capability_statement()
    console.print(
        f"[green]Connected to OpenEMR FHIR "
        f"{capability.fhir_version} ({capability.status}).[/green]"
    )


def _show_menu(console: Console) -> None:
    console.print(
        Panel(
            "[1] Check OpenEMR connection\n"
            "[2] List patient IDs\n"
            "[3] Exit",
            title="Folium Agents",
            border_style="green",
        )
    )
    choice = Prompt.ask(
        "Choose an action",
        choices=["1", "2", "3"],
        default="1",
        console=console,
    )
    if choice == "3":
        console.print("Goodbye.")
        return

    limit = 20
    if choice == "2":
        limit = IntPrompt.ask(
            "Maximum patient IDs to show (1-100)",
            default=20,
            console=console,
        )
        if not 1 <= limit <= 100:
            console.print("[red]Choose a limit from 1 to 100.[/red]")
            return

    asyncio.run(_run("patients" if choice == "2" else "check", limit, console))


def main() -> None:
    _load_environment()
    parser = argparse.ArgumentParser(description="Connect to an OpenEMR FHIR server.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("menu", "check", "patients", "epic-discover"),
        default="menu",
        help=(
            "open the menu, check OpenEMR, list patient IDs, "
            "or inspect Epic sandbox SMART configuration"
        ),
    )
    parser.add_argument("--limit", type=int, default=20, help="patient page size (1-100)")
    args = parser.parse_args()
    console = Console()
    if args.command == "menu":
        _show_menu(console)
    else:
        asyncio.run(_run(args.command, args.limit, console))
