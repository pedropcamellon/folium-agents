"""Core harness tests that enforce vendor-neutral imports."""

import ast
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "folium_agents"
CORE_ROOT = SOURCE_ROOT / "core"


def test_core_runtime_does_not_import_concrete_ehr_modules() -> None:
    imported_modules: list[str] = []
    for source_file in [SOURCE_ROOT / "cli.py", *CORE_ROOT.glob("*.py")]:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        imported_modules.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported_modules.extend(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )

    assert not [
        module
        for module in imported_modules
        if module.startswith("folium_agents.epic")
    ]


def test_importing_harness_does_not_eagerly_import_epic_module() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, folium_agents; "
                "assert not any(name == 'folium_agents.epic' or "
                "name.startswith('folium_agents.epic.') for name in sys.modules)"
            ),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_core_startup_succeeds_if_epic_imports_are_blocked() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """\
import importlib.abc
import sys

class BlockEpic(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("folium_agents.epic", "httpx", "keyring", "pydantic")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError(f"core imported module dependency {fullname}")

sys.meta_path.insert(0, BlockEpic())
import folium_agents
from folium_agents.core import cli
""",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
