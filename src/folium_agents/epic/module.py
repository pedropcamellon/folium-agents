"""Epic module registration for the generic Folium Agents harness."""

import argparse
from importlib.metadata import entry_points

from rich.console import Console

from folium_agents.core.module import HarnessModule
from folium_agents.epic.commands.protocol import EpicCommand

COMMAND_ENTRY_POINT_GROUP = "folium_agents.epic.commands"


class EpicModule(HarnessModule):
    name = "epic"

    def __init__(self) -> None:
        self._commands: dict[str, EpicCommand] = {}

    def register_commands(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True)
        self._commands = self._discover_commands()
        for command in self._commands.values():
            command_parser = actions.add_parser(command.name, help=command.help)
            command.configure_parser(command_parser)

    def run(self, args: argparse.Namespace) -> None:
        command = self._commands.get(args.action)
        if command is None:
            raise ValueError(f"Unsupported Epic command: {args.action}")

        command.run(args, Console())

    @staticmethod
    def _discover_commands() -> dict[str, EpicCommand]:
        commands: dict[str, EpicCommand] = {}
        entry_points_for_commands = sorted(
            entry_points(group=COMMAND_ENTRY_POINT_GROUP),
            key=lambda point: point.name,
        )
        for entry_point in entry_points_for_commands:
            if entry_point.name in commands:
                raise ValueError(
                    f"Duplicate Epic command entry point: {entry_point.name}"
                )
            command_factory = entry_point.load()
            command = command_factory()
            if command.name != entry_point.name:
                raise ValueError(
                    f"Epic command entry point {entry_point.name!r} "
                    f"created command named {command.name!r}."
                )
            commands[command.name] = command
        return commands


def create_module() -> EpicModule:
    return EpicModule()
