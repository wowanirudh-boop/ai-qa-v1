from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_testgen.document_ingestion import DocumentIngestionError, ingest_documents_from_config_artifact
from ai_testgen.project_config import ProjectConfigError, load_project_config, save_project_config
from ai_testgen.requirement_extraction import (
    DEFAULT_SKILL_DEFINITION_PATH,
    RequirementExtractionError,
    extract_requirements_from_source_package_artifact,
)
from ai_testgen.requirement_atomization import (
    RequirementAtomizationError,
    atomize_requirements_from_candidate_package_artifact,
)
from ai_testgen.source_ledger import SourceLedgerError, build_source_package_from_documents_artifact


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

    ingest_parser = subcommands.add_parser("ingest-documents")
    ingest_parser.add_argument("--config", required=True, type=Path)
    ingest_parser.set_defaults(func=_ingest_documents)

    source_package_parser = subcommands.add_parser("build-source-package")
    source_package_parser.add_argument("--documents", required=True, type=Path)
    source_package_parser.set_defaults(func=_build_source_package)

    extract_parser = subcommands.add_parser("extract-requirements")
    extract_parser.add_argument("--source-package", required=True, type=Path)
    extract_parser.add_argument("--skill-definition", type=Path, default=DEFAULT_SKILL_DEFINITION_PATH)
    extract_parser.set_defaults(func=_extract_requirements)

    atomize_parser = subcommands.add_parser("atomize-requirements")
    atomize_parser.add_argument("--candidates", required=True, type=Path)
    atomize_parser.add_argument("--skill-definition", type=Path)
    atomize_parser.set_defaults(func=_atomize_requirements)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except (
        ProjectConfigError,
        DocumentIngestionError,
        SourceLedgerError,
        RequirementExtractionError,
        RequirementAtomizationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _validate_config(args: argparse.Namespace) -> int:
    config = load_project_config(args.config)
    written = save_project_config(config, run_id=args.run_id, artifact_root=args.artifact_root)
    print(f"Validated ProjectConfig saved to {written.path}")
    return 0


def _ingest_documents(args: argparse.Namespace) -> int:
    written = ingest_documents_from_config_artifact(args.config)
    print(f"Ingested documents saved to {written.path}")
    return 0


def _build_source_package(args: argparse.Namespace) -> int:
    written = build_source_package_from_documents_artifact(args.documents)
    print(f"Built source package saved to {written.path}")
    return 0


def _extract_requirements(args: argparse.Namespace) -> int:
    result = extract_requirements_from_source_package_artifact(args.source_package, args.skill_definition)
    print(f"Extracted candidate requirements saved to {result.candidate_package_path}")
    return 0


def _atomize_requirements(args: argparse.Namespace) -> int:
    result = atomize_requirements_from_candidate_package_artifact(args.candidates, args.skill_definition)
    print(f"Atomized requirements saved to {result.atomic_ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
