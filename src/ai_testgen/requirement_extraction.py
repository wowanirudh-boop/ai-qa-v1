from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any

from ai_testgen.artifact_store import ArtifactStore, ArtifactStoreError
from ai_testgen.schemas import (
    CandidateRequirementPackage,
    SourceChunk,
    SchemaValidationError,
    SkillDefinition,
    SkillRunRecord,
    SourceChunkProcessingStatus,
    SourcePackage,
)
from ai_testgen.skill_runtime import (
    InvalidSkillDefinitionError,
    SkillExecutionError,
    SkillRuntime,
    SkillRuntimeError,
    load_skill_definition,
    validate_skill_definition,
)
from ai_testgen.skill_runtime_config import create_skill_runtime_for_run


SOURCE_PACKAGE_STAGE = "02_source_package"
SOURCE_PACKAGE_ARTIFACT_NAME = "source_package"
CANDIDATE_REQUIREMENTS_STAGE = "03_candidate_requirements"
CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME = "candidate_requirement_package"
RAW_CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME = "candidate_requirement_package_skill_output"
SOURCE_PACKAGE_EXTRACTION_INPUT_ARTIFACT_NAME = "source_package_extraction_input"
SOURCE_PACKAGE_EXTRACTION_STATUS_ARTIFACT_NAME = "source_package_extraction_status"
DEFAULT_SKILL_DEFINITION_PATH = Path("skills") / "requirement_extraction_v1.json"
REQUIREMENT_EXTRACTION_INPUT_CONTRACT = "SourcePackage"
REQUIREMENT_EXTRACTION_OUTPUT_CONTRACT = "CandidateRequirementPackage"
CANDIDATE_PACKAGE_ID = "cand_pkg_001"


class RequirementExtractionError(Exception):
    """Base error for C07 requirement extraction failures."""


class SourcePackageArtifactError(RequirementExtractionError):
    """Raised when the input SourcePackage artifact cannot be used."""


class InvalidRequirementExtractionSkillError(RequirementExtractionError):
    """Raised when the extraction SkillDefinition does not match C07 contracts."""


class RequirementExtractionSkillError(RequirementExtractionError):
    """Raised when the Skill Runtime fails the extraction run."""


class InvalidCandidateRequirementPackageError(RequirementExtractionError):
    """Raised when extracted candidates fail C07 cross-artifact validation."""


class RequirementExtractionPersistenceError(RequirementExtractionError):
    """Raised when C07 cannot persist its deterministic status artifact."""


@dataclass(frozen=True)
class RequirementExtractionResult:
    candidate_package: CandidateRequirementPackage
    skill_run_record: SkillRunRecord
    candidate_package_path: Path
    skill_run_record_path: Path
    skill_run_records: list[SkillRunRecord]
    skill_run_record_paths: list[Path]
    source_status_path: Path | None = None


