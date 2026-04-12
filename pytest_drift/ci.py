"""CI-specific drift reporting: GitHub Actions annotations, step summary, JUnit XML."""
from __future__ import annotations

import os
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pandas_utils import ComparisonResult


# ---------------------------------------------------------------------------
# Custom warning category — shows up in pytest's "warnings summary" section
# ---------------------------------------------------------------------------

class DriftWarning(UserWarning):
    """Emitted when a test's return value drifts from the base branch."""


def emit_warnings(results: list[ComparisonResult]) -> None:
    """Emit one DriftWarning per drifted test so pytest surfaces them."""
    for r in results:
        if not r.equal:
            msg = f"DRIFT: {r.node_id} — return value changed from base branch"
            if r.report:
                first_line = r.report.splitlines()[0] if r.report.splitlines() else ""
                if first_line:
                    msg += f"\n  {first_line}"
            warnings.warn(msg, DriftWarning, stacklevel=2)


# ---------------------------------------------------------------------------
# GitHub Actions
# ---------------------------------------------------------------------------

def _is_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def emit_github_annotations(results: list[ComparisonResult]) -> None:
    """Write ::warning:: lines so GitHub renders them as PR annotations."""
    if not _is_github_actions():
        return
    for r in results:
        if not r.equal:
            first_line = ""
            if r.report:
                first_line = r.report.splitlines()[0] if r.report.splitlines() else ""
            detail = f" — {first_line}" if first_line else ""
            # GitHub Actions annotation format (single line, no real newlines)
            print(f"::warning title=Drift (value changed)::{r.node_id}{detail}")


def write_github_step_summary(
    results: list[ComparisonResult],
    missing_base: list[str],
) -> None:
    """Append a markdown drift report to $GITHUB_STEP_SUMMARY."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines: list[str] = []
    failed = [r for r in results if not r.equal]
    passed = [r for r in results if r.equal]

    lines.append("## Drift Report")
    lines.append("")
    lines.append("> ℹ️ Drifted tests changed their return value from the base branch. This may be intentional — review before merging.")
    lines.append("")

    if not results and not missing_base:
        lines.append("> No drift comparisons were performed.")
    else:
        lines.append(
            f"**{len(failed)} changed** / {len(passed)} stable "
            f"({len(results)} total comparisons)"
        )
        lines.append("")

        if failed:
            lines.append("### Changed tests")
            lines.append("")
            lines.append("| Test | Details |")
            lines.append("| ---- | ------- |")
            for r in failed:
                detail = ""
                if r.report:
                    first_line = r.report.splitlines()[0] if r.report.splitlines() else ""
                    detail = first_line[:120]
                lines.append(f"| `{r.node_id}` | {detail} |")
            lines.append("")

        if missing_base:
            lines.append("### Tests with no base-branch result")
            lines.append("")
            for node_id in missing_base:
                lines.append(f"- `{node_id}`")
            lines.append("")

        if passed:
            lines.append(
                f"<details><summary>{len(passed)} stable test(s)</summary>\n"
            )
            for r in passed:
                lines.append(f"- `{r.node_id}`")
            lines.append("\n</details>")

    lines.append("")

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# GitLab CI / generic JUnit XML
# ---------------------------------------------------------------------------

def _is_gitlab_ci() -> bool:
    return os.environ.get("GITLAB_CI") == "true"


def write_junit_xml(
    results: list[ComparisonResult],
    missing_base: list[str],
    output_path: Path | None = None,
) -> None:
    """
    Write a JUnit XML file so GitLab (and other tools) can render drift as
    test results in the MR/PR test widget.

    GitLab picks this up automatically when the job artifact is configured with
    ``reports: junit: drift-report.xml``.
    """
    if output_path is None:
        if not _is_gitlab_ci():
            return
        output_path = Path("drift-report.xml")

    suite = ET.Element("testsuite", name="pytest-drift", tests=str(len(results) + len(missing_base)))

    for r in results:
        tc = ET.SubElement(suite, "testcase", classname="drift", name=r.node_id)
        if not r.equal:
            # Use "failure" so CI tools highlight it for review — not a test failure per se
            failure = ET.SubElement(tc, "failure", message="Return value changed from base branch (review required)")
            failure.text = r.report or ""

    for node_id in missing_base:
        tc = ET.SubElement(suite, "testcase", classname="drift", name=node_id)
        ET.SubElement(tc, "skipped", message="No base-branch result found")

    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)
