import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.orchestrator as orchestrator
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.codex_cli_adapter import CODEX_CLI_ADAPTER_NAME
from ai_testgen.orchestrator import PipelineOrchestrationError, PipelineRunOptions, run_pipeline
from ai_testgen.schemas import PIPELINE_RUN_STAGES, PipelineRunState, ProjectConfig


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "orchestrator"


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def project_config_data(artifact_root: Path) -> dict:
    return {
        "project_id": "demo_chatbot",
        "bot_name": "Demo Support Bot",
        "target_url": "https://example.test/chat",
        "coverage_policy": {
            "require_negative_tests": True,
            "require_positive_tests": True,
        },
        "approval_policy": {
            "allow_export_without_review": False,
            "require_human_approval_for_inferred": True,
        },
        "artifact_root": str(artifact_root),
        "source_paths": ["requirements.md"],
    }


def source_ref() -> dict:
    return {"document_id": "doc_001", "chunk_id": "chunk_001"}


def document_data() -> dict:
    return {
        "document_id": "doc_001",
        "project_id": "demo_chatbot",
        "source_path": "requirements.md",
        "title": "Requirements",
        "content_checksum": "sha256:doc001",
        "ingestion_status": "loaded",
        "content_type": "text/markdown",
    }


def source_chunk_data() -> dict:
    return {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "The bot must ask for an order number before showing order status.",
        "checksum": "sha256:chunk001",
        "processing_status": "not_processed",
    }


def source_package_data() -> dict:
    return {
        "source_package_id": "source_pkg_001",
        "project_id": "demo_chatbot",
        "document_ids": ["doc_001"],
        "chunks": [source_chunk_data()],
        "checksum": "sha256:sourcepkg",
    }


def candidate_package_data() -> dict:
    return {
        "candidate_package_id": "cand_pkg_001",
        "project_id": "demo_chatbot",
        "source_package_id": "source_pkg_001",
        "candidates": [
            {
                "candidate_id": "cand_001",
                "statement": "The bot must ask for an order number before showing order status.",
                "requirement_type_guess": "functional",
                "source_refs": [source_ref()],
                "confidence": 0.91,
            }
        ],
    }


def atomic_requirement_data(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot asks for an order number before showing order status.",
        "requirement_type": "functional",
        "status": "validated",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
    }
    data.update(overrides)
    return data


def atomic_ledger_data() -> dict:
    return {
        "atomic_ledger_id": "atomic_ledger_001",
        "project_id": "demo_chatbot",
        "candidate_package_id": "cand_pkg_001",
        "requirements": [atomic_requirement_data()],
    }


def governed_ledger_data() -> dict:
    return {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": [atomic_requirement_data()],
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": 1,
        },
    }


def obligation_ledger_data() -> dict:
    return {
        "obligation_ledger_id": "obl_ledger_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligations": [
            {
                "obligation_id": "obl_001",
                "requirement_id": "req_001",
                "obligation_type": "positive",
                "status": "planned",
                "source_refs": [source_ref()],
            }
        ],
    }


def turn_data() -> dict:
    return {"turn_id": "turn_001", "speaker": "user", "text": "Where is my order?"}


def assertion_data() -> dict:
    return {
        "assertion_id": "assert_001",
        "assertion_type": "bot_response_contains_request",
        "target": "bot.final_response",
        "expected": "The bot asks for the order number before providing status.",
    }


def case_data(**overrides: object) -> dict:
    data = {
        "test_case_id": "tc_001",
        "title": "Order status requires order number",
        "status": "draft",
        "requirement_ids": ["req_001"],
        "obligation_ids": ["obl_001"],
        "source_refs": [source_ref()],
        "turns": [turn_data()],
        "assertions": [assertion_data()],
    }
    data.update(overrides)
    return data


def draft_suite_data() -> dict:
    return {
        "draft_suite_id": "draft_suite_001",
        "project_id": "demo_chatbot",
        "obligation_ledger_id": "obl_ledger_001",
        "test_cases": [case_data()],
    }