def extract_requirements_from_source_package_artifact(
    source_package_path: str | Path,
    skill_definition: SkillDefinition | str | Path = DEFAULT_SKILL_DEFINITION_PATH,
    *,
    skill_runtime: SkillRuntime | None = None,
    skill_adapter: str | None = None,
    skill_run_id: str | None = None,
    max_chunks_per_skill_run: int = 1,
) -> RequirementExtractionResult:
    if type(max_chunks_per_skill_run) is not int or max_chunks_per_skill_run < 1:
        raise SourcePackageArtifactError("max_chunks_per_skill_run must be a positive integer")

    source_path = Path(source_package_path)
    artifact_root, project_id, run_id = _artifact_context_from_source_package_path(source_path)
    store = ArtifactStore(artifact_root)
    source_package = _load_source_package(store, project_id=project_id, run_id=run_id)
    if source_package.project_id != project_id:
        raise SourcePackageArtifactError(
            f"SourcePackage artifact project directory must match project_id {source_package.project_id}: "
            f"{source_path}"
        )

    definition = _load_requirement_extraction_skill_definition(skill_definition)
    eligible_chunks = _eligible_source_chunks(source_package)
    try:
        runtime = skill_runtime or create_skill_runtime_for_run(
            artifact_root=artifact_root,
            project_id=project_id,
            run_id=run_id,
            adapter_name=skill_adapter,
        )
    except SkillRuntimeError as exc:
        raise RequirementExtractionSkillError(f"Requirement extraction skill failed: {exc}") from exc
    batches = list(_chunk_batches(eligible_chunks, max_chunks_per_skill_run))
    raw_candidate_packages: list[CandidateRequirementPackage] = []
    skill_run_records: list[SkillRunRecord] = []

    for batch_index, batch in enumerate(batches, start=1):
        bounded_source_package = _source_package_with_chunks(source_package, batch)
        bounded_source_artifact = _write_extraction_input_source_package(
            store,
            run_id=run_id,
            source_package=bounded_source_package,
        )
        raw_candidate_path, raw_candidate_version = _next_artifact_path(
            store,
            project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            RAW_CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME,
        )
        run_id_for_skill = _skill_run_id_for_batch(
            store,
            project_id,
            run_id,
            skill_run_id,
            batch_index,
            len(batches),
        )

        try:
            skill_run_record = runtime.run_skill(
                definition,
                input_artifact_paths=[bounded_source_artifact.path],
                output_artifact_paths=[raw_candidate_path],
                skill_run_id=run_id_for_skill,
            )
        except SkillExecutionError as exc:
            raise RequirementExtractionSkillError(f"Requirement extraction skill failed: {exc}") from exc

        raw_candidate_package = _load_candidate_package(
            store,
            project_id=project_id,
            run_id=run_id,
            artifact_name=RAW_CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME,
            version=raw_candidate_version,
        )
        validate_candidate_package_against_source(raw_candidate_package, bounded_source_package)
        raw_candidate_packages.append(raw_candidate_package)
        skill_run_records.append(skill_run_record)

    candidate_package = _merge_candidate_packages_with_deterministic_ids(raw_candidate_packages)
    validate_candidate_package_against_source(candidate_package, source_package)
    final_candidate_artifact = _write_candidate_package(
        store,
        run_id=run_id,
        candidate_package=candidate_package,
    )

    status_path = _write_updated_source_package_if_needed(
        store,
        run_id=run_id,
        source_package=source_package,
        candidate_package=candidate_package,
        eligible_chunk_ids={chunk.chunk_id for chunk in eligible_chunks},
    )
    skill_run_record_paths = [
        store.artifact_path(project_id, run_id, "skill_runs", record.skill_run_id)
        for record in skill_run_records
    ]

    return RequirementExtractionResult(
        candidate_package=candidate_package,
        skill_run_record=skill_run_records[0],
        candidate_package_path=final_candidate_artifact.path,
        skill_run_record_path=skill_run_record_paths[0],
        skill_run_records=skill_run_records,
        skill_run_record_paths=skill_run_record_paths,
        source_status_path=status_path,
    )


def validate_candidate_package_against_source(
    candidate_package: CandidateRequirementPackage,
    source_package: SourcePackage,
) -> None:
    if candidate_package.project_id != source_package.project_id:
        raise InvalidCandidateRequirementPackageError("CandidateRequirementPackage project_id must match SourcePackage")
    if candidate_package.source_package_id != source_package.source_package_id:
        raise InvalidCandidateRequirementPackageError(
            "CandidateRequirementPackage source_package_id must match SourcePackage"
        )

    chunks_by_id = {chunk.chunk_id: chunk for chunk in source_package.chunks}
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidate_package.candidates}
    for candidate in candidate_package.candidates:
        for source_ref in candidate.source_refs:
            chunk = chunks_by_id.get(source_ref.chunk_id or "")
            if chunk is None:
                raise InvalidCandidateRequirementPackageError(
                    f"candidate {candidate.candidate_id} references unknown source chunk {source_ref.chunk_id}"
                )
            if source_ref.document_id != chunk.document_id:
                raise InvalidCandidateRequirementPackageError(
                    f"candidate {candidate.candidate_id} source_ref document_id must match chunk "
                    f"{source_ref.chunk_id}"
                )
    for chunk_result in candidate_package.chunk_extraction_results or []:
        if chunk_result.chunk_id not in chunks_by_id:
            raise InvalidCandidateRequirementPackageError(
                f"chunk extraction result references unknown source chunk {chunk_result.chunk_id}"
            )
        for candidate_id in chunk_result.candidate_ids:
            candidate = candidates_by_id.get(candidate_id)
            if candidate is None:
                raise InvalidCandidateRequirementPackageError(
                    f"chunk extraction result references unknown candidate {candidate_id}"
                )
            if not any(source_ref.chunk_id == chunk_result.chunk_id for source_ref in candidate.source_refs):
                raise InvalidCandidateRequirementPackageError(
                    f"chunk extraction result candidate {candidate_id} must reference chunk "
                    f"{chunk_result.chunk_id}"
                )


