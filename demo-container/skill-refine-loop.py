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
import re
import subprocess
import sys
from pathlib import Path


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
    conversation: bool = True,
    fail_fast: bool = True,
    checkpoint_file: str | None = None,
    fork_from: int | None = None,
) -> tuple[bool, dict | None]:
    """
    Run skill test with local source mounts.

    Returns: (all_passed, fix_context_or_none)
    """
    # Determine plugin and library paths
    plugin_path = Path(jira_skills_path) / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = Path(jira_skills_path) / "jira-assistant-skills"
    lib_path = Path(jira_skills_path) / "jira-as"

    # Ensure checkpoint directory exists on host
    checkpoint_dir = Path("/tmp/checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

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
        "-v", "/tmp/checkpoints:/tmp/checkpoints",  # Persist checkpoints across container runs
        "--entrypoint", "bash",
        "jira-demo-container:latest",
        "-c",
    ]

    # Build the inner command
    inner_cmd = (
        "pip install -q -e /opt/jira-lib 2>/dev/null; "
        "rm -f ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        "ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null; "
        "mkdir -p /tmp/checkpoints; "  # Ensure checkpoint dir exists in container
        f"python /workspace/skill-test.py /workspace/scenarios/{scenario}.prompts "
        f"--model {model} --judge-model {judge_model}"
    )

    # Add conversation mode and fail-fast for checkpoint-based iteration
    if conversation:
        inner_cmd += " --conversation"
    if fail_fast:
        inner_cmd += " --fail-fast"
    if checkpoint_file:
        inner_cmd += f" --checkpoint-file {checkpoint_file}"
    if fork_from is not None:
        inner_cmd += f" --fork-from {fork_from}"

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
        # Output is fix context JSON (may be multi-line)
        stdout = result.stdout.strip()

        # Try to parse the whole stdout as JSON
        try:
            ctx = json.loads(stdout)
            if isinstance(ctx, dict):
                if ctx.get("status") == "all_passed":
                    return True, None
                return False, ctx
        except json.JSONDecodeError:
            pass

        # Find JSON object in output - look for opening brace and parse from there
        brace_idx = stdout.find("{")
        if brace_idx >= 0:
            try:
                ctx = json.loads(stdout[brace_idx:])
                if isinstance(ctx, dict):
                    if ctx.get("status") == "all_passed":
                        return True, None
                    return False, ctx
            except json.JSONDecodeError:
                pass

        print("Error: Could not parse fix context from output")
        print(f"stdout length: {len(result.stdout)}")
        print(f"stderr length: {len(result.stderr)}")
        print(f"stdout (last 2000 chars): {result.stdout[-2000:]}")
        print(f"stderr (last 500 chars): {result.stderr[-500:]}")
        return False, None
    else:
        # Check exit code for pass/fail
        return result.returncode == 0, None


# =============================================================================
# Fix Agent
# =============================================================================


def _parse_fix_agent_output(output: str, default_session_id: str | None) -> str | None:
    """Extract session ID from fix agent JSON output."""
    try:
        output_data = json.loads(output)
        return output_data.get("session_id", default_session_id)
    except json.JSONDecodeError:
        return default_session_id


def _extract_text_from_output(output: str) -> str:
    """Extract text content from fix agent output (handles JSON or raw text)."""
    try:
        output_data = json.loads(output)
        if isinstance(output_data.get("result"), str):
            return output_data["result"]
        if isinstance(output_data.get("content"), list):
            return "\n".join(
                block.get("text", "") for block in output_data["content"]
                if block.get("type") == "text"
            )
    except json.JSONDecodeError:
        pass
    return output


