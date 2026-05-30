from __future__ import annotations

from collections.abc import Iterable

from ai_testgen.schemas import (
    AtomicRequirement,
    AtomicRequirementStatus,
    ExecutorExportPackage,
    NORMAL_OBLIGATION_STATUSES,
    SchemaValidationError,
    SourceRef,
    TestCase,
    TestObligation,
    ValidatedTestSuite,
)


def validate_obligation_links(
    obligations: Iterable[TestObligation],
    requirements: Iterable[AtomicRequirement],
) -> None:
    requirements_by_id = {requirement.requirement_id: requirement for requirement in requirements}

    for obligation in obligations:
        requirement = requirements_by_id.get(obligation.requirement_id)
        if requirement is None:
            raise SchemaValidationError(
                f"obligation {obligation.obligation_id} references unknown requirement {obligation.requirement_id}"
            )
        if requirement.status == AtomicRequirementStatus.REJECTED:
            raise SchemaValidationError(
                f"obligation {obligation.obligation_id} cannot link to rejected requirement {requirement.requirement_id}"
            )
        if requirement.status == AtomicRequirementStatus.CONFLICTING and obligation.status in NORMAL_OBLIGATION_STATUSES:
            raise SchemaValidationError(
                f"obligation {obligation.obligation_id} cannot be normal for conflicting requirement "
                f"{requirement.requirement_id}"
            )
        if _normalized_source_refs(obligation.source_refs) != _normalized_source_refs(requirement.source_refs):
            raise SchemaValidationError(
                f"obligation {obligation.obligation_id} source_refs must match linked requirement "
                f"{requirement.requirement_id} source_refs"
            )


def _normalized_source_refs(source_refs: Iterable[SourceRef] | None) -> list[tuple[tuple[str, str], ...]]:
    return sorted(
        tuple(sorted(source_ref.to_dict().items()))
        for source_ref in (source_refs or [])
    )


def validate_test_case_links(
    test_cases: Iterable[TestCase],
    requirements: Iterable[AtomicRequirement],
    obligations: Iterable[TestObligation],
) -> None:
    requirements_by_id = {requirement.requirement_id: requirement for requirement in requirements}
    obligation_ids = {obligation.obligation_id for obligation in obligations}

    for test_case in test_cases:
        for requirement_id in test_case.requirement_ids:
            requirement = requirements_by_id.get(requirement_id)
            if requirement is None:
                raise SchemaValidationError(
                    f"test case {test_case.test_case_id} references unknown requirement {requirement_id}"
                )
            if test_case.is_exportable and requirement.status == AtomicRequirementStatus.CONFLICTING:
                raise SchemaValidationError(
                    f"test case {test_case.test_case_id} is exportable but links to conflicting requirement "
                    f"{requirement_id}"
                )
            if test_case.is_exportable and requirement.status == AtomicRequirementStatus.REJECTED:
                raise SchemaValidationError(
                    f"test case {test_case.test_case_id} is exportable but links to rejected requirement "
                    f"{requirement_id}"
                )
        for obligation_id in test_case.obligation_ids:
            if obligation_id not in obligation_ids:
                raise SchemaValidationError(
                    f"test case {test_case.test_case_id} references unknown obligation {obligation_id}"
                )


def validate_executor_export_package(
    package: ExecutorExportPackage,
    validated_suite: ValidatedTestSuite,
) -> None:
    test_cases_by_id = {test_case.test_case_id: test_case for test_case in validated_suite.test_cases}

    if package.validated_suite_id != validated_suite.validated_suite_id:
        raise SchemaValidationError("export package validated_suite_id must match the validated suite")

    for test_case_id in package.exported_test_case_ids:
        test_case = test_cases_by_id.get(test_case_id)
        if test_case is None:
            raise SchemaValidationError(
                f"export package references unknown test case {test_case_id}"
            )
        if not test_case.is_exportable:
            raise SchemaValidationError(f"test case {test_case_id} is not exportable")
