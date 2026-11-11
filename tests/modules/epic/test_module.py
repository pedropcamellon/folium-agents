import argparse

import pytest

from folium_agents.epic import module as epic_module
from folium_agents.epic.module import EpicModule


def test_module_dispatches_registered_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    async def discover(_console: object) -> None:
        calls.append(("discover", None))

    def logout(_console: object) -> None:
        calls.append(("logout", None))

    async def patients(patient_id: str, _console: object) -> None:
        calls.append(("patients", patient_id))

    async def medication_review(patient_id: str, _console: object) -> None:
        calls.append(("medication-review", patient_id))

    monkeypatch.setattr(epic_module, "discover_epic", discover)
    monkeypatch.setattr(epic_module, "logout_epic", logout)
    monkeypatch.setattr(epic_module, "list_epic_patients", patients)
    monkeypatch.setattr(
        epic_module,
        "review_patient_medications",
        medication_review,
    )

    module = EpicModule()
    parser = argparse.ArgumentParser()
    module.register_commands(parser)
    for argv in (
        ["discover"],
        ["logout"],
        ["patients", "--patient-id", "patient-1"],
        ["medication-review", "--patient-id", "patient-2"],
    ):
        module.run(parser.parse_args(argv))

    assert calls == [
        ("discover", None),
        ("logout", None),
        ("patients", "patient-1"),
        ("medication-review", "patient-2"),
    ]


def test_module_rejects_unsupported_commands() -> None:
    with pytest.raises(ValueError, match="Unsupported Epic command"):
        EpicModule().run(argparse.Namespace(action="unsupported"))
