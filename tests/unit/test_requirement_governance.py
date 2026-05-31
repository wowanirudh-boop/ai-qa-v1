import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.requirement_governance as requirement_governance
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.requirement_governance import (
    AtomicLedgerArtifactError,
    InvalidGovernedRequirementLedgerError,
    ProjectConfigArtifactError,
    RequirementGovernanceError,
    govern_atomic_requirement_ledger,
    govern_requirements_from_atomic_ledger_artifact,
)
from ai_testgen.schemas import AtomicRequirementLedger, GovernedRequirementLedger, ProjectConfig


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "requirement_governance"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def project_config_data(**overrides: object) -> dict:
    data = {
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
    }
    data.update(overrides)
    return data


def atomic_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot must ask for an order number before showing order status.",
        "requirement_type": "functional",
        "status": "atomic_draft",
        "origin": "source_derived",
        "source_refs": [source_ref()],
        "candidate_ids": ["cand_001"],
    }
    data.update(overrides)
    return data


def atomic_ledger_data(**overrides: object) -> dict:
    data = {
        "atomic_ledger_id": "atomic_ledger_001",
        "project_id": "demo_chatbot",
        "candidate_package_id": "cand_pkg_001",
        "requirements": [atomic_requirement()],
    }
    data.update(overrides)
    return data


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_project_config(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "00_project_config",
        "project_config",
        data or project_config_data(),
    )


def write_atomic_ledger(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "04_atomic_requirements",
        "atomic_requirement_ledger",
        data or atomic_ledger_data(),
    )


def test_govern_requirements_happy_path_writes_governed_ledger(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_project_config(store)
    atomic_artifact = write_atomic_ledger(store)

    result = govern_requirements_from_atomic_ledger_artifact(atomic_artifact.path)

    expected_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "05_governed_requirements"
        / "governed_requirement_ledger.json"
    )
    assert result.governed_ledger_path == expected_path
    assert result.governed_ledger.to_dict() == {
        "governed_ledger_id": "gov_ledger_001",
        "project_id": "demo_chatbot",
        "atomic_ledger_id": "atomic_ledger_001",
        "requirements": [
            atomic_requirement(status="validated"),
        ],
        "governance_summary": {
            "conflicting": 0,
            "duplicate": 0,
            "inferred": 0,
            "needs_clarification": 0,
            "out_of_scope": 0,
            "rejected": 0,
            "validated": 1,
        },
        "policy_version": "c09_deterministic_v1",
    }
    assert GovernedRequirementLedger.from_dict(
        json.loads(expected_path.read_text(encoding="utf-8"))
    ) == result.governed_ledger


def test_valid_requirement_becomes_governed_and_validated():
    config = ProjectConfig.from_dict(project_config_data())
    atomic_ledger = AtomicRequirementLedger.from_dict(atomic_ledger_data())

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)

    assert governed.requirements[0].status == "validated"
    assert governed.requirements[0].is_eligible_for_obligation_planning is True
    assert governed.governance_summary["validated"] == 1


def test_duplicate_is_marked_without_silent_deletion():
    config = ProjectConfig.from_dict(project_config_data())
    atomic_ledger = AtomicRequirementLedger.from_dict(
        atomic_ledger_data(
            requirements=[
                atomic_requirement(requirement_id="req_001", candidate_ids=["cand_001"]),
                atomic_requirement(
                    requirement_id="req_002",
                    statement="  the BOT must ask for an order number before showing order status  ",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                ),
            ]
        )
    )

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)

    assert [requirement.requirement_id for requirement in governed.requirements] == ["req_001", "req_002"]
    assert [requirement.status for requirement in governed.requirements] == ["validated", "duplicate"]
    assert governed.requirements[1].duplicate_of == "req_001"
    assert governed.governance_summary["duplicate"] == 1


def test_conflict_is_marked_and_preserved():
    config = ProjectConfig.from_dict(project_config_data())
    atomic_ledger = AtomicRequirementLedger.from_dict(
        atomic_ledger_data(
            requirements=[
                atomic_requirement(requirement_id="req_001"),
                atomic_requirement(
                    requirement_id="req_002",
                    statement="The bot must show order status without asking for an order number.",
                    source_refs=[source_ref(chunk_id="chunk_002")],
                    candidate_ids=["cand_002"],
                    conflicts_with=["req_001"],
                ),
            ]
        )
    )

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)

    assert governed.requirements[1].status == "conflicting"
    assert governed.requirements[1].conflicts_with == ["req_001"]
    assert governed.governance_summary["conflicting"] == 1


def test_rejected_requirement_is_retained_but_ineligible_for_obligation_planning():
    config = ProjectConfig.from_dict(project_config_data())
    atomic_ledger = AtomicRequirementLedger.from_dict(
        atomic_ledger_data(
            requirements=[
                atomic_requirement(
                    status="rejected",
                    rationale="Out of product scope.",
                )
            ]
        )
    )

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)

    assert len(governed.requirements) == 1
    assert governed.requirements[0].status == "rejected"
    assert governed.requirements[0].is_eligible_for_obligation_planning is False
    assert governed.governance_summary["rejected"] == 1


