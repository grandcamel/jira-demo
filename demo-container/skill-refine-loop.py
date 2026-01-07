#!/usr/bin/env python3
"""
Skill Refinement Loop - Iteratively test and fix JIRA Assistant Skills.

Runs skill tests, collects failures, invokes a fix agent to make changes,
then re-tests until all pass or max attempts reached.

Usage:
    python skill-refine-loop.py --scenario search --jira-skills-path /path/to/skills
    python skill-refine-loop.py --scenario search --max-attempts 5 --verbose
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


# =============================================================================
# Configuration
# =============================================================================

JIRA_DEMO_PATH = Path(__file__).parent.parent
DEFAULT_SKILLS_PATH = "/Users/jasonkrueger/IdeaProjects/Jira-Assistant-Skills"


# =============================================================================
# Test Runner
# =============================================================================


def run_skill_test(
    scenario: str,
    jira_skills_path: str,
    model: str = "sonnet",
    judge_model: str = "haiku",
    prompt_index: int | None = None,
    fix_context: bool = False,
    verbose: bool = False,
) -> tuple[bool, dict | None]:
    """
    Run skill test with local source mounts.

    Returns: (all_passed, fix_context_or_none)
    """
    # Determine plugin and library paths
    plugin_path = Path(jira_skills_path) / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = Path(jira_skills_path) / "jira-assistant-skills"
    lib_path = Path(jira_skills_path) / "jira-assistant-skills-lib"

    # Build docker command
    cmd = [
        "docker", "run", "--rm",
        "-e", f"JIRA_API_TOKEN={os.environ.get('JIRA_API_TOKEN', '')}",
        "-e", f"JIRA_EMAIL={os.environ.get('JIRA_EMAIL', '')}",
        "-e", f"JIRA_SITE_URL={os.environ.get('JIRA_SITE_URL', '')}",
        "-v", f"{JIRA_DEMO_PATH}/secrets/.credentials.json:/home/devuser/.claude/.credentials.json:ro",
        "-v", f"{JIRA_DEMO_PATH}/secrets/.claude.json:/home/devuser/.claude/.claude.json:ro",
        "-v", f"{plugin_path}:/home/devuser/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev:ro",
        "-v", f"{lib_path}:/opt/jira-lib:ro",
        "--entrypoint", "bash",
        "jira-demo-container:latest",
        "-c",
    ]

    # Build the inner command
    inner_cmd = (
        "pip install -q -e /opt/jira-lib 2>/dev/null; "
        "rm -f ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        "ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        f"python /workspace/skill-test.py /workspace/scenarios/{scenario}.prompts "
        f"--model {model} --judge-model {judge_model}"
    )

    if prompt_index is not None:
        inner_cmd += f" --prompt-index {prompt_index}"

    if fix_context:
        inner_cmd += f" --fix-context {jira_skills_path}"

    if verbose:
        inner_cmd += " --verbose"

    cmd.append(inner_cmd)

    if verbose:
        print(f"Running: docker run ... (scenario={scenario})")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )
    except subprocess.TimeoutExpired:
        print("Error: Test timed out")
        return False, None
    except Exception as e:
        print(f"Error running test: {e}")
        return False, None

    # Parse output
    if fix_context:
        # Output is fix context JSON
        try:
            ctx = json.loads(result.stdout)
            if ctx.get("status") == "all_passed":
                return True, None
            return False, ctx
        except json.JSONDecodeError:
            # Might have non-JSON output before the JSON
            lines = result.stdout.strip().split("\n")
            for line in reversed(lines):
                try:
                    ctx = json.loads(line)
                    if ctx.get("status") == "all_passed":
                        return True, None
                    return False, ctx
                except json.JSONDecodeError:
                    continue
            print(f"Error: Could not parse fix context from output")
            print(result.stdout[-1000:])
            return False, None
    else:
        # Check exit code for pass/fail
        return result.returncode == 0, None


# =============================================================================
# Fix Agent
# =============================================================================


def run_fix_agent(
    fix_context: dict,
    jira_skills_path: str,
    verbose: bool = False,
) -> dict:
    """
    Run the skill-fix agent to make changes based on failure context.

    Returns: {"success": bool, "files_changed": [...], "summary": "..."}
    """
    # Build the prompt for the fix agent
    failure = fix_context["failure"]

    prompt = f"""You are a skill refinement agent. A JIRA Assistant Skill test has failed and you need to fix it.

## Failure Details

**Prompt that failed:**
{failure['prompt_text']}

**Tools called:** {failure['tools_called']}

**Tool Assertions:**
{json.dumps(failure['tool_assertions'], indent=2)}

**Text Assertions:**
{json.dumps(failure['text_assertions'], indent=2)}

**Quality Rating:** {failure['quality']}
**Tool Accuracy:** {failure['tool_accuracy']}

**Judge Reasoning:**
{failure['reasoning']}

**Refinement Suggestion:**
{failure['refinement_suggestion']}

## Relevant Files

The skill files are located at: {jira_skills_path}/jira-assistant-skills/skills/
The library files are located at: {jira_skills_path}/jira-assistant-skills-lib/src/jira_assistant_skills_lib/

Current relevant file contents:
"""

    for path, content in fix_context.get("relevant_files", {}).items():
        prompt += f"\n### {path}\n```\n{content[:3000]}\n```\n"

    if fix_context.get("git_history"):
        prompt += "\n## Recent Git History\n"
        for commit in fix_context["git_history"]:
            prompt += f"- {commit['commit']}: {commit['message']}\n"

    prompt += """

