#!/usr/bin/env python3
"""
Parallel Mock Skill Testing Orchestrator.

Runs multiple skill test scenarios in parallel using Docker containers
with mocked JIRA API. Collects results and generates PLAN files for failures.

Usage:
    python parallel-mock-test.py --scenarios all
    python parallel-mock-test.py --scenarios search,issue,agile --max-workers 4

Environment:
    JIRA_SKILLS_PATH: Path to Jira-Assistant-Skills repo (default: auto-detected)
"""

import argparse
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
    get_claude_token,
    get_plugin_paths,
    parse_scenario_arg,
    parse_test_output,
    validate_scenarios,
)

# Default timeout per scenario (20 minutes - Claude calls take time even with mocks)
DEFAULT_SCENARIO_TIMEOUT = 1200


@dataclass
class ScenarioResult:
    """Result from running a single scenario test."""
    scenario: str
    passed: bool
    duration_seconds: float
    fix_context: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class OrchestratorResult:
    """Aggregated results from all scenario tests."""
    total: int
    passed: int
    failed: int
    duration_seconds: float
    results: list[ScenarioResult] = field(default_factory=list)


def run_scenario_test(scenario: str, verbose: bool = False, timeout: int = DEFAULT_SCENARIO_TIMEOUT) -> ScenarioResult:
    """
    Run a single scenario test in a Docker container.

    Returns ScenarioResult with pass/fail status and fix_context if failed.
    """
    start_time = time.time()

    plugin_path, lib_path, dist_path = get_plugin_paths()

    if not plugin_path.exists():
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            duration_seconds=0,
            error=f"Plugin not found at {plugin_path}",
        )

    # Get Claude auth token
    claude_token = get_claude_token()

    # Build docker command (matching test-skill-mock-dev pattern)
    cmd = [
        "docker", "run", "--rm",
        "--network", DEMO_NETWORK,
        "-e", "JIRA_MOCK_MODE=true",
        "-e", "PYTHONPATH=/workspace/patches",
        "-e", "OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318",
        "-e", "LOKI_ENDPOINT=http://lgtm:3100",
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={claude_token}",
        "-v", f"{plugin_path}:/home/devuser/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev:ro",
        "-v", f"{dist_path}:/opt/jira-dist:ro",
        "-v", f"{PROJECT_ROOT}/demo-container/patches:/workspace/patches:ro",
        "--entrypoint", "bash",
        "jira-demo-container:latest",
        "-c",
    ]

    # Inner command: install wheel (for jira-as CLI), symlink plugin, run test from /tmp with fix-context
    inner_cmd = (
        "pip install -q /opt/jira-dist/*.whl 2>/dev/null; "
        "rm -f ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        "ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        f"cd /tmp && python /workspace/skill-test.py /workspace/scenarios/{scenario}.prompts "
        f"--mock --fix-context {JIRA_SKILLS_PATH}"
    )

    cmd.append(inner_cmd)

    if verbose:
        print(f"  [{scenario}] Starting...", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.time() - start_time

        # Parse output
        parsed = parse_test_output(result.stdout)

        if parsed is not None and parsed.get("status") == "all_passed":
            return ScenarioResult(scenario=scenario, passed=True, duration_seconds=duration)

        if result.returncode == 0:
            return ScenarioResult(scenario=scenario, passed=True, duration_seconds=duration)

        if parsed is not None:
            return ScenarioResult(
                scenario=scenario,
                passed=False,
                duration_seconds=duration,
                fix_context=parsed,
            )

        # Could not parse JSON - include stderr for debugging
        error_detail = result.stderr[-1000:] if result.stderr else result.stdout[-500:]
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            duration_seconds=duration,
            error=f"Could not parse fix context. Output: {error_detail}",
        )

    except subprocess.TimeoutExpired:
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            duration_seconds=timeout,
            error=f"Test timed out after {timeout // 60} minutes",
        )
    except Exception as e:
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            duration_seconds=time.time() - start_time,
            error=str(e),
        )