@pytest.mark.parametrize("origin", ["inferred", "assumption", "user_added", "system_default"])
def test_non_source_requirement_without_source_refs_remains_approval_gated(origin):
    config = ProjectConfig.from_dict(project_config_data())
    input_status = "inferred" if origin == "inferred" else "atomic_draft"
    atomic_ledger = AtomicRequirementLedger.from_dict(
        atomic_ledger_data(
            requirements=[
                {
                    "requirement_id": f"req_{origin}",
                    "statement": "The bot should provide a fallback response.",
                    "requirement_type": "functional",
                    "status": input_status,
                    "origin": origin,
                    "approval_required": True,
                }
            ]
        )
    )

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)
    requirement = governed.requirements[0]

    assert requirement.approval_required is True
    assert requirement.approval_status is None
    assert requirement.is_eligible_for_obligation_planning is False
    assert requirement.status in ("inferred", "needs_clarification")


def test_approved_non_source_requirement_can_be_validated():
    config = ProjectConfig.from_dict(project_config_data())
    atomic_ledger = AtomicRequirementLedger.from_dict(
        atomic_ledger_data(
            requirements=[
                {
                    "requirement_id": "req_assumption",
                    "statement": "The bot should provide a fallback response.",
                    "requirement_type": "functional",
                    "status": "atomic_draft",
                    "origin": "assumption",
                    "approval_required": True,
                    "approval_status": "approved",
                }
            ]
        )
    )

    governed = govern_atomic_requirement_ledger(atomic_ledger, config)

    assert governed.requirements[0].status == "validated"
    assert governed.requirements[0].is_eligible_for_obligation_planning is True


def test_governance_rejects_project_config_mismatch():
    config = ProjectConfig.from_dict(project_config_data(project_id="other_project"))
    atomic_ledger = AtomicRequirementLedger.from_dict(atomic_ledger_data())

    with pytest.raises(InvalidGovernedRequirementLedgerError, match="project_id"):
        govern_atomic_requirement_ledger(atomic_ledger, config)


def test_missing_project_config_artifact_is_reported(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    atomic_artifact = write_atomic_ledger(store)

    with pytest.raises(ProjectConfigArtifactError, match="ProjectConfig"):
        govern_requirements_from_atomic_ledger_artifact(atomic_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "05_governed_requirements"
        / "governed_requirement_ledger.json"
    ).exists()


def test_atomic_ledger_artifact_path_must_match_c09_input_convention(tmp_path):
    invalid_path = tmp_path / "artifacts" / "demo_chatbot" / "run_001" / "wrong" / "atomic_requirement_ledger.json"

    with pytest.raises(AtomicLedgerArtifactError, match="04_atomic_requirements"):
        govern_requirements_from_atomic_ledger_artifact(invalid_path)


def test_golden_fixture_atomic_ledger_to_governed_ledger(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    project_config = json.loads((GOLDEN_DIR / "project_config.json").read_text(encoding="utf-8"))
    source_ledger = json.loads((GOLDEN_DIR / "atomic_requirement_ledger.json").read_text(encoding="utf-8"))
    expected_governed = json.loads((GOLDEN_DIR / "governed_requirement_ledger.json").read_text(encoding="utf-8"))
    write_project_config(store, data=project_config)
    atomic_artifact = write_atomic_ledger(store, data=source_ledger)

    result = govern_requirements_from_atomic_ledger_artifact(atomic_artifact.path)

    assert result.governed_ledger.to_dict() == expected_governed
    assert stable_json(result.governed_ledger.to_dict()) == (
        GOLDEN_DIR / "governed_requirement_ledger.json"
    ).read_text(encoding="utf-8")


def test_cli_govern_requirements_smoke_delegates_to_c09(tmp_path, monkeypatch, capsys):
    atomic_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    )
    governed_path = tmp_path / "governed_requirement_ledger.json"
    calls = []

    def fake_govern(atomic_ledger):
        calls.append(atomic_ledger)
        return SimpleNamespace(governed_ledger_path=governed_path)

    monkeypatch.setattr(cli, "govern_requirements_from_atomic_ledger_artifact", fake_govern)

    exit_code = cli.main(["govern-requirements", "--atomic-ledger", str(atomic_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(governed_path) in captured.out
    assert captured.err == ""
    assert calls == [atomic_path]


def test_cli_govern_requirements_reports_missing_project_config(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    atomic_artifact = write_atomic_ledger(store)

    exit_code = cli.main(["govern-requirements", "--atomic-ledger", str(atomic_artifact.path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "ProjectConfig" in captured.err


def test_c09_writes_no_future_component_artifacts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    write_project_config(store)
    atomic_artifact = write_atomic_ledger(store)

    govern_requirements_from_atomic_ledger_artifact(atomic_artifact.path)

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/00_project_config/project_config.json",
        "demo_chatbot/run_001/04_atomic_requirements/atomic_requirement_ledger.json",
        "demo_chatbot/run_001/05_governed_requirements/governed_requirement_ledger.json",
    ]


def test_c09_implementation_has_no_future_component_or_provider_dependencies():
    source = inspect.getsource(requirement_governance)

    for forbidden in (
        "TestObligation",
        "DraftTestSuite",
        "TestCase",
        "ExecutorExportPackage",
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
