from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ai_testgen.schemas import (
    AtomicRequirement,
    CoverageReport,
    GovernedRequirementLedger,
    SchemaModel,
    SchemaValidationError,
    SourcePackage,
    SourceRef,
    TestCase,
    TestCaseStatus,
    TestObligation,
    TestObligationLedger,
    TestObligationStatus,
    ValidatedTestSuite,
)


COVERAGE_REPORT_ID = "coverage_001"
BLOCKED_OBLIGATION_STATUSES = {
    TestObligationStatus.BLOCKED_MISSING_DATA,
    TestObligationStatus.BLOCKED_UNCLEAR_REQUIREMENT,
}


def build_coverage_report(
    validated_suite: ValidatedTestSuite | Mapping[str, Any],
    governed_ledger: GovernedRequirementLedger | Mapping[str, Any],
    obligation_ledger: TestObligationLedger | Mapping[str, Any],
    source_package: SourcePackage | Mapping[str, Any] | None = None,
) -> CoverageReport:
    suite = _coerce_model(ValidatedTestSuite, validated_suite)
    governed = _coerce_model(GovernedRequirementLedger, governed_ledger)
    obligations = _coerce_model(TestObligationLedger, obligation_ledger)
    sources = _coerce_optional_model(SourcePackage, source_package)

    if suite.project_id != governed.project_id or suite.project_id != obligations.project_id:
        raise SchemaValidationError("coverage input project_id values must match")
    if sources is not None and suite.project_id != sources.project_id:
        raise SchemaValidationError("coverage SourcePackage project_id must match")

    covered_requirement_ids = _covered_requirement_ids(suite.test_cases)
    covered_obligation_ids = _covered_obligation_ids(suite.test_cases)
    blocked_obligation_ids = {
        obligation.obligation_id
        for obligation in obligations.obligations
        if obligation.status in BLOCKED_OBLIGATION_STATUSES
    }
    skipped_obligation_ids = {
        obligation.obligation_id
        for obligation in obligations.obligations
        if obligation.status == TestObligationStatus.SKIPPED_BY_POLICY
    }
    rejected_obligation_ids = {
        obligation.obligation_id
        for obligation in obligations.obligations
        if obligation.status == TestObligationStatus.REJECTED
    }
    skipped_requirement_ids = _skipped_requirement_ids(governed.requirements, obligations.obligations)

    requirement_ids = [requirement.requirement_id for requirement in governed.requirements]
    obligation_ids = [obligation.obligation_id for obligation in obligations.obligations]
    uncovered_requirement_ids = [
        requirement_id
        for requirement_id in requirement_ids
        if requirement_id not in covered_requirement_ids
        and requirement_id not in skipped_requirement_ids
    ]
    uncovered_obligation_ids = [
        obligation_id
        for obligation_id in obligation_ids
        if obligation_id not in covered_obligation_ids
        and obligation_id not in blocked_obligation_ids
        and obligation_id not in skipped_obligation_ids
        and obligation_id not in rejected_obligation_ids
    ]

    data = {
        "coverage_report_id": COVERAGE_REPORT_ID,
        "project_id": suite.project_id,
        "validated_suite_id": suite.validated_suite_id,
        "requirement_counts": {
            "total": len(requirement_ids),
            "covered": len(set(requirement_ids) & covered_requirement_ids),
            "uncovered": len(uncovered_requirement_ids),
        },
        "obligation_counts": {
            "total": len(obligation_ids),
            "covered": len(set(obligation_ids) & covered_obligation_ids),
            "uncovered": len(uncovered_obligation_ids),
            "blocked": len(blocked_obligation_ids),
            "skipped": len(skipped_obligation_ids),
        },
        "test_counts": _test_counts(suite.test_cases),
        "source_chunk_counts": _source_chunk_counts(
            governed.requirements,
            obligations.obligations,
            suite.test_cases,
            sources,
        ),
    }
    if skipped_requirement_ids:
        data["requirement_counts"]["skipped"] = len(skipped_requirement_ids)
    if uncovered_requirement_ids:
        data["uncovered_requirement_ids"] = uncovered_requirement_ids
    if uncovered_obligation_ids:
        data["uncovered_obligation_ids"] = uncovered_obligation_ids
    return CoverageReport.from_dict(data)


