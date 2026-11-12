import argparse
from collections.abc import Callable

import pytest
from rich.console import Console

from folium_agents.epic import module as epic_module
from folium_agents.epic.module import EpicModule


class FakeEntryPoint:
    def __init__(self, name: str, factory: Callable[[], object]) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> Callable[[], object]:
        return self._factory


class FakeCommand:
    def __init__(self, name: str, calls: list[tuple[str, str]]) -> None:
        self.name = name
        self.help = f"run {name}"
        self._calls = calls

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--value", required=True)

    def run(self, args: argparse.Namespace, _console: Console) -> None:
        self._calls.append((self.name, args.value))


def test_module_discovers_configures_and_runs_entry_point_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    commands = {name: FakeCommand(name, calls) for name in ("alpha", "beta")}
    points = [
        FakeEntryPoint(name, lambda command=command: command)
        for name, command in reversed(tuple(commands.items()))
    ]
    monkeypatch.setattr(
        epic_module,
        "entry_points",
        lambda *, group: points,
    )

    module = EpicModule()
    parser = argparse.ArgumentParser()
    module.register_commands(parser)
    module.run(parser.parse_args(["alpha", "--value", "first"]))
    module.run(parser.parse_args(["beta", "--value", "second"]))

    assert calls == [("alpha", "first"), ("beta", "second")]


def test_module_rejects_duplicate_entry_point_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory() -> FakeCommand:
        return FakeCommand("duplicate", [])

    points = [
        FakeEntryPoint("duplicate", factory),
        FakeEntryPoint("duplicate", factory),
    ]
    monkeypatch.setattr(
        epic_module,
        "entry_points",
        lambda *, group: points,
    )

    with pytest.raises(ValueError, match="Duplicate Epic command entry point"):
        EpicModule().register_commands(argparse.ArgumentParser())


def test_module_rejects_command_name_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = FakeEntryPoint("registered-name", lambda: FakeCommand("different-name", []))
    monkeypatch.setattr(
        epic_module,
        "entry_points",
        lambda *, group: [point],
    )

    with pytest.raises(ValueError, match="created command named"):
        EpicModule().register_commands(argparse.ArgumentParser())


def test_builtin_commands_are_registered_from_package_entry_points() -> None:
    module = EpicModule()
    parser = argparse.ArgumentParser()
    module.register_commands(parser)

    assert parser.parse_args(["discover"]).action == "discover"
    assert parser.parse_args(["logout"]).action == "logout"
    assert parser.parse_args(["patients", "--patient-id", "patient-1"]).patient_id == (
        "patient-1"
    )


def test_module_rejects_unsupported_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(epic_module, "entry_points", lambda *, group: [])
    module = EpicModule()
    module.register_commands(argparse.ArgumentParser())

    with pytest.raises(ValueError, match="Unsupported Epic command"):
        module.run(argparse.Namespace(action="unsupported"))
