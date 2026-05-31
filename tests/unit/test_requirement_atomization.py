import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_testgen.cli as cli
import ai_testgen.requirement_atomization as requirement_atomization
from ai_testgen.artifact_store import ArtifactStore
from ai_testgen.requirement_atomization import (
    CandidatePackageArtifactError,
    DEFAULT_SKILL_DEFINITION_PATH,
    InvalidAtomicRequirementLedgerError,
    InvalidRequirementAtomizationSkillError,
    RequirementAtomizationSkillError,
    atomize_candidate_package_deterministic_for_tests,
    atomize_requirements_from_candidate_package_artifact,
)
from ai_testgen.schemas import (
    AtomicRequirementLedger,
    CandidateRequirementPackage,
    SkillDefinition,
    SkillRunRecord,
)
from ai_testgen.skill_runtime import SkillRuntime


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "requirement_atomization"


def source_ref(chunk_id: str = "chunk_001", document_id: str = "doc_001") -> dict:
    return {"document_id": document_id, "chunk_id": chunk_id}


def candidate_requirement(**overrides: object) -> dict:
    data = {
        "candidate_id": "cand_001",
        "statement": "The bot must ask for an order number before helping with order status.",
        "requirement_type_guess": "functional",
        "source_refs": [source_ref()],
        "confidence": 0.91,
    }
    data.update(overrides)
    return data


def candidate_package_data(**overrides: object) -> dict:
    data = {
        "candidate_package_id": "cand_pkg_001",
        "project_id": "demo_chatbot",
        "source_package_id": "source_pkg_001",
        "candidates": [candidate_requirement()],
    }
    data.update(overrides)
    return data