def validated_suite_data() -> dict:
    return {
        "validated_suite_id": "validated_suite_001",
        "project_id": "demo_chatbot",
        "draft_suite_id": "draft_suite_001",
        "test_cases": [case_data(status="valid", export_eligible=True)],
        "validation_summary": {
            "export_eligible": 1,
            "needs_review": 0,
            "rejected": 0,
            "valid": 1,
        },
    }


def coverage_report_data() -> dict:
    return {
        "coverage_report_id": "coverage_001",
        "project_id": "demo_chatbot",
        "validated_suite_id": "validated_suite_001",
        "requirement_counts": {"covered": 1, "total": 1, "uncovered": 0},
        "obligation_counts": {"blocked": 0, "covered": 1, "total": 1},
        "test_counts": {"export_eligible": 1, "rejected": 0, "total": 1},
        "source_chunk_counts": {"total": 1, "with_requirements": 1, "without_requirements": 0},
    }


def review_metadata_data() -> dict:
    return {
        "review_report_id": "review_001",
        "project_id": "demo_chatbot",
        "governed_ledger_id": "gov_ledger_001",
        "obligation_ledger_id": "obl_ledger_001",
        "validated_suite_id": "validated_suite_001",
        "coverage_report_id": "coverage_001",
        "report_path": "artifacts/demo_chatbot/run_001/09_review_report/review_report.md",
    }


def export_package_data() -> dict:
    return {
        "export_package_id": "export_001",
        "project_id": "demo_chatbot",
        "validated_suite_id": "validated_suite_001",
        "exported_test_case_ids": ["tc_001"],
        "format": "json",
        "output_paths": ["artifacts/demo_chatbot/run_001/10_executor_export/tests.json"],
        "eligibility_summary": {"eligible": 1, "excluded": 0},
    }


def write_config(path: Path, artifact_root: Path) -> None:
    path.write_text(stable_json(project_config_data(artifact_root)), encoding="utf-8")


def stage_calls(components) -> list[str]:
    return [stage_id for stage_id, _artifacts in components.calls]


def artifact_path_from_record(artifact_root: Path, recorded_path: str) -> Path:
    parts = recorded_path.split("/")
    assert parts[0] == "artifacts"
    return artifact_root.joinpath(*parts[1:])


