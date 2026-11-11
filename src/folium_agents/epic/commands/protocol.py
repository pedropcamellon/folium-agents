"""Contract for independently registered Epic CLI commands."""

import argparse
from typing import Protocol

from rich.console import Console


class EpicCommand(Protocol):
    name: str
    help: str

    def configure_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace, console: Console) -> None: ...
