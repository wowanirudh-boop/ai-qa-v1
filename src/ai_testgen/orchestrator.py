from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.document_ingestion import ingest_documents
from ai_testgen.executor_export import export_tests_from_validated_suite_artifact
from ai_testgen.obligation_planning import plan_obligations_from_governed_ledger_artifact
from ai_testgen.project_config import load_project_config, save_project_config
from ai_testgen.requirement_atomization import atomize_requirements_from_candidate_package_artifact
from ai_testgen.requirement_extraction import extract_requirements_from_source_package_artifact
from ai_testgen.requirement_governance import govern_requirements_from_atomic_ledger_artifact
from ai_testgen.review_report import generate_review_report_from_validated_suite_artifact
from ai_testgen.schemas import (
    AtomicRequirementLedger,
    CandidateRequirementPackage,
    CoverageReport,
    Document,
    DraftTestSuite,
    ExecutorExportPackage,
    GovernedRequirementLedger,
    PIPELINE_RUN_STAGES,
    PipelineRunState,
    PipelineRunStatus,
    ProjectConfig,
    ReviewReportMetadata,
    SchemaModel,
    SchemaValidationError,
    SourcePackage,
    TestObligationLedger,
    ValidatedTestSuite,
)
from ai_testgen.source_ledger import build_source_package_from_documents_artifact
from ai_testgen.test_generation import generate_tests_from_obligation_ledger_artifact
from ai_testgen.test_validation import validate_tests_from_draft_suite_artifact
from ai_testgen.validators import (
    validate_executor_export_package,
    validate_obligation_links,
    validate_test_case_links,
)


PIPELINE_RUN_STATE_ARTIFACT_NAME = "pipeline_run_state"
PIPELINE_RUN_ID = "pipeline_run_001"


class PipelineOrchestrationError(Exception):
    """Base error for C15 pipeline orchestration failures."""


class PipelineCheckpointError(PipelineOrchestrationError):
    """Raised when an existing checkpoint artifact is missing or invalid."""


class PipelineComponentError(PipelineOrchestrationError):
    """Raised when a component stage fails during orchestration."""


@dataclass(frozen=True)
class PipelineRunOptions:
    requirement_extraction_skill_definition: str | Path | None = None
    requirement_atomization_skill_definition: str | Path | None = None
    test_case_writer_skill_definition: str | Path | None = None
    oracle_generator_skill_definition: str | Path | None = None
    resume: bool = True
    include_review: bool = True
    include_export: bool = True


@dataclass(frozen=True)
class PipelineRunContext:
    config_path: Path
    project_config: ProjectConfig
    run_id: str
    artifact_root: Path
    source_base_dir: Path
    options: PipelineRunOptions


@dataclass(frozen=True)
class PipelineRunResult:
    state: PipelineRunState
    state_path: Path
    artifact_paths: dict[str, Path]


@dataclass(frozen=True)
class ArtifactSpec:
    key: str
    stage: str
    artifact_name: str
    model_type: type[SchemaModel] | None = None
    suffix: str = ".json"
    validator: Callable[[Path], None] | None = None


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    runner_name: str | None
    outputs: tuple[ArtifactSpec, ...]


