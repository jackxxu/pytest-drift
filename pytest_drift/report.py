"""Terminal diff formatting for regression comparison results."""
from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pandas_utils import ComparisonResult


def format_regression_summary(
    results: list["ComparisonResult"],
    use_color: bool = True,
) -> str:
    """Format comparison results into a terminal-friendly summary."""
    if not results:
        return ""

    width = min(shutil.get_terminal_size().columns, 120)
    lines = []
    lines.append("=" * width)
    lines.append("DRIFT COMPARISON SUMMARY")
    lines.append("=" * width)

    passed = [r for r in results if r.equal]
    failed = [r for r in results if not r.equal]

    for result in passed:
        status = _green("STABLE", use_color)
        lines.append(f"{status} {result.node_id}")

    for result in failed:
        status = _yellow("DRIFTED", use_color)
        lines.append(f"{status} {result.node_id}")
        if result.report:
            # Indent and truncate long reports
            report_lines = result.report.splitlines()
            max_lines = 80
            if len(report_lines) > max_lines:
                report_lines = report_lines[:max_lines] + [
                    f"  ... ({len(report_lines) - max_lines} more lines)"
                ]
            for rline in report_lines:
                # Truncate long lines
                if len(rline) > width - 4:
                    rline = rline[: width - 7] + "..."
                lines.append(f"    {rline}")

    lines.append("-" * width)
    lines.append(
        f"{len(passed)} stable, {len(failed)} drifted "
        f"({len(results)} total drift comparisons)"
    )
    lines.append("")

    return "\n".join(lines)


def _green(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[32m{text}\033[0m"
    return text


def _red(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[31m{text}\033[0m"
    return text


def _yellow(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[33m{text}\033[0m"
    return text