def _load_requirement_extraction_skill_definition(
    skill_definition: SkillDefinition | str | Path,
) -> SkillDefinition:
    try:
        definition = (
            skill_definition
            if isinstance(skill_definition, SkillDefinition)
            else load_skill_definition(skill_definition)
        )
        validated = validate_skill_definition(definition)
    except (InvalidSkillDefinitionError, SchemaValidationError, SkillRuntimeError) as exc:
        raise InvalidRequirementExtractionSkillError(f"Invalid requirement extraction SkillDefinition: {exc}") from exc

    if validated.input_contract != REQUIREMENT_EXTRACTION_INPUT_CONTRACT:
        raise InvalidRequirementExtractionSkillError(
            f"Requirement extraction skill input_contract must be {REQUIREMENT_EXTRACTION_INPUT_CONTRACT}"
        )
    if validated.output_contract != REQUIREMENT_EXTRACTION_OUTPUT_CONTRACT:
        raise InvalidRequirementExtractionSkillError(
            f"Requirement extraction skill output_contract must be {REQUIREMENT_EXTRACTION_OUTPUT_CONTRACT}"
        )
    return validated


def _load_source_package(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
) -> SourcePackage:
    try:
        return store.load_model(
            SourcePackage,
            project_id,
            run_id,
            SOURCE_PACKAGE_STAGE,
            SOURCE_PACKAGE_ARTIFACT_NAME,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise SourcePackageArtifactError(f"Failed to load SourcePackage artifact: {exc}") from exc


def _load_candidate_package(
    store: ArtifactStore,
    *,
    project_id: str,
    run_id: str,
    artifact_name: str,
    version: int,
) -> CandidateRequirementPackage:
    try:
        return store.load_model(
            CandidateRequirementPackage,
            project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            artifact_name,
            version=version,
        )
    except (ArtifactStoreError, SchemaValidationError) as exc:
        raise InvalidCandidateRequirementPackageError(
            f"Failed to load CandidateRequirementPackage artifact: {exc}"
        ) from exc


def _write_extraction_input_source_package(
    store: ArtifactStore,
    *,
    run_id: str,
    source_package: SourcePackage,
):
    try:
        return store.write_json(
            source_package.project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            SOURCE_PACKAGE_EXTRACTION_INPUT_ARTIFACT_NAME,
            source_package,
        )
    except ArtifactStoreError as exc:
        raise RequirementExtractionPersistenceError(
            f"Failed to save SourcePackage extraction input artifact: {exc}"
        ) from exc


def _write_candidate_package(
    store: ArtifactStore,
    *,
    run_id: str,
    candidate_package: CandidateRequirementPackage,
):
    try:
        return store.write_json(
            candidate_package.project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            CANDIDATE_REQUIREMENT_PACKAGE_ARTIFACT_NAME,
            candidate_package,
        )
    except ArtifactStoreError as exc:
        raise RequirementExtractionPersistenceError(
            f"Failed to save CandidateRequirementPackage artifact: {exc}"
        ) from exc


def _write_updated_source_package_if_needed(
    store: ArtifactStore,
    *,
    run_id: str,
    source_package: SourcePackage,
    candidate_package: CandidateRequirementPackage,
    eligible_chunk_ids: set[str],
) -> Path | None:
    updated_source_package = _source_package_with_extraction_statuses(
        source_package,
        candidate_package,
        eligible_chunk_ids=eligible_chunk_ids,
    )
    if updated_source_package is None:
        return None

    try:
        written = store.write_json(
            source_package.project_id,
            run_id,
            CANDIDATE_REQUIREMENTS_STAGE,
            SOURCE_PACKAGE_EXTRACTION_STATUS_ARTIFACT_NAME,
            updated_source_package,
        )
    except ArtifactStoreError as exc:
        raise RequirementExtractionPersistenceError(
            f"Failed to save SourcePackage extraction status artifact: {exc}"
        ) from exc
    return written.path


def _eligible_source_chunks(source_package: SourcePackage) -> list[SourceChunk]:
    chunks = [
        chunk
        for chunk in source_package.chunks
        if chunk.processing_status == SourceChunkProcessingStatus.NOT_PROCESSED
    ]
    if not chunks:
        raise SourcePackageArtifactError("No source chunks are eligible for requirement extraction")
    return chunks


def _source_package_with_chunks(source_package: SourcePackage, chunks: list[SourceChunk]) -> SourcePackage:
    data = source_package.to_dict()
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    data["chunks"] = [chunk for chunk in data["chunks"] if chunk["chunk_id"] in chunk_ids]
    if not data["chunks"]:
        raise SourcePackageArtifactError("No source chunks are eligible for requirement extraction")
    data["checksum"] = _checksum_source_package_data(data)
    try:
        return SourcePackage.from_dict(data)
    except SchemaValidationError as exc:
        raise SourcePackageArtifactError(f"Invalid eligible SourcePackage data: {exc}") from exc


def _merge_candidate_packages_with_deterministic_ids(
    candidate_packages: list[CandidateRequirementPackage],
) -> CandidateRequirementPackage:
    if not candidate_packages:
        raise InvalidCandidateRequirementPackageError("No CandidateRequirementPackage outputs to merge")

    project_id = candidate_packages[0].project_id
    source_package_id = candidate_packages[0].source_package_id
    data: dict[str, Any] = {
        "candidate_package_id": CANDIDATE_PACKAGE_ID,
        "project_id": project_id,
        "source_package_id": source_package_id,
        "candidates": [],
    }
    chunk_extraction_results: list[dict[str, Any]] = []
    next_candidate_id = count(1)

    for package in candidate_packages:
        if package.project_id != project_id:
            raise InvalidCandidateRequirementPackageError("CandidateRequirementPackage project_id values must match")
        if package.source_package_id != source_package_id:
            raise InvalidCandidateRequirementPackageError(
                "CandidateRequirementPackage source_package_id values must match"
            )

        candidate_id_map: dict[str, str] = {}
        for candidate in package.candidates:
            candidate_data = candidate.to_dict()
            original_candidate_id = candidate_data["candidate_id"]
            rewritten_candidate_id = f"cand_{next(next_candidate_id):03d}"
            candidate_data["candidate_id"] = rewritten_candidate_id
            candidate_id_map[original_candidate_id] = rewritten_candidate_id
            data["candidates"].append(candidate_data)

        for chunk_result in package.chunk_extraction_results or []:
            chunk_result_data = chunk_result.to_dict()
            rewritten_candidate_ids = []
            for candidate_id in chunk_result.candidate_ids:
                rewritten_candidate_id = candidate_id_map.get(candidate_id)
                if rewritten_candidate_id is None:
                    raise InvalidCandidateRequirementPackageError(
                        f"chunk extraction result references unknown candidate {candidate_id}"
                    )
                rewritten_candidate_ids.append(rewritten_candidate_id)
            chunk_result_data["candidate_ids"] = rewritten_candidate_ids
            chunk_extraction_results.append(chunk_result_data)

    if chunk_extraction_results:
        data["chunk_extraction_results"] = chunk_extraction_results

    try:
        return CandidateRequirementPackage.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidCandidateRequirementPackageError(
            f"Invalid deterministic CandidateRequirementPackage data: {exc}"
        ) from exc


def _source_package_with_extraction_statuses(
    source_package: SourcePackage,
    candidate_package: CandidateRequirementPackage,
    *,
    eligible_chunk_ids: set[str],
) -> SourcePackage | None:
    referenced_chunk_ids = {
        source_ref.chunk_id
        for candidate in candidate_package.candidates
        for source_ref in candidate.source_refs
        if source_ref.chunk_id
    }
    result_status_by_chunk_id = {
        chunk_result.chunk_id: chunk_result.processing_status
        for chunk_result in candidate_package.chunk_extraction_results or []
    }

    data = source_package.to_dict()
    changed = False
    for chunk in data["chunks"]:
        if (
            chunk["chunk_id"] in eligible_chunk_ids
            and chunk["processing_status"] == SourceChunkProcessingStatus.NOT_PROCESSED.value
        ):
            if chunk["chunk_id"] in referenced_chunk_ids:
                next_status = SourceChunkProcessingStatus.REQUIREMENTS_EXTRACTED.value
            elif chunk["chunk_id"] in result_status_by_chunk_id:
                next_status = result_status_by_chunk_id[chunk["chunk_id"]].value
            else:
                next_status = SourceChunkProcessingStatus.FAILED_PROCESSING.value

            if chunk["processing_status"] != next_status:
                chunk["processing_status"] = next_status
                changed = True

    if not changed:
        return None

    data["checksum"] = _checksum_source_package_data(data)
    try:
        return SourcePackage.from_dict(data)
    except SchemaValidationError as exc:
        raise InvalidCandidateRequirementPackageError(f"Invalid updated SourcePackage data: {exc}") from exc


def _artifact_context_from_source_package_path(path: Path) -> tuple[Path, str, str]:
    if path.name != "source_package.json":
        raise SourcePackageArtifactError(f"SourcePackage artifact must be named source_package.json: {path}")
    if path.parent.name != SOURCE_PACKAGE_STAGE:
        raise SourcePackageArtifactError(f"SourcePackage artifact must be under {SOURCE_PACKAGE_STAGE}: {path}")
    run_dir = path.parent.parent
    project_dir = run_dir.parent
    return project_dir.parent, project_dir.name, run_dir.name


def _next_artifact_path(
    store: ArtifactStore,
    project_id: str,
    run_id: str,
    stage: str,
    artifact_name: str,
) -> tuple[Path, int]:
    for version in count(1):
        if not store.exists(project_id, run_id, stage, artifact_name, version=version):
            return store.artifact_path(project_id, run_id, stage, artifact_name, version=version), version
    raise AssertionError("unreachable")


def _next_skill_run_id(store: ArtifactStore, project_id: str, run_id: str) -> str:
    for index in count(1):
        skill_run_id = f"skill_run_{index:03d}"
        if not store.exists(project_id, run_id, "skill_runs", skill_run_id):
            return skill_run_id
    raise AssertionError("unreachable")


def _skill_run_id_for_batch(
    store: ArtifactStore,
    project_id: str,
    run_id: str,
    requested_skill_run_id: str | None,
    batch_index: int,
    batch_count: int,
) -> str:
    if requested_skill_run_id is None:
        return _next_skill_run_id(store, project_id, run_id)
    if batch_count == 1:
        return requested_skill_run_id
    return f"{requested_skill_run_id}_{batch_index:03d}"


def _chunk_batches(chunks: list[SourceChunk], batch_size: int) -> list[list[SourceChunk]]:
    return [
        chunks[index:index + batch_size]
        for index in range(0, len(chunks), batch_size)
    ]


def _checksum_source_package_data(data: dict[str, Any]) -> str:
    content_data = dict(data)
    content_data.pop("checksum", None)
    content = json.dumps(
        content_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
