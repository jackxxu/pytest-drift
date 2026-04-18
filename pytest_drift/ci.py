"""CI-specific drift reporting: GitHub Actions annotations, step summary, JUnit XML."""
from __future__ import annotations

import json
import os
import urllib.request
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

    lines.append("## pytest-drift report")
    lines.append("")

    if not results and not missing_base:
        lines.append("> No drift comparisons were performed.")
    else:
        lines.append(
            f"**{len(failed)} drifted** / {len(passed)} stable "
            f"({len(results)} total comparisons)"
        )
        lines.append("")

        if failed:
            for r in failed:
                lines.append(f"- `{r.node_id}`")
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
# GitHub PR comment
# ---------------------------------------------------------------------------

def _get_pr_number() -> int | None:
    """Extract PR number from the GitHub Actions event payload."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        with open(event_path, encoding="utf-8") as f:
            event = json.load(f)
        return event["pull_request"]["number"]
    except Exception:
        return None


def _build_pr_comment(
    results: list[ComparisonResult],
    missing_base: list[str],
) -> str:
    failed = [r for r in results if not r.equal]
    passed = [r for r in results if r.equal]

    lines: list[str] = []
    lines.append("## pytest-drift report")
    lines.append("")
    lines.append(
        f"**{len(failed)} drifted** / {len(passed)} stable "
        f"({len(results)} total comparisons)"
    )
    lines.append("")

    if failed:
        for r in failed:
            lines.append(f"- `{r.node_id}`")
        lines.append("")

    if missing_base:
        lines.append("### Tests with no base-branch result")
        lines.append("")
        for node_id in missing_base:
            lines.append(f"- `{node_id}`")
        lines.append("")

    if passed:
        lines.append(f"<details><summary>{len(passed)} stable test(s)</summary>\n")
        for r in passed:
            lines.append(f"- `{r.node_id}`")
        lines.append("\n</details>")

    return "\n".join(lines)


def post_github_pr_comment(
    results: list[ComparisonResult],
    missing_base: list[str],
) -> None:
    """Post a drift summary comment on the GitHub PR conversation tab."""
    if not _is_github_actions():
        return
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = _get_pr_number()

    if not token or not repo or not pr_number:
        return

    # Only comment when there is something to report
    failed = [r for r in results if not r.equal]
    if not failed and not missing_base:
        return

    body = _build_pr_comment(results, missing_base)
    payload = json.dumps({"body": body}).encode("utf-8")
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        warnings.warn(
            f"pytest-drift: failed to post GitHub PR comment: {e}",
            DriftWarning,
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# GitLab CI — MR note + JUnit XML
# ---------------------------------------------------------------------------

def _is_gitlab_ci() -> bool:
    return os.environ.get("GITLAB_CI") == "true"


def post_gitlab_mr_note(
    results: list[ComparisonResult],
    missing_base: list[str],
) -> None:
    """Post a drift summary note on the GitLab MR conversation tab.

    Requires the pipeline to be triggered by a merge request (so that
    CI_MERGE_REQUEST_IID is set) and either GITLAB_TOKEN (a project/PAT token
    with api scope) or CI_JOB_TOKEN in the environment.
    """
    if not _is_gitlab_ci():
        return

    mr_iid = os.environ.get("CI_MERGE_REQUEST_IID")
    if not mr_iid:
        return  # not a merge-request pipeline

    # Only comment when there is something to report
    failed = [r for r in results if not r.equal]
    if not failed and not missing_base:
        return

    project_id = os.environ.get("CI_PROJECT_ID")
    server_url = os.environ.get("CI_SERVER_URL", "https://gitlab.com").rstrip("/")

    # Prefer an explicit token; fall back to the built-in job token
    token = os.environ.get("GITLAB_TOKEN")
    auth_header = ("PRIVATE-TOKEN", token) if token else ("JOB-TOKEN", os.environ.get("CI_JOB_TOKEN", ""))

    if not project_id or not auth_header[1]:
        return

    body = _build_pr_comment(results, missing_base)
    payload = json.dumps({"body": body}).encode("utf-8")
    url = f"{server_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes"

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            auth_header[0]: auth_header[1],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        warnings.warn(
            f"pytest-drift: failed to post GitLab MR note: {e}",
            DriftWarning,
            stacklevel=2,
        )


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