class FakePipelineComponents:
    def __init__(self, *, fail_stage: str | None = None) -> None:
        self.fail_stage = fail_stage
        self.calls: list[tuple[str, dict[str, Path]]] = []

    def run_project_config(self, context, artifacts):
        return self._write_stage(context, artifacts, "C03_project_config", [
            ("00_project_config", "project_config", context.project_config.to_dict()),
        ])

    def run_document_ingestion(self, context, artifacts):
        return self._write_stage(context, artifacts, "C04_document_ingestion", [
            ("01_documents", "documents", {"project_id": "demo_chatbot", "documents": [document_data()]}),
        ])

    def run_source_ledger(self, context, artifacts):
        assert set(artifacts) >= {"project_config", "documents"}
        return self._write_stage(context, artifacts, "C05_source_ledger", [
            ("02_source_package", "source_package", source_package_data()),
        ])

    def run_requirement_extraction(self, context, artifacts):
        assert "source_package" in artifacts
        return self._write_stage(context, artifacts, "C07_requirement_extraction", [
            ("03_candidate_requirements", "candidate_requirement_package", candidate_package_data()),
        ])

    def run_requirement_atomization(self, context, artifacts):
        assert "candidate_requirement_package" in artifacts
        return self._write_stage(context, artifacts, "C08_requirement_atomization", [
            ("04_atomic_requirements", "atomic_requirement_ledger", atomic_ledger_data()),
        ])

    def run_requirement_governance(self, context, artifacts):
        assert "atomic_requirement_ledger" in artifacts
        return self._write_stage(context, artifacts, "C09_requirement_governance", [
            ("05_governed_requirements", "governed_requirement_ledger", governed_ledger_data()),
        ])

    def run_obligation_planning(self, context, artifacts):
        assert "governed_requirement_ledger" in artifacts
        return self._write_stage(context, artifacts, "C10_obligation_planning", [
            ("06_test_obligations", "test_obligation_ledger", obligation_ledger_data()),
        ])

    def run_test_generation(self, context, artifacts):
        assert "test_obligation_ledger" in artifacts
        return self._write_stage(context, artifacts, "C11_test_generation", [
            ("07_draft_tests", "draft_test_suite", draft_suite_data()),
        ])

    def run_test_validation_coverage(self, context, artifacts):
        assert "draft_test_suite" in artifacts
        return self._write_stage(context, artifacts, "C12_test_validation_coverage", [
            ("08_validated_tests", "validated_test_suite", validated_suite_data()),
            ("08_validated_tests", "coverage_report", coverage_report_data()),
        ])

    def run_review_report(self, context, artifacts):
        assert set(artifacts) >= {"validated_test_suite", "coverage_report"}
        outputs = self._write_stage(context, artifacts, "C13_review_report", [
            ("09_review_report", "review_report_metadata", review_metadata_data()),
        ])
        report_path = (
            Path(context.artifact_root)
            / context.project_config.project_id
            / context.run_id
            / "09_review_report"
            / "review_report.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# Review Report\n", encoding="utf-8")
        outputs["review_report"] = report_path
        return outputs

    def run_executor_export(self, context, artifacts):
        assert "validated_test_suite" in artifacts
        outputs = self._write_stage(context, artifacts, "C14_executor_export", [
            ("10_executor_export", "tests", {"format_version": "executor_json_v1", "tests": []}),
            ("10_executor_export", "executor_export_package", export_package_data()),
        ])
        outputs["executor_tests"] = outputs.pop("tests")
        return outputs

    def _write_stage(self, context, artifacts, stage_id: str, outputs: list[tuple[str, str, dict]]) -> dict[str, Path]:
        self.calls.append((stage_id, dict(artifacts)))
        if self.fail_stage == stage_id:
            raise RuntimeError(f"boom in {stage_id}")
        store = ArtifactStore(context.artifact_root)
        written: dict[str, Path] = {}
        for stage, artifact_name, data in outputs:
            artifact = store.write_json(
                context.project_config.project_id,
                context.run_id,
                stage,
                artifact_name,
                data,
            )
            written[artifact_name] = artifact.path
        return written


