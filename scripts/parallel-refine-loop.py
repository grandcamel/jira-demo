#!/usr/bin/env python3
"""
Parallel Skill Refinement Orchestrator.

Runs refinement loops for multiple scenarios in parallel. Each scenario gets
independent retry attempts with checkpoint-based iteration and fix agent
session continuity.

Usage:
    python parallel-refine-loop.py --scenarios all --max-attempts 5
    python parallel-refine-loop.py --scenarios search,issue --max-workers 4

Environment:
    JIRA_SKILLS_PATH: Path to Jira-Assistant-Skills repo (default: auto-detected)
"""

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from parallel_test_common import (
    ALL_SCENARIOS,
    DEMO_NETWORK,
    JIRA_SKILLS_PATH,
    PROJECT_ROOT,
    SCENARIOS_DIR,
    ensure_network_exists,
    get_checkpoint_file,
    get_plugin_paths,
    parse_scenario_arg,
    parse_test_output,
    validate_scenarios,
)
from docker_runner import build_refine_skill_test_command

# Timeouts
DEFAULT_TEST_TIMEOUT = 600  # 10 min per test attempt
DEFAULT_FIX_TIMEOUT = 300   # 5 min per fix agent call


@dataclass
class AttemptResult:
    """Result from a single refinement attempt."""
    attempt: int
    passed: bool
    prompt_index: Optional[int] = None
    quality: Optional[str] = None
    files_changed: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ScenarioResult:
    """Result from a scenario's full refinement loop."""
    scenario: str
    passed: bool
    total_attempts: int
    duration_seconds: float
    attempts: list[AttemptResult] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class OrchestratorResult:
    """Aggregated results from all scenario refinements."""
    total: int
    passed: int
    failed: int
    duration_seconds: float
    max_attempts: int
    results: list[ScenarioResult] = field(default_factory=list)