def _coerce_model(model_type: type[SchemaModel], value: SchemaModel | Mapping[str, Any]) -> Any:
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        return model_type.from_dict(value)
    raise SchemaValidationError(f"{model_type.__name__} input must be a mapping or model")


def _coerce_optional_model(
    model_type: type[SchemaModel],
    value: SchemaModel | Mapping[str, Any] | None,
) -> Any:
    if value is None:
        return None
    return _coerce_model(model_type, value)


def _covered_requirement_ids(test_cases: Iterable[TestCase]) -> set[str]:
    covered: set[str] = set()
    for test_case in test_cases:
        if test_case.is_exportable:
            covered.update(test_case.requirement_ids)
    return covered


def _covered_obligation_ids(test_cases: Iterable[TestCase]) -> set[str]:
    covered: set[str] = set()
    for test_case in test_cases:
        if test_case.is_exportable:
            covered.update(test_case.obligation_ids)
    return covered


def _test_counts(test_cases: list[TestCase]) -> dict[str, int]:
    return {
        "total": len(test_cases),
        "valid": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.VALID),
        "needs_review": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.NEEDS_REVIEW),
        "export_eligible": sum(1 for test_case in test_cases if test_case.is_exportable),
        "rejected": sum(1 for test_case in test_cases if test_case.status == TestCaseStatus.REJECTED),
    }


def _source_chunk_counts(
    requirements: list[AtomicRequirement],
    obligations: list[TestObligation],
    test_cases: list[TestCase],
    source_package: SourcePackage | None,
) -> dict[str, int]:
    if source_package is None:
        return {
            "total": 0,
            "with_requirements": 0,
            "covered": 0,
            "uncovered": 0,
            "without_requirements": 0,
        }

    chunk_ids = {chunk.chunk_id for chunk in source_package.chunks}
    skipped_requirement_ids = _skipped_requirement_ids(requirements, obligations)
    requirement_chunk_ids = _chunk_ids_from_source_refs(
        source_ref
        for requirement in requirements
        for source_ref in (requirement.source_refs or [])
    )
    skipped_chunk_ids = _chunk_ids_from_source_refs(
        source_ref
        for requirement in requirements
        if requirement.requirement_id in skipped_requirement_ids
        for source_ref in (requirement.source_refs or [])
    )
    covered_chunk_ids = _chunk_ids_from_source_refs(
        source_ref
        for test_case in test_cases
        if test_case.is_exportable
        for source_ref in (test_case.source_refs or [])
    )
    requirement_chunk_ids &= chunk_ids
    covered_requirement_chunk_ids = covered_chunk_ids & requirement_chunk_ids
    skipped_requirement_chunk_ids = (skipped_chunk_ids & requirement_chunk_ids) - covered_requirement_chunk_ids

    counts = {
        "total": len(chunk_ids),
        "with_requirements": len(requirement_chunk_ids),
        "covered": len(covered_requirement_chunk_ids),
        "uncovered": len(requirement_chunk_ids - covered_requirement_chunk_ids - skipped_requirement_chunk_ids),
        "without_requirements": len(chunk_ids - requirement_chunk_ids),
    }
    if skipped_requirement_chunk_ids:
        counts["skipped"] = len(skipped_requirement_chunk_ids)
    return counts


def _chunk_ids_from_source_refs(source_refs: Iterable[SourceRef]) -> set[str]:
    return {
        source_ref.chunk_id
        for source_ref in source_refs
        if source_ref.chunk_id is not None
    }


def _skipped_requirement_ids(
    requirements: list[AtomicRequirement],
    obligations: list[TestObligation],
) -> set[str]:
    obligations_by_requirement_id: dict[str, list[TestObligation]] = {}
    for obligation in obligations:
        obligations_by_requirement_id.setdefault(obligation.requirement_id, []).append(obligation)

    skipped: set[str] = set()
    for requirement in requirements:
        linked_obligations = obligations_by_requirement_id.get(requirement.requirement_id, [])
        if linked_obligations and all(_is_skipped_chatbot_obligation(obligation) for obligation in linked_obligations):
            skipped.add(requirement.requirement_id)
    return skipped


def _is_skipped_chatbot_obligation(obligation: TestObligation) -> bool:
    return (
        obligation.status == TestObligationStatus.SKIPPED_BY_POLICY
        or obligation.obligation_type == "non_chatbot_api_schema"
        or bool(obligation.metadata and obligation.metadata.get("chatbot_obligation") is False)
    )