def test_run_pipeline_happy_path_uses_components_in_order_and_persists_final_state(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()

    result = run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == [
        "C03_project_config",
        "C04_document_ingestion",
        "C05_source_ledger",
        "C07_requirement_extraction",
        "C08_requirement_atomization",
        "C09_requirement_governance",
        "C10_obligation_planning",
        "C11_test_generation",
        "C12_test_validation_coverage",
        "C13_review_report",
        "C14_executor_export",
    ]
    assert result.state.status == "succeeded"
    assert result.state.current_stage == "C15_orchestrator"
    assert result.state.completed_stages == PIPELINE_RUN_STAGES
    assert result.state_path == artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    persisted = PipelineRunState.from_dict(json.loads(result.state_path.read_text(encoding="utf-8")))
    assert persisted == result.state
    store = ArtifactStore(artifact_root)
    assert result.state_path == store.run_artifact_path("demo_chatbot", "run_001", "pipeline_run_state")
    assert store.load_run_model(PipelineRunState, "demo_chatbot", "run_001", "pipeline_run_state") == result.state
    assert stable_json(result.state.to_dict()) == (GOLDEN_DIR / "pipeline_run_state.json").read_text(
        encoding="utf-8"
    )


def test_default_pipeline_components_pass_skill_adapter_to_skill_required_stages(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    context = orchestrator.PipelineRunContext(
        config_path=config_path,
        project_config=ProjectConfig.from_dict(project_config_data(artifact_root)),
        run_id="run_001",
        artifact_root=artifact_root,
        source_base_dir=tmp_path,
        options=PipelineRunOptions(skill_adapter=CODEX_CLI_ADAPTER_NAME),
    )
    source_path = artifact_root / "demo_chatbot" / "run_001" / "02_source_package" / "source_package.json"
    candidate_path = artifact_root / "demo_chatbot" / "run_001" / "03_candidate_requirements" / "candidate_requirement_package.json"
    obligation_path = artifact_root / "demo_chatbot" / "run_001" / "06_test_obligations" / "test_obligation_ledger.json"
    calls = []

    def fake_extract(source_package, skill_definition=None, *, skill_adapter=None):
        calls.append(("C07", source_package, skill_definition, skill_adapter))
        return SimpleNamespace(candidate_package_path=candidate_path)

    def fake_atomize(candidates, skill_definition=None, *, skill_adapter=None):
        calls.append(("C08", candidates, skill_definition, skill_adapter))
        return SimpleNamespace(atomic_ledger_path=artifact_root / "atomic.json")

    def fake_generate(
        obligations,
        test_case_writer_skill_definition=None,
        oracle_generator_skill_definition=None,
        *,
        skill_adapter=None,
    ):
        calls.append(
            (
                "C11",
                obligations,
                test_case_writer_skill_definition,
                oracle_generator_skill_definition,
                skill_adapter,
            )
        )
        return SimpleNamespace(draft_suite_path=artifact_root / "draft.json")

    monkeypatch.setattr(orchestrator, "extract_requirements_from_source_package_artifact", fake_extract)
    monkeypatch.setattr(orchestrator, "atomize_requirements_from_candidate_package_artifact", fake_atomize)
    monkeypatch.setattr(orchestrator, "generate_tests_from_obligation_ledger_artifact", fake_generate)

    components = orchestrator.DefaultPipelineComponents()
    components.run_requirement_extraction(context, {"source_package": source_path})
    components.run_requirement_atomization(context, {"candidate_requirement_package": candidate_path})
    components.run_test_generation(context, {"test_obligation_ledger": obligation_path})

    assert calls == [
        ("C07", source_path, None, CODEX_CLI_ADAPTER_NAME),
        ("C08", candidate_path, None, CODEX_CLI_ADAPTER_NAME),
        ("C11", obligation_path, None, None, CODEX_CLI_ADAPTER_NAME),
    ]


def test_run_pipeline_resumes_from_existing_valid_checkpoints(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    first_components = FakePipelineComponents()
    run_pipeline(config_path, run_id="run_001", components=first_components)

    second_components = FakePipelineComponents()
    result = run_pipeline(config_path, run_id="run_001", components=second_components)

    assert second_components.calls == []
    assert result.state.status == "succeeded"
    assert result.state.completed_stages == PIPELINE_RUN_STAGES


def test_run_pipeline_resume_false_attempts_to_rerun_existing_checkpoints(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    first_components = FakePipelineComponents()
    run_pipeline(config_path, run_id="run_001", components=first_components)

    second_components = FakePipelineComponents()
    result = run_pipeline(
        config_path,
        run_id="run_001",
        components=second_components,
        options=PipelineRunOptions(resume=False),
    )

    assert stage_calls(second_components) == stage_calls(first_components)
    assert result.state.status == "succeeded"


def test_run_pipeline_resume_false_records_new_versioned_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    first_components = FakePipelineComponents()
    run_pipeline(config_path, run_id="run_001", components=first_components)

    second_components = FakePipelineComponents()
    result = run_pipeline(
        config_path,
        run_id="run_001",
        components=second_components,
        options=PipelineRunOptions(resume=False),
    )

    assert "C03_project_config" in stage_calls(second_components)
    recorded = result.state.artifact_paths["project_config"]
    assert recorded.endswith("/00_project_config/project_config.v2.json")
    assert not recorded.endswith("/00_project_config/project_config.json")
    actual_path = artifact_path_from_record(artifact_root, recorded)
    assert actual_path.exists()
    assert ProjectConfig.from_dict(json.loads(actual_path.read_text(encoding="utf-8")))
    assert second_components.calls[1][1]["project_config"] == actual_path


def test_run_pipeline_skip_review_omits_c13_but_keeps_export(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()

    result = run_pipeline(
        config_path,
        run_id="run_001",
        components=components,
        options=PipelineRunOptions(include_review=False),
    )

    assert "C13_review_report" not in stage_calls(components)
    assert "C14_executor_export" in stage_calls(components)
    assert "review_report" not in result.artifact_paths
    assert "review_report_metadata" not in result.artifact_paths
    assert "executor_export_package" in result.artifact_paths
    assert result.state.completed_stages == PIPELINE_RUN_STAGES[:10]


def test_run_pipeline_skip_export_omits_c14(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()

    result = run_pipeline(
        config_path,
        run_id="run_001",
        components=components,
        options=PipelineRunOptions(include_export=False),
    )

    assert "C13_review_report" in stage_calls(components)
    assert "C14_executor_export" not in stage_calls(components)
    assert "review_report_metadata" in result.artifact_paths
    assert "executor_export_package" not in result.artifact_paths
    assert result.state.completed_stages == PIPELINE_RUN_STAGES[:11]


def test_run_pipeline_skip_review_and_export_stops_after_c12(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()

    result = run_pipeline(
        config_path,
        run_id="run_001",
        components=components,
        options=PipelineRunOptions(include_review=False, include_export=False),
    )

    assert "C13_review_report" not in stage_calls(components)
    assert "C14_executor_export" not in stage_calls(components)
    assert "review_report_metadata" not in result.artifact_paths
    assert "executor_export_package" not in result.artifact_paths
    assert result.state.completed_stages == PIPELINE_RUN_STAGES[:10]


def test_run_pipeline_stops_on_failure_and_records_failed_stage(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents(fail_stage="C08_requirement_atomization")

    with pytest.raises(PipelineOrchestrationError, match="C08_requirement_atomization"):
        run_pipeline(config_path, run_id="run_001", components=components)

    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    state = PipelineRunState.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
    assert state.status == "failed"
    assert state.current_stage == "C08_requirement_atomization"
    assert state.failed_stage == "C08_requirement_atomization"
    assert state.completed_stages == [
        "C03_project_config",
        "C04_document_ingestion",
        "C05_source_ledger",
        "C06_skill_runtime",
        "C07_requirement_extraction",
    ]
    assert "boom in C08_requirement_atomization" in state.error
    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "05_governed_requirements"
        / "governed_requirement_ledger.json"
    ).exists()


def test_run_pipeline_rejects_invalid_resume_checkpoint_before_calling_component(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()
    store = ArtifactStore(artifact_root)
    store.write_json("demo_chatbot", "run_001", "00_project_config", "project_config", project_config_data(artifact_root))
    store.write_json(
        "demo_chatbot",
        "run_001",
        "01_documents",
        "documents",
        {"project_id": "demo_chatbot", "documents": [document_data()]},
    )
    store.write_json("demo_chatbot", "run_001", "02_source_package", "source_package", {"bad": True})

    with pytest.raises(PipelineOrchestrationError, match="C05_source_ledger"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == []
    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    state = PipelineRunState.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
    assert state.status == "failed"
    assert state.failed_stage == "C05_source_ledger"


def test_run_pipeline_rejects_existing_state_with_missing_recorded_artifact(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = FakePipelineComponents()
    store = ArtifactStore(artifact_root)
    store.write_run_json(
        "demo_chatbot",
        "run_001",
        "pipeline_run_state",
        {
            "pipeline_run_id": "pipeline_run_001",
            "project_id": "demo_chatbot",
            "run_id": "run_001",
            "status": "running",
            "current_stage": "C03_project_config",
            "artifact_paths": {
                "project_config": "artifacts/demo_chatbot/run_001/00_project_config/project_config.json"
            },
            "completed_stages": ["C03_project_config"],
        },
    )

    with pytest.raises(PipelineOrchestrationError, match="project_config"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == []


def test_run_pipeline_rejects_partial_checkpoint_without_downstream_execution(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    first_components = FakePipelineComponents()
    run_pipeline(config_path, run_id="run_001", components=first_components)
    (artifact_root / "demo_chatbot" / "run_001" / "08_validated_tests" / "coverage_report.json").unlink()
    second_components = FakePipelineComponents()

    with pytest.raises(PipelineOrchestrationError, match="C12_test_validation_coverage"):
        run_pipeline(config_path, run_id="run_001", components=second_components)

    assert "C13_review_report" not in stage_calls(second_components)
    assert "C14_executor_export" not in stage_calls(second_components)


def test_run_pipeline_fails_clearly_when_required_runner_is_missing(tmp_path):
    class MissingExtractionRunner(FakePipelineComponents):
        run_requirement_extraction = None

    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = MissingExtractionRunner()

    with pytest.raises(PipelineOrchestrationError, match="run_requirement_extraction"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == [
        "C03_project_config",
        "C04_document_ingestion",
        "C05_source_ledger",
    ]


def test_run_pipeline_fails_clearly_when_runner_returns_invalid_result(tmp_path):
    class InvalidResultRunner(FakePipelineComponents):
        def run_document_ingestion(self, context, artifacts):
            self.calls.append(("C04_document_ingestion", dict(artifacts)))
            return ["not", "a", "mapping"]

    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)

    with pytest.raises(PipelineOrchestrationError, match="mapping"):
        run_pipeline(config_path, run_id="run_001", components=InvalidResultRunner())


def test_run_pipeline_fails_when_runner_result_is_missing_expected_key(tmp_path):
    class MissingDocumentsResultRunner(FakePipelineComponents):
        def run_document_ingestion(self, context, artifacts):
            self.calls.append(("C04_document_ingestion", dict(artifacts)))
            return {}

    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = MissingDocumentsResultRunner()

    with pytest.raises(PipelineOrchestrationError, match="documents"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == ["C03_project_config", "C04_document_ingestion"]


def test_run_pipeline_fails_when_runner_returns_missing_artifact_path(tmp_path):
    class MissingPathRunner(FakePipelineComponents):
        def run_document_ingestion(self, context, artifacts):
            self.calls.append(("C04_document_ingestion", dict(artifacts)))
            return {
                "documents": (
                    Path(context.artifact_root)
                    / context.project_config.project_id
                    / context.run_id
                    / "01_documents"
                    / "documents.json"
                )
            }

    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = MissingPathRunner()

    with pytest.raises(PipelineOrchestrationError, match="does not exist"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == ["C03_project_config", "C04_document_ingestion"]


def test_run_pipeline_fails_when_runner_returns_path_outside_artifact_root(tmp_path):
    outside_path = tmp_path / "outside" / "documents.json"
    outside_path.parent.mkdir()
    outside_path.write_text(
        stable_json({"project_id": "demo_chatbot", "documents": [document_data()]}),
        encoding="utf-8",
    )

    class OutsideRootRunner(FakePipelineComponents):
        def run_document_ingestion(self, context, artifacts):
            self.calls.append(("C04_document_ingestion", dict(artifacts)))
            return {"documents": outside_path}

    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    components = OutsideRootRunner()

    with pytest.raises(PipelineOrchestrationError, match="artifact root"):
        run_pipeline(config_path, run_id="run_001", components=components)

    assert stage_calls(components) == ["C03_project_config", "C04_document_ingestion"]


def test_run_pipeline_resume_false_rejects_stale_returned_artifact_path(tmp_path):
    artifact_root = tmp_path / "artifacts"
    config_path = tmp_path / "project_config.json"
    write_config(config_path, artifact_root)
    run_pipeline(config_path, run_id="run_001", components=FakePipelineComponents())
    stale_project_config = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "00_project_config"
        / "project_config.json"
    )

    class StaleProjectConfigRunner(FakePipelineComponents):
        def run_project_config(self, context, artifacts):
            self.calls.append(("C03_project_config", dict(artifacts)))
            return {"project_config": stale_project_config}

    components = StaleProjectConfigRunner()

    with pytest.raises(PipelineOrchestrationError, match="stale"):
        run_pipeline(
            config_path,
            run_id="run_001",
            components=components,
            options=PipelineRunOptions(resume=False),
        )

    assert stage_calls(components) == ["C03_project_config"]
    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    state = PipelineRunState.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
    assert state.status == "failed"
    assert state.failed_stage == "C03_project_config"


def test_cli_run_smoke_delegates_to_orchestrator(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "project_config.json"
    artifact_root = tmp_path / "artifacts"
    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    calls = []

    class FakeResult:
        def __init__(self) -> None:
            self.state_path = state_path
            self.state = PipelineRunState.from_dict(
                {
                    "pipeline_run_id": "pipeline_run_001",
                    "project_id": "demo_chatbot",
                    "run_id": "run_001",
                    "status": "succeeded",
                    "current_stage": "C15_orchestrator",
                    "artifact_paths": {},
                    "completed_stages": PIPELINE_RUN_STAGES,
                }
            )

    def fake_run_pipeline(config, run_id, *, artifact_root=None, options=None, **_kwargs):
        calls.append((config, run_id, artifact_root, options))
        return FakeResult()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--run-id",
            "run_001",
            "--artifact-root",
            str(artifact_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(state_path) in captured.out
    assert captured.err == ""
    assert calls == [(config_path, "run_001", artifact_root, PipelineRunOptions())]


def test_cli_run_can_pass_skill_adapter_to_orchestrator(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "project_config.json"
    artifact_root = tmp_path / "artifacts"
    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    calls = []

    class FakeResult:
        def __init__(self) -> None:
            self.state_path = state_path

    def fake_run_pipeline(config, run_id, *, artifact_root=None, options=None, **_kwargs):
        calls.append((config, run_id, artifact_root, options))
        return FakeResult()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--run-id",
            "run_001",
            "--artifact-root",
            str(artifact_root),
            "--skill-adapter",
            CODEX_CLI_ADAPTER_NAME,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(state_path) in captured.out
    assert captured.err == ""
    assert calls == [
        (
            config_path,
            "run_001",
            artifact_root,
            PipelineRunOptions(skill_adapter=CODEX_CLI_ADAPTER_NAME),
        )
    ]


def test_cli_run_skip_flags_disable_review_and_export(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "project_config.json"
    artifact_root = tmp_path / "artifacts"
    state_path = artifact_root / "demo_chatbot" / "run_001" / "pipeline_run_state.json"
    calls = []

    class FakeResult:
        def __init__(self) -> None:
            self.state_path = state_path

    def fake_run_pipeline(config, run_id, *, artifact_root=None, options=None, **_kwargs):
        calls.append((config, run_id, artifact_root, options))
        return FakeResult()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--run-id",
            "run_001",
            "--artifact-root",
            str(artifact_root),
            "--skip-review",
            "--skip-export",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(state_path) in captured.out
    assert captured.err == ""
    assert calls == [
        (
            config_path,
            "run_001",
            artifact_root,
            PipelineRunOptions(include_review=False, include_export=False),
        )
    ]


def test_orchestrator_has_no_skill_runtime_or_provider_dependencies():
    source = inspect.getsource(orchestrator)

    for forbidden in (
        "SkillRuntime",
        "run_skill",
        "op" + "enai",
        "anth" + "ropic",
        "lang" + "chain",
        "llama" + "_index",
        "req" + "uests",
        "ht" + "tpx",
        "url" + "lib",
        "so" + "cket",
        "sub" + "process",
    ):
        assert forbidden not in source
