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
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Constants
DEMO_NETWORK = os.environ.get("DEMO_NETWORK", "demo-telemetry-network")
PROJECT_ROOT = Path(__file__).parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "demo-container" / "scenarios"
SECRETS_DIR = PROJECT_ROOT / "secrets"

# Default JIRA skills path - can be overridden via env var
JIRA_SKILLS_PATH = os.environ.get(
    "JIRA_SKILLS_PATH",
    "/Users/jasonkrueger/IdeaProjects/Jira-Assistant-Skills"
)

# All main scenarios (excluding test scenarios)
ALL_SCENARIOS = [
    "admin", "agile", "bulk", "collaborate", "dev",
    "fields", "issue", "jsm", "relationships", "search", "time"
]

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


def ensure_network_exists() -> bool:
    """Ensure the telemetry network exists, create if needed."""
    result = subprocess.run(
        ["docker", "network", "inspect", DEMO_NETWORK],
        capture_output=True
    )
    if result.returncode != 0:
        print(f"Creating network: {DEMO_NETWORK}")
        create = subprocess.run(
            ["docker", "network", "create", DEMO_NETWORK],
            capture_output=True
        )
        return create.returncode == 0
    return True


def get_plugin_paths() -> tuple[Path, Path]:
    """Get paths to JIRA plugin and library."""
    skills_path = Path(JIRA_SKILLS_PATH)

    # Try different plugin path patterns
    plugin_path = skills_path / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = skills_path / "jira-assistant-skills"

    lib_path = skills_path / "jira-assistant-skills-lib"

    return plugin_path, lib_path


def run_scenario_test(scenario: str, verbose: bool = False, timeout: int = DEFAULT_SCENARIO_TIMEOUT) -> ScenarioResult:
    """
    Run a single scenario test in a Docker container.

    Returns ScenarioResult with pass/fail status and fix_context if failed.
    """
    start_time = time.time()

    plugin_path, lib_path = get_plugin_paths()

    if not plugin_path.exists():
        return ScenarioResult(
            scenario=scenario,
            passed=False,
            duration_seconds=0,
            error=f"Plugin not found at {plugin_path}",
        )

    # Build docker command (matching test-skill-mock-dev pattern)
    cmd = [
        "docker", "run", "--rm",
        "--network", DEMO_NETWORK,
        "-e", "JIRA_MOCK_MODE=true",
        "-e", "OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318",
        "-e", "LOKI_ENDPOINT=http://lgtm:3100",
        "-v", f"{SECRETS_DIR}/.credentials.json:/home/devuser/.claude/.credentials.json:ro",
        "-v", f"{SECRETS_DIR}/.claude.json:/home/devuser/.claude/.claude.json:ro",
        "-v", f"{plugin_path}:/home/devuser/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev:ro",
        "-v", f"{lib_path}:/opt/jira-lib:ro",
        "--entrypoint", "bash",
        "jira-demo-container:latest",
        "-c",
    ]

    # Inner command: install lib, symlink plugin, run test with fix-context
    inner_cmd = (
        "pip install -q -e /opt/jira-lib 2>/dev/null; "
        "rm -f ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        "ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        f"python /workspace/skill-test.py /workspace/scenarios/{scenario}.prompts "
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
        if result.returncode == 0:
            # Check if it's actually all passed (fix-context returns JSON even on success)
            try:
                output = json.loads(result.stdout.strip())
                if output.get("status") == "all_passed":
                    return ScenarioResult(
                        scenario=scenario,
                        passed=True,
                        duration_seconds=duration,
                    )
            except json.JSONDecodeError:
                pass

            # Assume passed if exit code 0
            return ScenarioResult(
                scenario=scenario,
                passed=True,
                duration_seconds=duration,
            )

        # Non-zero exit - try to parse fix context from stdout
        try:
            fix_ctx = json.loads(result.stdout.strip())
            if fix_ctx.get("status") == "all_passed":
                return ScenarioResult(
                    scenario=scenario,
                    passed=True,
                    duration_seconds=duration,
                )
            return ScenarioResult(
                scenario=scenario,
                passed=False,
                duration_seconds=duration,
                fix_context=fix_ctx,
            )
        except json.JSONDecodeError:
            # Try to find JSON in output (may have non-JSON preamble)
            for line in reversed(result.stdout.strip().split("\n")):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        fix_ctx = json.loads(line)
                        return ScenarioResult(
                            scenario=scenario,
                            passed=False,
                            duration_seconds=duration,
                            fix_context=fix_ctx,
                        )
                    except json.JSONDecodeError:
                        continue

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
    content.append(f"# Single scenario test\n")
    content.append(f"make test-skill-mock-dev SCENARIO={result.scenario}\n\n")
    content.append(f"# With conversation mode\n")
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

    # Parse scenarios
    if args.scenarios == "all":
        scenarios = ALL_SCENARIOS
    else:
        scenarios = [s.strip() for s in args.scenarios.split(",")]

    # Validate scenarios exist
    missing = []
    for s in scenarios:
        if not (SCENARIOS_DIR / f"{s}.prompts").exists():
            missing.append(s)

    if missing:
        print(f"Error: Scenarios not found: {', '.join(missing)}")
        print(f"Use --list-scenarios to see available scenarios")
        sys.exit(1)

    # Check plugin path
    plugin_path, lib_path = get_plugin_paths()
    if not plugin_path.exists():
        print(f"Error: Plugin not found at {plugin_path}")
        print(f"Set JIRA_SKILLS_PATH environment variable")
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
