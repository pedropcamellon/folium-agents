"""Vendor-neutral command registration and dispatch contract tests."""

import argparse

import pytest


class FakeModule:
    name = "fake"

    def __init__(self) -> None:
        self.dispatched_command: str | None = None

    def register_commands(self, parser: argparse.ArgumentParser) -> None:
        commands = parser.add_subparsers(dest="module_action", required=True)
        commands.add_parser("probe")

    def run(self, args: argparse.Namespace) -> None:
        self.dispatched_command = args.module_action


def test_core_cli_registers_and_dispatches_a_fake_module() -> None:
    from folium_agents.core.cli import build_parser, dispatch

    module = FakeModule()
    parser = build_parser([module])
    args = parser.parse_args(["fake", "probe"])

    dispatch(args, [module])

    assert module.dispatched_command == "probe"


def test_core_cli_rejects_unregistered_modules() -> None:
    from folium_agents.core.cli import build_parser

    parser = build_parser([FakeModule()])

    with pytest.raises(SystemExit):
        parser.parse_args(["unknown", "probe"])