def run_skill_test(
    scenario: str,
    fork_from: Optional[int] = None,
    prompt_index: Optional[int] = None,
    checkpoint_file: Optional[str] = None,
    verbose: bool = False,
) -> tuple[bool, Optional[dict]]:
    """
    Run skill test in Docker with mock mode.

    Returns: (all_passed, fix_context_or_none)
    """
    # Build docker command using shared builder
    cmd, inner_cmd = build_refine_skill_test_command(
        scenario=scenario,
        checkpoint_file=checkpoint_file or get_checkpoint_file(scenario),
        fork_from=fork_from,
        prompt_index=prompt_index,
        verbose=verbose,
    )
    cmd.append(inner_cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, {"error": "Test timed out"}
    except Exception as e:
        return False, {"error": str(e)}

    parsed = parse_test_output(result.stdout)

    if parsed and parsed.get("status") == "all_passed":
        return True, None

    if parsed:
        return False, parsed

    error_detail = result.stderr[-500:] if result.stderr else result.stdout[-500:]
    return False, {"error": f"Could not parse output: {error_detail}"}


def run_fix_agent(
    fix_context: dict,
    session_id: Optional[str] = None,
    attempt_history: Optional[list[dict]] = None,
    verbose: bool = False,
) -> dict:
    """
    Run fix agent to make changes based on failure context.

    Returns: {"success": bool, "files_changed": [...], "session_id": "..."}
    """
    failure = fix_context.get("failure", {})
    if not failure:
        return {"success": False, "files_changed": [], "session_id": session_id}

    prompt = f"""You are a skill refinement agent. A JIRA Assistant Skill test has failed and you need to fix it.

## Failure Details

**Prompt that failed:**
{failure.get('prompt_text', 'unknown')}

**Tools called:** {failure.get('tools_called', [])}

**Tool Assertions:**
{json.dumps(failure.get('tool_assertions', []), indent=2)}

**Text Assertions:**
{json.dumps(failure.get('text_assertions', []), indent=2)}

**Quality Rating:** {failure.get('quality', 'unknown')}
**Tool Accuracy:** {failure.get('tool_accuracy', 'unknown')}

**Judge Reasoning:**
{failure.get('reasoning', 'none')}

**Refinement Suggestion:**
{failure.get('refinement_suggestion', 'none')}

## Relevant Files

The skill files are at: {JIRA_SKILLS_PATH}/plugins/jira-assistant-skills/skills/
"""

    for path, content in fix_context.get("relevant_files", {}).items():
        prompt += f"\n### {path}\n```\n{content[:3000]}\n```\n"

    if attempt_history:
        prompt += "\n## Previous Fix Attempts\n"
        for h in attempt_history:
            prompt += f"- Attempt {h['attempt']}: "
            if h.get('files'):
                prompt += f"Changed {h['files']}, "
            prompt += f"Result: {h['result']}\n"

    prompt += """

## Your Task

Make targeted changes to fix the failing test:
1. If tool selection is wrong: Update skill descriptions
2. If output is wrong: Improve skill examples or instructions
3. If API error: Check library code

Make minimal, focused changes. Edit actual files.
"""

    cmd = [
        "claude",
        "-p", prompt,
        "--model", "sonnet",
        "--dangerously-skip-permissions",
        "--output-format", "json",
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FIX_TIMEOUT,
            cwd=JIRA_SKILLS_PATH,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "files_changed": [], "session_id": session_id}
    except Exception as e:
        return {"success": False, "files_changed": [], "session_id": session_id, "error": str(e)}

    # Parse session ID from JSON output
    new_session_id = session_id
    try:
        output_data = json.loads(result.stdout)
        new_session_id = output_data.get("session_id", session_id)
    except json.JSONDecodeError:
        pass

    # Detect changed files
    files_changed = []
    output = result.stdout
    if "Edit" in output or "edited" in output.lower():
        file_patterns = re.findall(r'(?:skills/|lib/)[^\s\'"]+\.(?:md|py)', output)
        files_changed = list(set(file_patterns))

    return {
        "success": result.returncode == 0,
        "files_changed": files_changed,
        "session_id": new_session_id,
    }


def run_refinement_loop(
    scenario: str,
    max_attempts: int = 5,
    verbose: bool = False,
) -> ScenarioResult:
    """
    Run refinement loop for a single scenario.

    Uses checkpoint-based iteration:
    - Stop at first failing prompt
    - Fork from checkpoint on retry (skip passed prompts)
    - Maintain fix agent session across attempts
    """
    start_time = time.time()
    checkpoint_file = get_checkpoint_file(scenario)
    fix_session_id: Optional[str] = None
    attempt_history: list[dict] = []
    attempts: list[AttemptResult] = []
    last_failing_prompt_index: Optional[int] = None

    if verbose:
        print(f"  [{scenario}] Starting refinement loop (max {max_attempts} attempts)")

    for attempt in range(1, max_attempts + 1):
        fork_from: Optional[int] = None
        prompt_index: Optional[int] = None

        # Fork from checkpoint if we know where we failed
        if attempt > 1 and last_failing_prompt_index is not None:
            if last_failing_prompt_index > 0:
                fork_from = last_failing_prompt_index - 1
                prompt_index = last_failing_prompt_index

        # Run test
        all_passed, fix_ctx = run_skill_test(
            scenario=scenario,
            fork_from=fork_from,
            prompt_index=prompt_index,
            checkpoint_file=checkpoint_file,
            verbose=verbose,
        )

        if all_passed:
            attempts.append(AttemptResult(attempt=attempt, passed=True))
            return ScenarioResult(
                scenario=scenario,
                passed=True,
                total_attempts=attempt,
                duration_seconds=time.time() - start_time,
                attempts=attempts,
            )

        # Handle test failure
        if fix_ctx and "error" in fix_ctx:
            attempts.append(AttemptResult(
                attempt=attempt,
                passed=False,
                error=fix_ctx["error"],
            ))
            continue

        failure = fix_ctx.get("failure", {}) if fix_ctx else {}
        last_failing_prompt_index = failure.get("prompt_index")
        quality = failure.get("quality", "unknown")

        attempts.append(AttemptResult(
            attempt=attempt,
            passed=False,
            prompt_index=last_failing_prompt_index,
            quality=quality,
        ))

        # Run fix agent
        fix_result = run_fix_agent(
            fix_ctx,
            session_id=fix_session_id,
            attempt_history=attempt_history,
            verbose=verbose,
        )

        fix_session_id = fix_result.get("session_id", fix_session_id)
        attempts[-1].files_changed = fix_result.get("files_changed", [])

        attempt_history.append({
            "attempt": attempt,
            "files": fix_result.get("files_changed", []),
            "result": "still failing",
        })

    return ScenarioResult(
        scenario=scenario,
        passed=False,
        total_attempts=max_attempts,
        duration_seconds=time.time() - start_time,
        attempts=attempts,
    )


def run_parallel_refinement(
    scenarios: list[str],
    max_workers: int = 4,
    max_attempts: int = 5,
    verbose: bool = False,
) -> OrchestratorResult:
    """Run refinement loops for all scenarios in parallel."""
    start_time = time.time()
    results: list[ScenarioResult] = []

    print(f"Running refinement loops for {len(scenarios)} scenarios", flush=True)
    print(f"Max workers: {max_workers}, Max attempts per scenario: {max_attempts}", flush=True)
    print(f"Scenarios: {', '.join(scenarios)}\n", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_scenario = {
            executor.submit(
                run_refinement_loop,
                scenario,
                max_attempts,
                verbose,
            ): scenario
            for scenario in scenarios
        }

        for future in as_completed(future_to_scenario):
            scenario = future_to_scenario[future]
            try:
                result = future.result()
                results.append(result)

                status = "PASS" if result.passed else "FAIL"
                attempts_str = f"{result.total_attempts}/{max_attempts} attempts"
                duration_str = f"{result.duration_seconds:.1f}s"
                print(f"  [{scenario}] {status} ({attempts_str}, {duration_str})", flush=True)

            except Exception as e:
                results.append(ScenarioResult(
                    scenario=scenario,
                    passed=False,
                    total_attempts=0,
                    duration_seconds=0,
                    error=str(e),
                ))
                print(f"  [{scenario}] ERROR: {e}", flush=True)

    total_duration = time.time() - start_time
    passed_count = sum(1 for r in results if r.passed)

    return OrchestratorResult(
        total=len(results),
        passed=passed_count,
        failed=len(results) - passed_count,
        duration_seconds=total_duration,
        max_attempts=max_attempts,
        results=results,
    )


def generate_summary_report(result: OrchestratorResult, output_path: Path) -> None:
    """Generate a markdown summary report."""
    content = [
        "# Parallel Refinement Results\n\n",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n",
        "## Summary\n\n",
        "| Metric | Value |\n",
        "|--------|-------|\n",
        f"| Total Scenarios | {result.total} |\n",
        f"| Passed | {result.passed} |\n",
        f"| Failed | {result.failed} |\n",
        f"| Max Attempts | {result.max_attempts} |\n",
        f"| Total Duration | {result.duration_seconds:.1f}s |\n\n",
        "## Scenario Results\n\n",
        "| Scenario | Status | Attempts | Duration | Last Failure |\n",
        "|----------|--------|----------|----------|-------------|\n",
    ]

    for r in sorted(result.results, key=lambda x: x.scenario):
        status = "PASS" if r.passed else "FAIL"
        last_fail = ""
        if not r.passed and r.attempts:
            last = r.attempts[-1]
            if last.prompt_index is not None:
                last_fail = f"prompt {last.prompt_index} ({last.quality or 'unknown'})"
            elif last.error:
                last_fail = last.error[:30] + "..."
        content.append(
            f"| {r.scenario} | {status} | {r.total_attempts}/{result.max_attempts} | "
            f"{r.duration_seconds:.1f}s | {last_fail} |\n"
        )

    # Failed scenarios detail
    failed = [r for r in result.results if not r.passed]
    if failed:
        content.append("\n## Failed Scenarios Detail\n\n")
        for r in failed:
            content.append(f"### {r.scenario}\n\n")
            if r.error:
                content.append(f"**Error:** {r.error}\n\n")
            for a in r.attempts:
                status = "PASS" if a.passed else "FAIL"
                content.append(f"- Attempt {a.attempt}: {status}")
                if a.prompt_index is not None:
                    content.append(f" at prompt {a.prompt_index}")
                if a.quality:
                    content.append(f" (quality: {a.quality})")
                if a.files_changed:
                    content.append(f" - changed: {', '.join(a.files_changed)}")
                content.append("\n")
            content.append("\n")

    content.append("## Retry Commands\n\n")
    content.append("```bash\n")
    for r in failed:
        content.append(f"make refine-skill SCENARIO={r.scenario} MAX_ATTEMPTS=5\n")
    content.append("```\n")

    output_path.write_text("".join(content))


def main():
    parser = argparse.ArgumentParser(
        description="Parallel Skill Refinement Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --scenarios all
    %(prog)s --scenarios search,issue --max-attempts 5
    %(prog)s --scenarios search --max-workers 2 --verbose
        """
    )
    parser.add_argument(
        "--scenarios",
        default="all",
        help="Comma-separated scenarios or 'all' (default: all)"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum parallel refinement loops (default: 4)"
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=5,
        help="Maximum fix attempts per scenario (default: 5)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT,
        help="Directory for summary report (default: project root)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit"
    )
    args = parser.parse_args()

    if args.list_scenarios:
        print("Available scenarios:")
        for s in ALL_SCENARIOS:
            prompts_file = SCENARIOS_DIR / f"{s}.prompts"
            exists = "exists" if prompts_file.exists() else "MISSING"
            print(f"  {s} ({exists})")
        sys.exit(0)

    # Parse and validate scenarios
    scenarios = parse_scenario_arg(args.scenarios)
    missing = validate_scenarios(scenarios)
    if missing:
        print(f"Error: Scenarios not found: {', '.join(missing)}")
        sys.exit(1)

    plugin_path, _, _ = get_plugin_paths()
    if not plugin_path.exists():
        print(f"Error: Plugin not found at {plugin_path}")
        print("Set JIRA_SKILLS_PATH environment variable")
        sys.exit(1)

    if not ensure_network_exists():
        print(f"Error: Could not create network {DEMO_NETWORK}")
        sys.exit(1)

    # Run parallel refinement
    result = run_parallel_refinement(
        scenarios=scenarios,
        max_workers=args.max_workers,
        max_attempts=args.max_attempts,
        verbose=args.verbose,
    )

    # Generate summary report
    report_path = args.output_dir / "REFINE-SUMMARY.md"
    generate_summary_report(result, report_path)

    # Print summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total:        {result.total}")
    print(f"Passed:       {result.passed}")
    print(f"Failed:       {result.failed}")
    print(f"Max Attempts: {result.max_attempts}")
    print(f"Duration:     {result.duration_seconds:.1f}s")
    print(f"\nReport: {report_path}")

    if result.failed > 0:
        print("\nFailed scenarios:")
        for r in result.results:
            if not r.passed:
                print(f"  - {r.scenario}")

    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
