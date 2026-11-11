"""Epic saved-token cleanup command."""

import argparse

from rich.console import Console

from folium_agents.epic.commands.protocol import EpicCommand
from folium_agents.epic.epic_cli import logout_epic


class LogoutCommand:
    name = "logout"
    help = "remove the saved Epic token"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace, console: Console) -> None:
        logout_epic(console)


def create_command() -> EpicCommand:
    return LogoutCommand()