def run_fix_agent(
    fix_context: dict,
    jira_skills_path: str,
    verbose: bool = False,
    session_id: str | None = None,
    attempt_history: list[dict] | None = None,
) -> dict:
    """
    Run the skill-fix agent to make changes based on failure context.

    Args:
        fix_context: Context about the failure from skill-test.py
        jira_skills_path: Path to the JIRA skills repo
        verbose: Enable verbose output
        session_id: Optional session ID to continue previous fix session
        attempt_history: List of previous fix attempts for context

    Returns: {"success": bool, "files_changed": [...], "summary": "...", "session_id": "..."}
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
The library files are located at: {jira_skills_path}/jira-as/src/jira_as/

Current relevant file contents:
"""

    for path, content in fix_context.get("relevant_files", {}).items():
        prompt += f"\n### {path}\n```\n{content[:3000]}\n```\n"

    if fix_context.get("git_history"):
        prompt += "\n## Recent Git History\n"
        for commit in fix_context["git_history"]:
            prompt += f"- {commit['commit']}: {commit['message']}\n"

    # Add previous attempt history for cumulative context
    if attempt_history:
        prompt += "\n## Previous Fix Attempts (this session)\n"
        for h in attempt_history:
            prompt += f"- Attempt {h['attempt']}: "
            if h.get('files'):
                prompt += f"Changed {h['files']}, "
            prompt += f"Result: {h['result']}\n"
            if h.get('error_summary'):
                prompt += f"  Error: {h['error_summary']}\n"

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
        if session_id:
            print(f"Continuing session: {session_id}")

    # Run Claude to make the fixes
    cmd = [
        "claude",
        "-p", prompt,
        "--model", "sonnet",
        "--dangerously-skip-permissions",
        "--output-format", "json",  # JSON format to capture session ID
    ]

    # Continue previous session if available
    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=jira_skills_path,  # Run in skills directory so edits work
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "files_changed": [], "summary": "Fix agent timed out", "session_id": session_id}
    except Exception as e:
        return {"success": False, "files_changed": [], "summary": f"Fix agent error: {e}", "session_id": session_id}

    # Parse output to find what changed
    output = result.stdout
    new_session_id = _parse_fix_agent_output(output, session_id)
    output = _extract_text_from_output(output)

    # Look for file edit indicators
    files_changed = []
    if "Edit" in output or "edited" in output.lower() or "updated" in output.lower():
        file_patterns = re.findall(r'(?:skills/|lib/)[^\s\'"]+\.(?:md|py)', output)
        files_changed = list(set(file_patterns))

    return {
        "success": result.returncode == 0,
        "files_changed": files_changed,
        "summary": output[-500:] if len(output) > 500 else output,
        "session_id": new_session_id,
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

    Uses checkpoint-based iteration:
    - Fail-fast: Stop at first failing prompt
    - Fork from checkpoint: On retry, skip passed prompts
    - Single fix session: Maintain context across fix attempts

    Returns: True if all tests pass, False otherwise
    """
    print(f"{'=' * 70}")
    print("SKILL REFINEMENT LOOP (with checkpoint-based iteration)")
    print(f"{'=' * 70}")
    print(f"Scenario: {scenario}")
    print(f"Skills path: {jira_skills_path}")
    print(f"Max attempts: {max_attempts}")
    print(f"Model: {model}, Judge: {judge_model}")
    print(f"{'=' * 70}")
    print()

    # State for checkpoint-based iteration
    checkpoint_file = f"/tmp/checkpoints/{scenario}.json"
    fix_session_id: str | None = None
    attempt_history: list[dict] = []
    last_failing_prompt_index: int | None = None

    for attempt in range(1, max_attempts + 1):
        print(f"[Attempt {attempt}/{max_attempts}]")
        print("-" * 40)

        # Determine if we should fork from checkpoint
        fork_from: int | None = None
        prompt_index: int | None = None

        if attempt > 1 and last_failing_prompt_index is not None:
            # Fork from checkpoint just before the failing prompt
            if last_failing_prompt_index > 0:
                fork_from = last_failing_prompt_index - 1
                prompt_index = last_failing_prompt_index
                print(f"Forking from checkpoint {fork_from}, running prompt {prompt_index}")
            else:
                # First prompt failed, no checkpoint to fork from
                prompt_index = 0
                print("First prompt failed, running from start")

        # Run test with fix context output
        all_passed, fix_ctx = run_skill_test(
            scenario=scenario,
            jira_skills_path=jira_skills_path,
            model=model,
            judge_model=judge_model,
            fix_context=True,
            verbose=verbose,
            conversation=True,
            fail_fast=True,
            checkpoint_file=checkpoint_file,
            fork_from=fork_from,
            prompt_index=prompt_index,
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
        last_failing_prompt_index = failure.get("prompt_index")
        print(f"Failed at prompt {last_failing_prompt_index}: {failure.get('prompt_text', 'unknown')[:60]}...")
        print(f"Quality: {failure.get('quality', 'unknown')}")
        print(f"Refinement suggestion: {failure.get('refinement_suggestion', 'none')[:100]}...")
        print()

        # Run fix agent with session continuity
        print("Running fix agent...")
        if fix_session_id:
            print(f"Continuing fix session: {fix_session_id[:20]}...")
        fix_result = run_fix_agent(
            fix_ctx,
            jira_skills_path,
            verbose=verbose,
            session_id=fix_session_id,
            attempt_history=attempt_history,
        )

        # Update session ID for next iteration
        fix_session_id = fix_result.get("session_id", fix_session_id)

        # Track attempt in history
        attempt_history.append({
            "attempt": attempt,
            "files": fix_result["files_changed"],
            "result": "still failing",
            "error_summary": failure.get('refinement_suggestion', '')[:100],
        })

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