class DefaultPipelineComponents:
    def run_project_config(
        self,
        context: PipelineRunContext,
        _artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        written = save_project_config(
            context.project_config,
            run_id=context.run_id,
            artifact_root=context.artifact_root,
        )
        return {"project_config": written.path}

    def run_document_ingestion(
        self,
        context: PipelineRunContext,
        _artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        written = ingest_documents(
            context.project_config,
            context.run_id,
            artifact_root=context.artifact_root,
            source_base_dir=context.source_base_dir,
        )
        return {"documents": written.path}

    def run_source_ledger(
        self,
        context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        written = build_source_package_from_documents_artifact(
            artifacts["documents"],
            source_base_dir=context.source_base_dir,
        )
        return {"source_package": written.path}

    def run_requirement_extraction(
        self,
        context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        if context.options.requirement_extraction_skill_definition is None:
            result = extract_requirements_from_source_package_artifact(artifacts["source_package"])
        else:
            result = extract_requirements_from_source_package_artifact(
                artifacts["source_package"],
                context.options.requirement_extraction_skill_definition,
            )
        return {"candidate_requirement_package": result.candidate_package_path}

    def run_requirement_atomization(
        self,
        context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = atomize_requirements_from_candidate_package_artifact(
            artifacts["candidate_requirement_package"],
            context.options.requirement_atomization_skill_definition,
        )
        return {"atomic_requirement_ledger": result.atomic_ledger_path}

    def run_requirement_governance(
        self,
        _context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = govern_requirements_from_atomic_ledger_artifact(artifacts["atomic_requirement_ledger"])
        return {"governed_requirement_ledger": result.governed_ledger_path}

    def run_obligation_planning(
        self,
        _context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = plan_obligations_from_governed_ledger_artifact(artifacts["governed_requirement_ledger"])
        return {"test_obligation_ledger": result.obligation_ledger_path}

    def run_test_generation(
        self,
        context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = generate_tests_from_obligation_ledger_artifact(
            artifacts["test_obligation_ledger"],
            context.options.test_case_writer_skill_definition,
            context.options.oracle_generator_skill_definition,
        )
        return {"draft_test_suite": result.draft_suite_path}

    def run_test_validation_coverage(
        self,
        _context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = validate_tests_from_draft_suite_artifact(artifacts["draft_test_suite"])
        paths = {"validated_test_suite": result.validated_suite_path}
        if result.coverage_report_path is not None:
            paths["coverage_report"] = result.coverage_report_path
        return paths

    def run_review_report(
        self,
        _context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = generate_review_report_from_validated_suite_artifact(artifacts["validated_test_suite"])
        return {
            "review_report": result.report_path,
            "review_report_metadata": result.metadata_path,
        }

    def run_executor_export(
        self,
        _context: PipelineRunContext,
        artifacts: dict[str, Path],
    ) -> dict[str, Path]:
        result = export_tests_from_validated_suite_artifact(artifacts["validated_test_suite"])
        paths = {"executor_export_package": result.export_package_path}
        if result.tests_path is not None:
            paths["executor_tests"] = result.tests_path
        return paths


def _validate_document_collection(path: Path) -> None:
    data = _read_json_mapping(path)
    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise SchemaValidationError("documents.project_id is required")
    raw_documents = data.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise SchemaValidationError("documents must be a non-empty list")
    document_ids: set[str] = set()
    for index, raw_document in enumerate(raw_documents):
        document = Document.from_dict(raw_document)
        if document.project_id != project_id:
            raise SchemaValidationError(f"documents[{index}].project_id must match collection project_id")
        if document.document_id in document_ids:
            raise SchemaValidationError(f"duplicate document_id: {document.document_id}")
        document_ids.add(document.document_id)


STAGE_SPECS = (
    StageSpec(
        "C03_project_config",
        "run_project_config",
        (
            ArtifactSpec("project_config", "00_project_config", "project_config", ProjectConfig),
        ),
    ),
    StageSpec(
        "C04_document_ingestion",
        "run_document_ingestion",
        (
            ArtifactSpec("documents", "01_documents", "documents", validator=_validate_document_collection),
        ),
    ),
    StageSpec(
        "C05_source_ledger",
        "run_source_ledger",
        (
            ArtifactSpec("source_package", "02_source_package", "source_package", SourcePackage),
        ),
    ),
    StageSpec("C06_skill_runtime", None, ()),
    StageSpec(
        "C07_requirement_extraction",
        "run_requirement_extraction",
        (
            ArtifactSpec(
                "candidate_requirement_package",
                "03_candidate_requirements",
                "candidate_requirement_package",
                CandidateRequirementPackage,
            ),
        ),
    ),
    StageSpec(
        "C08_requirement_atomization",
        "run_requirement_atomization",
        (
            ArtifactSpec(
                "atomic_requirement_ledger",
                "04_atomic_requirements",
                "atomic_requirement_ledger",
                AtomicRequirementLedger,
            ),
        ),
    ),
    StageSpec(
        "C09_requirement_governance",
        "run_requirement_governance",
        (
            ArtifactSpec(
                "governed_requirement_ledger",
                "05_governed_requirements",
                "governed_requirement_ledger",
                GovernedRequirementLedger,
            ),
        ),
    ),
    StageSpec(
        "C10_obligation_planning",
        "run_obligation_planning",
        (
            ArtifactSpec(
                "test_obligation_ledger",
                "06_test_obligations",
                "test_obligation_ledger",
                TestObligationLedger,
            ),
        ),
    ),
    StageSpec(
        "C11_test_generation",
        "run_test_generation",
        (
            ArtifactSpec("draft_test_suite", "07_draft_tests", "draft_test_suite", DraftTestSuite),
        ),
    ),
    StageSpec(
        "C12_test_validation_coverage",
        "run_test_validation_coverage",
        (
            ArtifactSpec(
                "validated_test_suite",
                "08_validated_tests",
                "validated_test_suite",
                ValidatedTestSuite,
            ),
            ArtifactSpec("coverage_report", "08_validated_tests", "coverage_report", CoverageReport),
        ),
    ),
    StageSpec(
        "C13_review_report",
        "run_review_report",
        (
            ArtifactSpec("review_report", "09_review_report", "review_report", suffix=".md"),
            ArtifactSpec(
                "review_report_metadata",
                "09_review_report",
                "review_report_metadata",
                ReviewReportMetadata,
            ),
        ),
    ),
    StageSpec(
        "C14_executor_export",
        "run_executor_export",
        (
            ArtifactSpec("executor_tests", "10_executor_export", "tests"),
            ArtifactSpec(
                "executor_export_package",
                "10_executor_export",
                "executor_export_package",
                ExecutorExportPackage,
            ),
        ),
    ),
)


def run_pipeline(
    config_path: str | Path,
    run_id: str,
    *,
    artifact_root: str | Path | None = None,
    components: Any | None = None,
    options: PipelineRunOptions | None = None,
    source_base_dir: str | Path | None = None,
) -> PipelineRunResult:
    config_file = Path(config_path)
    project_config = load_project_config(config_file)
    effective_artifact_root = Path(artifact_root or project_config.artifact_root or "artifacts")
    context = PipelineRunContext(
        config_path=config_file,
        project_config=project_config,
        run_id=run_id,
        artifact_root=effective_artifact_root,
        source_base_dir=Path(source_base_dir) if source_base_dir is not None else config_file.parent,
        options=options or PipelineRunOptions(),
    )
    active_components = components or DefaultPipelineComponents()
    state_path = _pipeline_state_path(context.artifact_root, project_config.project_id, run_id)
    existing_state: PipelineRunState | None = None
    if context.options.resume:
        existing_state = _validate_existing_pipeline_state(context)
    completed_stages: list[str] = []
    artifacts: dict[str, Path] = {}
    artifact_path_records: dict[str, str] = {}
    resume_artifact_path_records = dict(existing_state.artifact_paths) if existing_state is not None else {}

    state = _build_state(
        context,
        status=PipelineRunStatus.RUNNING,
        current_stage="C03_project_config",
        completed_stages=completed_stages,
        artifact_paths=artifact_path_records,
    )
    _write_pipeline_state(context, state)

    for stage in _selected_stage_specs(context.options):
        try:
            checkpoint_paths = _stage_checkpoint_paths(context, stage, resume_artifact_path_records)
            if checkpoint_paths is not None:
                _validate_stage_outputs(context, stage, checkpoint_paths, artifacts)
                _record_stage_outputs(context, stage, checkpoint_paths, artifacts, artifact_path_records)
            else:
                stage_paths = _run_stage(active_components, context, stage, artifacts)
                _validate_stage_outputs(context, stage, stage_paths, artifacts)
                _record_stage_outputs(context, stage, stage_paths, artifacts, artifact_path_records)
            _record_completed_stage(completed_stages, stage.stage_id)
            state = _build_state(
                context,
                status=PipelineRunStatus.RUNNING,
                current_stage=stage.stage_id,
                completed_stages=completed_stages,
                artifact_paths=artifact_path_records,
            )
            _write_pipeline_state(context, state)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            failed_state = _build_state(
                context,
                status=PipelineRunStatus.FAILED,
                current_stage=stage.stage_id,
                completed_stages=completed_stages,
                artifact_paths=artifact_path_records,
                failed_stage=stage.stage_id,
                error=error,
            )
            _write_pipeline_state(context, failed_state)
            raise PipelineOrchestrationError(f"{stage.stage_id} failed: {error}") from exc

    _record_completed_stage(completed_stages, "C15_orchestrator")
    final_state = _build_state(
        context,
        status=PipelineRunStatus.SUCCEEDED,
        current_stage="C15_orchestrator",
        completed_stages=completed_stages,
        artifact_paths=artifact_path_records,
    )
    _write_pipeline_state(context, final_state)
    return PipelineRunResult(
        state=final_state,
        state_path=state_path,
        artifact_paths=dict(artifacts),
    )


def _run_stage(
    components: Any,
    context: PipelineRunContext,
    stage: StageSpec,
    artifacts: dict[str, Path],
) -> dict[str, Path]:
    if stage.runner_name is None:
        return {}
    runner = getattr(components, stage.runner_name, None)
    if runner is None:
        raise PipelineComponentError(f"Required component runner is not implemented: {stage.runner_name}")
    pre_existing_paths = _existing_stage_output_paths(context, stage)
    try:
        result = runner(context, dict(artifacts))
    except Exception as exc:
        raise PipelineComponentError(str(exc) or exc.__class__.__name__) from exc
    if not isinstance(result, dict):
        raise PipelineComponentError(f"{stage.runner_name} must return a mapping of artifact keys to paths")
    return _validate_runner_result(context, stage, result, pre_existing_paths)


def _validate_runner_result(
    context: PipelineRunContext,
    stage: StageSpec,
    result: dict[Any, Any],
    pre_existing_paths: set[Path],
) -> dict[str, Path]:
    output_paths: dict[str, Path] = {}
    for spec in stage.outputs:
        if spec.key not in result:
            raise PipelineComponentError(f"{stage.runner_name} did not return expected artifact key: {spec.key}")
        output_paths[spec.key] = _coerce_returned_artifact_path(stage, spec, result[spec.key])
        _validate_stage_artifact_path(
            context,
            stage,
            spec,
            output_paths[spec.key],
            pre_existing_paths=pre_existing_paths,
        )
    return output_paths


def _coerce_returned_artifact_path(stage: StageSpec, spec: ArtifactSpec, value: Any) -> Path:
    if not isinstance(value, (str, PathLike)):
        raise PipelineComponentError(
            f"{stage.runner_name} returned {spec.key} as {type(value).__name__}; expected a path"
        )
    path = Path(value)
    if not str(path):
        raise PipelineComponentError(f"{stage.runner_name} returned an empty path for {spec.key}")
    return path


def _validate_stage_artifact_path(
    context: PipelineRunContext,
    stage: StageSpec,
    spec: ArtifactSpec,
    path: Path,
    *,
    pre_existing_paths: set[Path] | None = None,
) -> None:
    if not path.exists():
        raise PipelineCheckpointError(f"Returned artifact path for {spec.key} does not exist: {path}")

    root = Path(context.artifact_root).resolve(strict=False)
    target = path.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PipelineCheckpointError(f"Returned artifact path for {spec.key} must stay inside artifact root") from exc

    expected_parent = (
        Path(context.artifact_root)
        / context.project_config.project_id
        / context.run_id
        / spec.stage
    ).resolve(strict=False)
    if target.parent != expected_parent:
        raise PipelineCheckpointError(
            f"Returned artifact path for {spec.key} must be under stage {spec.stage}: {path}"
        )

    if not _artifact_file_name_matches(spec, target.name):
        raise PipelineCheckpointError(
            f"Returned artifact path for {spec.key} must point to {spec.artifact_name}{spec.suffix}: {path}"
        )

    if (
        pre_existing_paths is not None
        and spec.suffix == ".json"
        and target in pre_existing_paths
    ):
        raise PipelineCheckpointError(f"Returned artifact path for {spec.key} is stale: {path}")


def _artifact_file_name_matches(spec: ArtifactSpec, file_name: str) -> bool:
    if spec.suffix != ".json":
        return file_name == f"{spec.artifact_name}{spec.suffix}"
    if file_name == f"{spec.artifact_name}.json":
        return True
    prefix = f"{spec.artifact_name}.v"
    if not file_name.startswith(prefix) or not file_name.endswith(".json"):
        return False
    version = file_name[len(prefix):-len(".json")]
    return version.isdecimal() and int(version) > 1


def _existing_stage_output_paths(context: PipelineRunContext, stage: StageSpec) -> set[Path]:
    existing: set[Path] = set()
    for spec in stage.outputs:
        stage_dir = (
            Path(context.artifact_root)
            / context.project_config.project_id
            / context.run_id
            / spec.stage
        )
        if not stage_dir.exists():
            continue
        for path in stage_dir.iterdir():
            if path.is_file() and _artifact_file_name_matches(spec, path.name):
                existing.add(path.resolve(strict=False))
    return existing


def _selected_stage_specs(options: PipelineRunOptions) -> tuple[StageSpec, ...]:
    return tuple(
        stage
        for stage in STAGE_SPECS
        if (stage.stage_id != "C13_review_report" or options.include_review)
        and (stage.stage_id != "C14_executor_export" or options.include_export)
    )


def _record_completed_stage(completed_stages: list[str], stage_id: str) -> None:
    if len(completed_stages) >= len(PIPELINE_RUN_STAGES):
        return
    if PIPELINE_RUN_STAGES[len(completed_stages)] == stage_id:
        completed_stages.append(stage_id)


def _stage_checkpoint_paths(
    context: PipelineRunContext,
    stage: StageSpec,
    artifact_path_records: dict[str, str],
) -> dict[str, Path] | None:
    if not context.options.resume:
        return None
    if not stage.outputs:
        return {}

    recorded_paths = _recorded_stage_output_paths(context, stage, artifact_path_records)
    if recorded_paths:
        return recorded_paths

    paths = {spec.key: _artifact_path(context, spec) for spec in stage.outputs}
    existing = [path.exists() for path in paths.values()]
    if not any(existing):
        return None
    if not all(existing):
        missing = [
            spec.key
            for spec, exists in zip(stage.outputs, existing)
            if not exists
        ]
        raise PipelineCheckpointError(f"Partial checkpoint for {stage.stage_id}; missing: {', '.join(missing)}")
    return paths


def _recorded_stage_output_paths(
    context: PipelineRunContext,
    stage: StageSpec,
    artifact_path_records: dict[str, str],
) -> dict[str, Path]:
    recorded = {
        spec.key: _artifact_path_from_record(context.artifact_root, artifact_path_records[spec.key])
        for spec in stage.outputs
        if spec.key in artifact_path_records
    }
    if not recorded:
        return {}
    if len(recorded) != len(stage.outputs):
        missing = [spec.key for spec in stage.outputs if spec.key not in recorded]
        raise PipelineCheckpointError(
            f"Partial recorded checkpoint for {stage.stage_id}; missing: {', '.join(missing)}"
        )
    return recorded


def _validate_stage_outputs(
    context: PipelineRunContext,
    stage: StageSpec,
    stage_paths: dict[str, Path],
    artifacts: dict[str, Path],
) -> None:
    combined_artifacts = {**artifacts, **stage_paths}
    for spec in stage.outputs:
        path = stage_paths.get(spec.key)
        if path is None:
            raise PipelineCheckpointError(f"Expected artifact path missing for {spec.key}")
        _validate_stage_artifact_path(context, stage, spec, path)
        try:
            _validate_artifact(path, spec)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            raise PipelineCheckpointError(f"Invalid checkpoint artifact {path}: {error}") from exc
    _validate_cross_artifact_links(stage, combined_artifacts)


def _record_stage_outputs(
    context: PipelineRunContext,
    stage: StageSpec,
    stage_paths: dict[str, Path],
    artifacts: dict[str, Path],
    artifact_path_records: dict[str, str],
) -> None:
    for spec in stage.outputs:
        path = stage_paths[spec.key]
        artifacts[spec.key] = path
        artifact_path_records[spec.key] = _recorded_artifact_path(context.artifact_root, path)


def _artifact_path(context: PipelineRunContext, spec: ArtifactSpec) -> Path:
    store = ArtifactStore(context.artifact_root)
    path = store.artifact_path(
        context.project_config.project_id,
        context.run_id,
        spec.stage,
        spec.artifact_name,
    )
    if spec.suffix != ".json":
        path = path.with_suffix(spec.suffix)
    return path


def _validate_artifact(path: Path, spec: ArtifactSpec) -> None:
    if spec.validator is not None:
        spec.validator(path)
        return
    if spec.model_type is not None:
        spec.model_type.from_dict(_read_json_mapping(path))
        return
    if spec.suffix == ".json":
        _read_json_mapping(path)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PipelineCheckpointError("artifact JSON must be a mapping")
    return data


def _load_artifact_model(
    artifacts: dict[str, Path],
    artifact_key: str,
    model_type: type[SchemaModel],
) -> SchemaModel:
    path = artifacts.get(artifact_key)
    if path is None:
        raise PipelineCheckpointError(f"Expected artifact path missing for {artifact_key}")
    return model_type.from_dict(_read_json_mapping(path))


def _validate_cross_artifact_links(stage: StageSpec, artifacts: dict[str, Path]) -> None:
    if stage.stage_id == "C10_obligation_planning":
        governed = _load_governed_requirement_ledger(artifacts)
        obligations = _load_test_obligation_ledger(artifacts)
        validate_obligation_links(obligations.obligations, governed.requirements)
    elif stage.stage_id == "C11_test_generation":
        governed = _load_governed_requirement_ledger(artifacts)
        obligations = _load_test_obligation_ledger(artifacts)
        draft_suite = _load_draft_test_suite(artifacts)
        validate_test_case_links(draft_suite.test_cases, governed.requirements, obligations.obligations)
    elif stage.stage_id == "C12_test_validation_coverage":
        governed = _load_governed_requirement_ledger(artifacts)
        obligations = _load_test_obligation_ledger(artifacts)
        validated_suite = _load_validated_test_suite(artifacts)
        validate_test_case_links(validated_suite.test_cases, governed.requirements, obligations.obligations)
    elif stage.stage_id == "C14_executor_export":
        validated_suite = _load_validated_test_suite(artifacts)
        export_package = _load_executor_export_package(artifacts)
        validate_executor_export_package(export_package, validated_suite)


def _load_governed_requirement_ledger(artifacts: dict[str, Path]) -> GovernedRequirementLedger:
    return _load_artifact_model(
        artifacts,
        "governed_requirement_ledger",
        GovernedRequirementLedger,
    )


def _load_test_obligation_ledger(artifacts: dict[str, Path]) -> TestObligationLedger:
    return _load_artifact_model(
        artifacts,
        "test_obligation_ledger",
        TestObligationLedger,
    )


def _load_draft_test_suite(artifacts: dict[str, Path]) -> DraftTestSuite:
    return _load_artifact_model(
        artifacts,
        "draft_test_suite",
        DraftTestSuite,
    )


def _load_validated_test_suite(artifacts: dict[str, Path]) -> ValidatedTestSuite:
    return _load_artifact_model(
        artifacts,
        "validated_test_suite",
        ValidatedTestSuite,
    )


def _load_executor_export_package(artifacts: dict[str, Path]) -> ExecutorExportPackage:
    return _load_artifact_model(
        artifacts,
        "executor_export_package",
        ExecutorExportPackage,
    )


def _build_state(
    context: PipelineRunContext,
    *,
    status: PipelineRunStatus,
    current_stage: str,
    completed_stages: list[str],
    artifact_paths: dict[str, str],
    failed_stage: str | None = None,
    error: str | None = None,
) -> PipelineRunState:
    return PipelineRunState.from_dict(
        {
            "pipeline_run_id": PIPELINE_RUN_ID,
            "project_id": context.project_config.project_id,
            "run_id": context.run_id,
            "status": status.value,
            "current_stage": current_stage,
            "artifact_paths": dict(artifact_paths),
            "completed_stages": list(completed_stages),
            **({"failed_stage": failed_stage} if failed_stage is not None else {}),
            **({"error": error} if error is not None else {}),
        }
    )


def _pipeline_state_path(artifact_root: Path, project_id: str, run_id: str) -> Path:
    store = ArtifactStore(artifact_root)
    return store.run_artifact_path(project_id, run_id, PIPELINE_RUN_STATE_ARTIFACT_NAME)


def _write_pipeline_state(context: PipelineRunContext, state: PipelineRunState) -> None:
    store = ArtifactStore(context.artifact_root)
    store.write_run_json(
        context.project_config.project_id,
        context.run_id,
        PIPELINE_RUN_STATE_ARTIFACT_NAME,
        state,
        replace=True,
    )


def _validate_existing_pipeline_state(context: PipelineRunContext) -> PipelineRunState | None:
    store = ArtifactStore(context.artifact_root)
    state_path = store.run_artifact_path(
        context.project_config.project_id,
        context.run_id,
        PIPELINE_RUN_STATE_ARTIFACT_NAME,
    )
    if not state_path.exists():
        return None

    try:
        state = store.load_run_model(
            PipelineRunState,
            context.project_config.project_id,
            context.run_id,
            PIPELINE_RUN_STATE_ARTIFACT_NAME,
        )
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        raise PipelineCheckpointError(f"Invalid existing pipeline run state: {error}") from exc

    for artifact_key, recorded_path in state.artifact_paths.items():
        artifact_path = _artifact_path_from_record(context.artifact_root, recorded_path)
        if not artifact_path.exists():
            stage_id = _stage_id_for_artifact_key(artifact_key)
            raise PipelineCheckpointError(
                f"Existing pipeline state references missing artifact {artifact_key} for {stage_id}: {recorded_path}"
            )
    return state


def _artifact_path_from_record(artifact_root: Path, recorded_path: str) -> Path:
    parts = PurePosixPath(recorded_path).parts
    if len(parts) < 2 or parts[0] != "artifacts":
        raise PipelineCheckpointError(f"Invalid recorded artifact path: {recorded_path}")

    path = Path(artifact_root).joinpath(*parts[1:])
    root = Path(artifact_root).resolve(strict=False)
    target = path.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PipelineCheckpointError(f"Recorded artifact path escapes artifact root: {recorded_path}") from exc
    return path


def _stage_id_for_artifact_key(artifact_key: str) -> str:
    for stage in STAGE_SPECS:
        if any(spec.key == artifact_key for spec in stage.outputs):
            return stage.stage_id
    return "unknown_stage"


def _recorded_artifact_path(artifact_root: Path, path: Path) -> str:
    relative = path.resolve(strict=False).relative_to(artifact_root.resolve(strict=False))
    return Path("artifacts", *relative.parts).as_posix()