def atomic_requirement(**overrides: object) -> dict:
    data = {
        "requirement_id": "req_001",
        "statement": "The bot must ask for an order number before helping with order status.",
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


def requirement_atomization_skill_definition(**overrides: object) -> SkillDefinition:
    data = {
        "skill_id": "fake_requirement_atomization_v1",
        "name": "Fake Requirement Atomization",
        "version": "1.0.0",
        "input_contract": "CandidateRequirementPackage",
        "output_contract": "AtomicRequirementLedger",
        "entrypoint": "tests.fake_requirement_atomization",
    }
    data.update(overrides)
    return SkillDefinition.from_dict(data)


def stable_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


class FakeRequirementAtomizationAdapter:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.calls = []

    def execute(self, skill_definition, input_artifacts):
        self.calls.append((skill_definition, input_artifacts))
        return self.output


def write_candidate_package(store: ArtifactStore, *, data: dict | None = None):
    return store.write_json(
        "demo_chatbot",
        "run_001",
        "03_candidate_requirements",
        "candidate_requirement_package",
        data or candidate_package_data(),
    )


def runtime_with_adapter(artifact_root: Path, output: dict) -> tuple[SkillRuntime, FakeRequirementAtomizationAdapter]:
    adapter = FakeRequirementAtomizationAdapter(output)
    return SkillRuntime(artifact_root=artifact_root, adapter=adapter), adapter


def write_skill_definition(path: Path, **overrides: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    definition = requirement_atomization_skill_definition(**overrides)
    path.write_text(stable_json(definition.to_dict()), encoding="utf-8")
    return path


def test_production_atomization_uses_skill_runtime_when_no_skill_definition_is_supplied(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    default_skill_path = tmp_path / DEFAULT_SKILL_DEFINITION_PATH
    write_skill_definition(default_skill_path)
    monkeypatch.setattr(requirement_atomization, "DEFAULT_SKILL_DEFINITION_PATH", default_skill_path)
    runtime, adapter = runtime_with_adapter(
        artifact_root,
        atomic_ledger_data(
            requirements=[
                atomic_requirement(
                    requirement_id="skill_generated_id",
                    statement="The bot must ask for an order number before helping with order status.",
                )
            ]
        ),
    )

    result = atomize_requirements_from_candidate_package_artifact(
        candidate_artifact.path,
        skill_runtime=runtime,
    )

    expected_atomic_path = (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    )
    expected_ledger = atomic_ledger_data()
    assert result.atomic_ledger_path == expected_atomic_path
    assert result.atomic_ledger.to_dict() == expected_ledger
    assert result.skill_run_record.skill_id == "fake_requirement_atomization_v1"
    assert result.skill_run_record_path == (
        artifact_root / "demo_chatbot" / "run_001" / "skill_runs" / "skill_run_001.json"
    )
    assert len(adapter.calls) == 1
    assert AtomicRequirementLedger.from_dict(
        json.loads(expected_atomic_path.read_text(encoding="utf-8"))
    ) == result.atomic_ledger


def test_candidate_split_into_multiple_atomic_requirements():
    candidate_package = CandidateRequirementPackage.from_dict(
        candidate_package_data(
            candidates=[
                candidate_requirement(
                    statement="The bot must collect an order number and provide order status."
                )
            ]
        )
    )

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert [requirement.requirement_id for requirement in ledger.requirements] == ["req_001", "req_002"]
    assert [requirement.statement for requirement in ledger.requirements] == [
        "The bot must collect an order number.",
        "The bot must provide order status.",
    ]
    assert [requirement.candidate_ids for requirement in ledger.requirements] == [["cand_001"], ["cand_001"]]


def test_ambiguous_and_phrase_is_not_split_into_invalid_requirements():
    candidate_package = CandidateRequirementPackage.from_dict(
        candidate_package_data(
            candidates=[
                candidate_requirement(
                    statement="The bot must collect first and last name."
                )
            ]
        )
    )

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert [requirement.statement for requirement in ledger.requirements] == [
        "The bot must collect first and last name.",
    ]


def test_and_phrase_inside_object_is_not_split():
    candidate_package = CandidateRequirementPackage.from_dict(
        candidate_package_data(
            candidates=[
                candidate_requirement(
                    statement="The bot must show order status and payment history."
                )
            ]
        )
    )

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert [requirement.statement for requirement in ledger.requirements] == [
        "The bot must show order status and payment history.",
    ]


@pytest.mark.parametrize(
    "statement",
    [
        "The bot must ask for and collect an order number.",
        "The bot must check for and reject duplicate requests.",
    ],
)
def test_and_split_does_not_create_prepositional_fragments(statement):
    candidate_package = CandidateRequirementPackage.from_dict(
        candidate_package_data(
            candidates=[
                candidate_requirement(statement=statement)
            ]
        )
    )

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert [requirement.statement for requirement in ledger.requirements] == [statement]


def test_source_refs_candidate_ids_and_origin_are_preserved():
    refs = [
        {"document_id": "doc_001", "chunk_id": "chunk_001", "location": "requirements.md:1"},
        {"document_id": "doc_002", "chunk_id": "chunk_009", "quote": "The bot must verify the customer."},
    ]
    candidate_package = CandidateRequirementPackage.from_dict(
        candidate_package_data(candidates=[candidate_requirement(source_refs=refs)])
    )

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)
    requirement = ledger.requirements[0]

    assert requirement.origin == "source_derived"
    assert requirement.status == "atomic_draft"
    assert requirement.candidate_ids == ["cand_001"]
    assert [source_ref.to_dict() for source_ref in requirement.source_refs] == refs


def test_candidate_missing_source_refs_is_rejected_by_schema_validation(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    invalid_candidate_package = candidate_package_data(
        candidates=[candidate_requirement(source_refs=[])]
    )
    candidate_artifact = write_candidate_package(store, data=invalid_candidate_package)

    with pytest.raises(CandidatePackageArtifactError, match="source_refs"):
        atomize_requirements_from_candidate_package_artifact(candidate_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    ).exists()


def test_missing_default_skill_definition_fails_without_heuristic_atomization(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    monkeypatch.setattr(
        requirement_atomization,
        "DEFAULT_SKILL_DEFINITION_PATH",
        tmp_path / "skills" / "missing_requirement_atomization_v1.json",
    )

    with pytest.raises(InvalidRequirementAtomizationSkillError, match="SkillDefinition file not found"):
        atomize_requirements_from_candidate_package_artifact(candidate_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    ).exists()


def test_invalid_default_atomization_skill_definition_fails_clearly(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    default_skill_path = tmp_path / DEFAULT_SKILL_DEFINITION_PATH
    write_skill_definition(default_skill_path, input_contract="SourcePackage")
    monkeypatch.setattr(requirement_atomization, "DEFAULT_SKILL_DEFINITION_PATH", default_skill_path)

    with pytest.raises(InvalidRequirementAtomizationSkillError, match="input_contract"):
        atomize_requirements_from_candidate_package_artifact(candidate_artifact.path)

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    ).exists()


def test_source_derived_skill_output_missing_source_refs_is_rejected(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    invalid_output = atomic_ledger_data(
        requirements=[
            atomic_requirement(
                status="validated",
                source_refs=[],
            )
        ]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, invalid_output)

    with pytest.raises(RequirementAtomizationSkillError, match="source_refs"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(),
            skill_runtime=runtime,
        )

    assert not (
        artifact_root
        / "demo_chatbot"
        / "run_001"
        / "04_atomic_requirements"
        / "atomic_requirement_ledger.json"
    ).exists()


@pytest.mark.parametrize("origin", ["inferred", "assumption", "user_added", "system_default"])
def test_non_source_skill_requirements_without_source_refs_must_require_approval(tmp_path, origin):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    invalid_output = atomic_ledger_data(
        requirements=[
            {
                "requirement_id": "req_001",
                "statement": "The bot has a non-source requirement.",
                "requirement_type": "functional",
                "status": "inferred" if origin == "inferred" else "atomic_draft",
                "origin": origin,
            }
        ]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, invalid_output)

    with pytest.raises(RequirementAtomizationSkillError, match="approval_required"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(),
            skill_runtime=runtime,
        )


def test_approval_gated_non_source_skill_requirement_without_source_refs_is_allowed(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    skill_output = atomic_ledger_data(
        requirements=[
            {
                "requirement_id": "skill_req_inferred",
                "statement": "The bot may need a fallback response.",
                "requirement_type": "functional",
                "status": "inferred",
                "origin": "inferred",
                "approval_required": True,
            }
        ]
    )
    runtime, adapter = runtime_with_adapter(artifact_root, skill_output)

    result = atomize_requirements_from_candidate_package_artifact(
        candidate_artifact.path,
        requirement_atomization_skill_definition(),
        skill_runtime=runtime,
    )

    assert result.atomic_ledger.requirements[0].to_dict() == {
        "requirement_id": "req_001",
        "statement": "The bot may need a fallback response.",
        "requirement_type": "functional",
        "status": "inferred",
        "origin": "inferred",
        "approval_required": True,
    }
    assert result.skill_run_record.status == "succeeded"
    assert isinstance(adapter.calls[0][1][0], CandidateRequirementPackage)
    assert SkillRunRecord.from_dict(
        json.loads(result.skill_run_record_path.read_text(encoding="utf-8"))
    ) == result.skill_run_record


def test_skill_source_derived_requirement_must_preserve_candidate_source_refs(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    skill_output = atomic_ledger_data(
        requirements=[
            atomic_requirement(
                source_refs=[source_ref(chunk_id="chunk_999")],
            )
        ]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, skill_output)

    with pytest.raises(InvalidAtomicRequirementLedgerError, match="source_refs"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(),
            skill_runtime=runtime,
        )


def test_skill_output_with_unknown_candidate_id_fails(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    skill_output = atomic_ledger_data(
        requirements=[
            atomic_requirement(
                candidate_ids=["cand_missing"],
            )
        ]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, skill_output)

    with pytest.raises(InvalidAtomicRequirementLedgerError, match="unknown candidate"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(),
            skill_runtime=runtime,
        )


def test_source_derived_skill_output_without_candidate_ids_fails(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    skill_output = atomic_ledger_data(
        requirements=[
            atomic_requirement(
                candidate_ids=None,
            )
        ]
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, skill_output)

    with pytest.raises(RequirementAtomizationSkillError, match="candidate_ids"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(),
            skill_runtime=runtime,
        )


def test_requirement_atomization_skill_must_declare_c08_contracts(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    runtime, adapter = runtime_with_adapter(artifact_root, atomic_ledger_data())

    with pytest.raises(InvalidRequirementAtomizationSkillError, match="input_contract"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(input_contract="SourcePackage"),
            skill_runtime=runtime,
        )

    with pytest.raises(InvalidRequirementAtomizationSkillError, match="output_contract"):
        atomize_requirements_from_candidate_package_artifact(
            candidate_artifact.path,
            requirement_atomization_skill_definition(output_contract="CandidateRequirementPackage"),
            skill_runtime=runtime,
        )

    assert adapter.calls == []


def test_skill_atomization_writes_documented_outputs_and_raw_skill_output(tmp_path):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    runtime, _adapter = runtime_with_adapter(artifact_root, atomic_ledger_data())

    atomize_requirements_from_candidate_package_artifact(
        candidate_artifact.path,
        requirement_atomization_skill_definition(),
        skill_runtime=runtime,
    )

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json",
        "demo_chatbot/run_001/04_atomic_requirements/atomic_requirement_ledger.json",
        "demo_chatbot/run_001/04_atomic_requirements/atomic_requirement_ledger_skill_output.json",
        "demo_chatbot/run_001/skill_runs/skill_run_001.json",
    ]


def test_golden_fixture_candidate_package_to_atomic_ledger():
    source_data = json.loads((GOLDEN_DIR / "candidate_requirement_package.json").read_text(encoding="utf-8"))
    expected_ledger = json.loads((GOLDEN_DIR / "atomic_requirement_ledger.json").read_text(encoding="utf-8"))
    candidate_package = CandidateRequirementPackage.from_dict(source_data)

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert ledger.to_dict() == expected_ledger
    assert stable_json(ledger.to_dict()) == (
        GOLDEN_DIR / "atomic_requirement_ledger.json"
    ).read_text(encoding="utf-8")


def test_cli_atomize_requirements_smoke_delegates_to_c08(tmp_path, monkeypatch, capsys):
    candidate_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )
    skill_definition_path = tmp_path / "skills" / "requirement_atomization_v1.json"
    atomic_path = tmp_path / "atomic_requirement_ledger.json"
    calls = []

    def fake_atomize(candidates, skill_definition=None):
        calls.append((candidates, skill_definition))
        return SimpleNamespace(atomic_ledger_path=atomic_path)

    monkeypatch.setattr(cli, "atomize_requirements_from_candidate_package_artifact", fake_atomize)

    exit_code = cli.main(
        [
            "atomize-requirements",
            "--candidates",
            str(candidate_path),
            "--skill-definition",
            str(skill_definition_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(atomic_path) in captured.out
    assert captured.err == ""
    assert calls == [(candidate_path, skill_definition_path)]


def test_cli_atomize_requirements_reports_invalid_candidate_artifact(tmp_path, capsys):
    missing_path = (
        tmp_path
        / "artifacts"
        / "demo_chatbot"
        / "run_001"
        / "03_candidate_requirements"
        / "candidate_requirement_package.json"
    )

    exit_code = cli.main(["atomize-requirements", "--candidates", str(missing_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "CandidateRequirementPackage" in captured.err


def test_c08_writes_no_future_component_artifacts(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    default_skill_path = tmp_path / DEFAULT_SKILL_DEFINITION_PATH
    write_skill_definition(default_skill_path)
    monkeypatch.setattr(requirement_atomization, "DEFAULT_SKILL_DEFINITION_PATH", default_skill_path)
    runtime, _adapter = runtime_with_adapter(artifact_root, atomic_ledger_data())

    atomize_requirements_from_candidate_package_artifact(
        candidate_artifact.path,
        skill_runtime=runtime,
    )

    files = sorted(path.relative_to(artifact_root).as_posix() for path in artifact_root.rglob("*") if path.is_file())
    assert files == [
        "demo_chatbot/run_001/03_candidate_requirements/candidate_requirement_package.json",
        "demo_chatbot/run_001/04_atomic_requirements/atomic_requirement_ledger.json",
        "demo_chatbot/run_001/04_atomic_requirements/atomic_requirement_ledger_skill_output.json",
        "demo_chatbot/run_001/skill_runs/skill_run_001.json",
    ]


def test_deterministic_helper_is_explicitly_named_for_tests_only():
    candidate_package = CandidateRequirementPackage.from_dict(candidate_package_data())

    ledger = atomize_candidate_package_deterministic_for_tests(candidate_package)

    assert ledger.to_dict() == atomic_ledger_data()
    assert not hasattr(requirement_atomization, "atomize_candidate_package")


def test_production_public_function_does_not_call_deterministic_helper(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(artifact_root)
    candidate_artifact = write_candidate_package(store)
    default_skill_path = tmp_path / DEFAULT_SKILL_DEFINITION_PATH
    write_skill_definition(default_skill_path)
    monkeypatch.setattr(requirement_atomization, "DEFAULT_SKILL_DEFINITION_PATH", default_skill_path)

    def fail_if_called(candidate_package):
        raise AssertionError("production path must not call deterministic helper")

    monkeypatch.setattr(
        requirement_atomization,
        "atomize_candidate_package_deterministic_for_tests",
        fail_if_called,
    )
    runtime, _adapter = runtime_with_adapter(artifact_root, atomic_ledger_data())

    result = atomize_requirements_from_candidate_package_artifact(
        candidate_artifact.path,
        skill_runtime=runtime,
    )

    assert result.atomic_ledger.to_dict() == atomic_ledger_data()


def test_c08_implementation_has_no_future_component_or_provider_dependencies():
    source = inspect.getsource(requirement_atomization)

    for forbidden in (
        "GovernedRequirementLedger",
        "TestObligation",
        "DraftTestSuite",
        "TestCase",
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
