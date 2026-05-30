from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_testgen.project_config import ProjectConfigError, load_project_config, save_project_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-testgen")
    subcommands = parser.add_subparsers(dest="command", required=True)

    config_parser = subcommands.add_parser("config")
    config_subcommands = config_parser.add_subparsers(dest="config_command", required=True)

    validate_parser = config_subcommands.add_parser("validate")
    validate_parser.add_argument("--config", required=True, type=Path)
    validate_parser.add_argument("--run-id", required=True)
    validate_parser.add_argument("--artifact-root", type=Path)
    validate_parser.set_defaults(func=_validate_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except ProjectConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _validate_config(args: argparse.Namespace) -> int:
    config = load_project_config(args.config)
    written = save_project_config(config, run_id=args.run_id, artifact_root=args.artifact_root)
    print(f"Validated ProjectConfig saved to {written.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