## Your Task

Analyze the failure and make targeted changes to fix it. Focus on:

1. **If tool selection is wrong**: Update the skill description to better trigger on this type of query
2. **If tool worked but output is wrong**: Check if the skill examples or instructions need improvement
3. **If there's an API error**: Check the library code for bugs

Make minimal, focused changes. Edit the actual files - do not just describe what to change.

After making changes, provide a brief summary of what you changed and why.
"""

    if verbose:
        print(f"Running fix agent with context for prompt: {failure['prompt_text'][:50]}...")

    # Run Claude to make the fixes
    cmd = [
        "claude",
        "-p", prompt,
        "--model", "sonnet",
        "--dangerously-skip-permissions",
        "--output-format", "text",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=jira_skills_path,  # Run in skills directory so edits work
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "files_changed": [], "summary": "Fix agent timed out"}
    except Exception as e:
        return {"success": False, "files_changed": [], "summary": f"Fix agent error: {e}"}

    # Parse output to find what changed
    output = result.stdout

    # Look for file edit indicators
    files_changed = []
    if "Edit" in output or "edited" in output.lower() or "updated" in output.lower():
        # Try to extract file names from output
        import re
        file_patterns = re.findall(r'(?:skills/|lib/)[^\s\'"]+\.(?:md|py)', output)
        files_changed = list(set(file_patterns))

    return {
        "success": result.returncode == 0,
        "files_changed": files_changed,
        "summary": output[-500:] if len(output) > 500 else output,
    }


# =============================================================================
# Main Loop
# =============================================================================


def run_refinement_loop(
    scenario: str,
    jira_skills_path: str,
    max_attempts: int = 3,
    model: str = "sonnet",
    judge_model: str = "haiku",
    verbose: bool = False,
) -> bool:
    """
    Run the refinement loop until all tests pass or max attempts reached.

    Returns: True if all tests pass, False otherwise
    """
    print(f"{'=' * 70}")
    print(f"SKILL REFINEMENT LOOP")
    print(f"{'=' * 70}")
    print(f"Scenario: {scenario}")
    print(f"Skills path: {jira_skills_path}")
    print(f"Max attempts: {max_attempts}")
    print(f"Model: {model}, Judge: {judge_model}")
    print(f"{'=' * 70}")
    print()

    for attempt in range(1, max_attempts + 1):
        print(f"[Attempt {attempt}/{max_attempts}]")
        print("-" * 40)

        # Run test with fix context output
        all_passed, fix_ctx = run_skill_test(
            scenario=scenario,
            jira_skills_path=jira_skills_path,
            model=model,
            judge_model=judge_model,
            fix_context=True,
            verbose=verbose,
        )

        if all_passed:
            print()
            print(f"{'=' * 70}")
            print(f"SUCCESS: All tests passed on attempt {attempt}")
            print(f"{'=' * 70}")
            return True

        if not fix_ctx:
            print("Error: Test failed but no fix context available")
            continue

        failure = fix_ctx.get("failure", {})
        print(f"Failed prompt: {failure.get('prompt_text', 'unknown')[:60]}...")
        print(f"Quality: {failure.get('quality', 'unknown')}")
        print(f"Refinement suggestion: {failure.get('refinement_suggestion', 'none')[:100]}...")
        print()

        # Run fix agent
        print("Running fix agent...")
        fix_result = run_fix_agent(fix_ctx, jira_skills_path, verbose=verbose)

        if fix_result["files_changed"]:
            print(f"Files changed: {fix_result['files_changed']}")
        else:
            print("No files changed (fix may have failed)")

        print(f"Summary: {fix_result['summary'][:200]}...")
        print()

    print(f"{'=' * 70}")
    print(f"FAILED: Max attempts ({max_attempts}) reached without passing all tests")
    print(f"{'=' * 70}")
    return False


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Skill Refinement Loop - Iteratively test and fix JIRA Assistant Skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python skill-refine-loop.py --scenario search
    python skill-refine-loop.py --scenario search --max-attempts 5
    python skill-refine-loop.py --scenario search --jira-skills-path /custom/path
        """,
    )
    parser.add_argument("--scenario", required=True, help="Scenario name (e.g., search, issue)")
    parser.add_argument("--jira-skills-path", default=DEFAULT_SKILLS_PATH,
                        help=f"Path to Jira-Assistant-Skills repo (default: {DEFAULT_SKILLS_PATH})")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Maximum fix attempts before giving up (default: 3)")
    parser.add_argument("--model", default="sonnet", help="Model for running prompts (default: sonnet)")
    parser.add_argument("--judge-model", default="haiku", help="Model for LLM judge (default: haiku)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Validate skills path
    skills_path = Path(args.jira_skills_path)
    plugin_path = skills_path / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = skills_path / "jira-assistant-skills"
    if not plugin_path.exists():
        print(f"Error: Plugin not found at {skills_path}/plugins/jira-assistant-skills or {skills_path}/jira-assistant-skills")
        sys.exit(1)

    # Check environment
    if not os.environ.get("JIRA_API_TOKEN"):
        print("Warning: JIRA_API_TOKEN not set")

    success = run_refinement_loop(
        scenario=args.scenario,
        jira_skills_path=str(skills_path),
        max_attempts=args.max_attempts,
        model=args.model,
        judge_model=args.judge_model,
        verbose=args.verbose,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
