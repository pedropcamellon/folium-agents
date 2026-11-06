"""Vendor-neutral module discovery and command dispatch."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import EntryPoint, entry_points
from typing import cast

from folium_agents.core.module import HarnessModule

ENTRY_POINT_GROUP = "folium_agents.modules"


def discover_modules() -> dict[str, EntryPoint]:
    return {
        point.name: point
        for point in entry_points(group=ENTRY_POINT_GROUP)
    }


def build_parser(
    modules: Sequence[HarnessModule],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run agent tools and optional domain modules."
    )
    module_parsers = parser.add_subparsers(dest="module_name", required=True)
    for module in modules:
        module_parser = module_parsers.add_parser(module.name)
        module.register_commands(module_parser)
    return parser


def dispatch(
    args: argparse.Namespace,
    modules: Sequence[HarnessModule],
) -> None:
    module_name = getattr(args, "module_name", None)
    module = next((item for item in modules if item.name == module_name), None)
    if module is None:
        raise ValueError(f"No registered module named {module_name!r}.")
    module.run(args)


def load_module(
    name: str,
    *,
    module_discovery: Callable[[], dict[str, EntryPoint]] = discover_modules,
) -> HarnessModule:
    modules = module_discovery()
    try:
        selected = modules[name]
    except KeyError:
        available = ", ".join(sorted(modules))
        raise ValueError(
            f"Unknown module {name!r}. Available modules: {available}"
        ) from None
    module = cast(HarnessModule, selected.load()())
    if module.name != name:
        raise ValueError(
            f"Module entry point {name!r} loaded a module named {module.name!r}."
        )
    return module


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        modules = discover_modules()
        names = ", ".join(sorted(modules)) or "(none installed)"
        print(
            "Usage: folium-agents <module> <command> [options]\n"
            f"Available modules: {names}"
        )
        return

    module = load_module(args[0])
    parser = build_parser([module])
    parsed_args = parser.parse_args(args)
    dispatch(parsed_args, [module])