def generate_plan_file(result: ScenarioResult, output_dir: Path) -> Path:
    """Generate PLAN-{scenario}-mock.md file from failure context."""
    plan_path = output_dir / f"PLAN-{result.scenario}-mock.md"

    content = [f"# PLAN: {result.scenario.title()} Scenario Mock API Coverage\n\n"]
    content.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")

    if result.error:
        content.append("## Error\n\n")
        content.append(f"Test failed with error:\n```\n{result.error}\n```\n\n")

    elif result.fix_context:
        failure = result.fix_context.get("failure", {})

        # Summary
        content.append("## Summary\n\n")
        quality = failure.get("quality", "unknown")
        content.append(f"The `{result.scenario}` scenario failed with quality rating: **{quality}**\n\n")

        # Failure Details
        content.append("## Failure Details\n\n")
        prompt_text = failure.get("prompt_text", "N/A")
        if len(prompt_text) > 200:
            prompt_text = prompt_text[:200] + "..."
        content.append(f"- **Prompt**: {prompt_text}\n")
        content.append(f"- **Tools Called**: {', '.join(failure.get('tools_called', []))}\n")
        content.append(f"- **Quality**: {failure.get('quality', 'N/A')}\n")
        content.append(f"- **Tool Accuracy**: {failure.get('tool_accuracy', 'N/A')}\n\n")

        # Assertions table
        content.append("## Failed Assertions\n\n")
        content.append("| Type | Assertion | Passed | Detail |\n")
        content.append("|------|-----------|--------|--------|\n")

        for a in failure.get("tool_assertions", []):
            status = "PASS" if a.get("passed") else "**FAIL**"
            detail = a.get("detail", "").replace("|", "\\|")[:50]
            content.append(f"| Tool | {a.get('desc', '')} | {status} | {detail} |\n")

        for a in failure.get("text_assertions", []):
            status = "PASS" if a.get("passed") else "**FAIL**"
            detail = a.get("detail", "").replace("|", "\\|")[:50]
            content.append(f"| Text | {a.get('desc', '')} | {status} | {detail} |\n")

        content.append("\n")

        # Judge analysis
        content.append("## Judge Analysis\n\n")
        content.append(f"**Reasoning:** {failure.get('reasoning', 'N/A')}\n\n")
        content.append(f"**Refinement Suggestion:** {failure.get('refinement_suggestion', 'N/A')}\n\n")

        if failure.get("expectation_suggestion"):
            content.append(f"**Expectation Suggestion:** {failure.get('expectation_suggestion')}\n\n")

        # Relevant files
        relevant_files = result.fix_context.get("relevant_files", {})
        if relevant_files:
            content.append("## Relevant Files\n\n")
            for path, file_content in relevant_files.items():
                content.append(f"### `{path}`\n\n")
                truncated = file_content[:2000]
                if len(file_content) > 2000:
                    truncated += "\n... (truncated)"
                content.append(f"```\n{truncated}\n```\n\n")

    # Test commands
    content.append("## Test Commands\n\n")
    content.append("```bash\n")
    content.append("# Single scenario test\n")
    content.append(f"make test-skill-mock-dev SCENARIO={result.scenario}\n\n")
    content.append("# With conversation mode\n")
    content.append(f"make test-skill-mock-dev SCENARIO={result.scenario} CONVERSATION=1 FAIL_FAST=1\n")
    content.append("```\n")

    plan_path.write_text("".join(content))
    return plan_path


def run_parallel_tests(
    scenarios: list[str],
    max_workers: int = 4,
    verbose: bool = False,
    timeout: int = DEFAULT_SCENARIO_TIMEOUT,
) -> OrchestratorResult:
    """Run all scenarios in parallel and collect results."""
    start_time = time.time()

    results: list[ScenarioResult] = []

    print(f"Running {len(scenarios)} scenarios with {max_workers} workers...")
    print(f"Scenarios: {', '.join(scenarios)}\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all scenarios
        future_to_scenario = {
            executor.submit(run_scenario_test, scenario, verbose, timeout): scenario
            for scenario in scenarios
        }

        # Collect results as they complete
        for future in as_completed(future_to_scenario):
            scenario = future_to_scenario[future]
            try:
                result = future.result()
                results.append(result)

                status = "PASS" if result.passed else "FAIL"
                duration_str = f"{result.duration_seconds:.1f}s"

                if result.error:
                    print(f"  [{scenario}] {status} ({duration_str}) - {result.error[:50]}...")
                else:
                    print(f"  [{scenario}] {status} ({duration_str})")

            except Exception as e:
                results.append(ScenarioResult(
                    scenario=scenario,
                    passed=False,
                    duration_seconds=0,
                    error=str(e),
                ))
                print(f"  [{scenario}] ERROR: {e}")

    total_duration = time.time() - start_time
    passed_count = sum(1 for r in results if r.passed)

    return OrchestratorResult(
        total=len(results),
        passed=passed_count,
        failed=len(results) - passed_count,
        duration_seconds=total_duration,
        results=results,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Parallel Mock Skill Testing Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --scenarios all
    %(prog)s --scenarios search,issue,agile --max-workers 4
    %(prog)s --scenarios search --verbose
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
        help="Maximum parallel containers (default: 4)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT,
        help="Directory for PLAN files (default: project root)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_SCENARIO_TIMEOUT,
        help=f"Timeout per scenario in seconds (default: {DEFAULT_SCENARIO_TIMEOUT})"
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

    # List scenarios
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
        print("Use --list-scenarios to see available scenarios")
        sys.exit(1)

    # Check plugin path
    plugin_path, lib_path, _ = get_plugin_paths()
    if not plugin_path.exists():
        print(f"Error: Plugin not found at {plugin_path}")
        print("Set JIRA_SKILLS_PATH environment variable")
        sys.exit(1)

    # Ensure network exists
    if not ensure_network_exists():
        print(f"Error: Could not create network {DEMO_NETWORK}")
        sys.exit(1)

    # Run tests
    orchestrator_result = run_parallel_tests(
        scenarios=scenarios,
        max_workers=args.max_workers,
        verbose=args.verbose,
        timeout=args.timeout,
    )

    # Generate PLAN files for failures
    print(f"\n{'=' * 60}")
    print("GENERATING PLAN FILES")
    print(f"{'=' * 60}\n")

    plan_files = []
    for result in orchestrator_result.results:
        if not result.passed:
            plan_path = generate_plan_file(result, args.output_dir)
            plan_files.append(plan_path)
            print(f"  Generated: {plan_path.name}")

    if not plan_files:
        print("  No failures - no PLAN files generated")

    # Print summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total:    {orchestrator_result.total}")
    print(f"Passed:   {orchestrator_result.passed}")
    print(f"Failed:   {orchestrator_result.failed}")
    print(f"Duration: {orchestrator_result.duration_seconds:.1f}s")

    if plan_files:
        print(f"\nPLAN files generated ({len(plan_files)}):")
        for pf in sorted(plan_files):
            print(f"  - {pf.name}")

    # Exit with failure if any tests failed
    sys.exit(0 if orchestrator_result.failed == 0 else 1)


if __name__ == "__main__":
    main()
