"""Contract for modules that expose tools and command-line workflows."""

from __future__ import annotations

import argparse
from typing import Protocol


class HarnessModule(Protocol):
    """A lazily loaded module that contributes commands to the harness."""

    name: str

    def register_commands(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace) -> None: ...
