#!/usr/bin/env python3
"""
Skill Test Runner - Tests Claude Code skills against expected patterns.

Runs prompts through Claude, captures tool usage and response text,
asserts against deterministic patterns, and uses LLM-as-judge for
semantic quality evaluation.

Telemetry:
    - Traces sent to Tempo via OTLP (spans for test runs, prompts, Claude calls)
    - Logs sent to Loki (prompts, responses, tool usage, assertions)
    - Debug mode enabled by default (use --no-debug to disable)

Usage:
    python skill-test.py scenarios/search.prompts
    python skill-test.py scenarios/search.prompts --model sonnet --judge-model haiku
    python skill-test.py scenarios/search.prompts --verbose
    python skill-test.py scenarios/search.prompts --no-debug  # Disable telemetry
    python skill-test.py scenarios/search.prompts --mock      # Use mocked JIRA API

Fast Iteration with Checkpoints:
    # Step 1: Run full scenario to create checkpoints
    python skill-test.py scenarios/issue.prompts --checkpoint-file /tmp/issue.json

    # Step 2: List available checkpoints
    python skill-test.py scenarios/issue.prompts --checkpoint-file /tmp/issue.json --list-checkpoints

    # Step 3: Iterate on prompt 3 by forking from prompt 2's checkpoint
    python skill-test.py scenarios/issue.prompts --checkpoint-file /tmp/issue.json \\
        --prompt-index 3 --fork-from 2

    This skips replaying prompts 0-2, instantly resuming from the saved session state.
"""

import argparse
import atexit
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml  # type: ignore[import-untyped]

# =============================================================================
# Telemetry Setup (imported from shared module)
# =============================================================================

# Add /workspace to path for otel_setup import
sys.path.insert(0, "/workspace")

try:
    from otel_setup import (
        init_telemetry,
        shutdown_telemetry,
        log_to_loki,
        get_tracer,
        OTEL_AVAILABLE,
    )
    if OTEL_AVAILABLE:
        from opentelemetry.trace import Status, StatusCode
except ImportError:
    # Fallback if otel_setup not available
    OTEL_AVAILABLE = False

    def init_telemetry(*args, **kwargs):
        return None

    def shutdown_telemetry():
        pass

    def log_to_loki(*args, **kwargs):
        pass

    def get_tracer():
        return None


def _set_span_attribute(span, key: str, value) -> None:
    """Set a span attribute, converting to string if needed."""
    if value is None or span is None:
        return
    if isinstance(value, (int, float, bool)):
        span.set_attribute(key, value)
    else:
        span.set_attribute(key, str(value))


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[dict] = None,
    record_exception: bool = True,
):
    """Context manager for creating trace spans with timing."""
    start_time = time.time()
    _tracer = get_tracer()

    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                _set_span_attribute(span, key, value)
        try:
            yield span
            if OTEL_AVAILABLE:
                span.set_status(Status(StatusCode.OK))
        except Exception as e:
            if OTEL_AVAILABLE:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                if record_exception:
                    span.record_exception(e)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            span.set_attribute("duration_ms", duration_ms)


# =============================================================================
# Session Checkpoints (with file locking for parallel safety)
# =============================================================================


@contextmanager
def _checkpoint_lock(checkpoint_file: Path, exclusive: bool = False):
    """
    Context manager for checkpoint file locking.

    Uses fcntl.flock for Unix file locking to prevent race conditions
    when multiple parallel processes access the same checkpoint file.

    Args:
        checkpoint_file: Path to the checkpoint file
        exclusive: If True, acquire exclusive (write) lock; otherwise shared (read) lock
    """
    # Use a lock file in /tmp to avoid race condition with directory creation.
    # The lock file name is based on a hash of the checkpoint path to ensure
    # uniqueness while avoiding path characters that are invalid in filenames.
    import hashlib
    lock_name = hashlib.md5(str(checkpoint_file).encode()).hexdigest()[:16]
    lock_file = Path(f"/tmp/checkpoint_{lock_name}.lock")

    lock_fd = None
    try:
        # Open lock file (this always succeeds since /tmp exists)
        lock_fd = open(lock_file, "w")

        # Acquire lock
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_fd.fileno(), lock_type)

        # Now safe to create parent directory (we hold the lock)
        checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

        yield
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass  # Ignore unlock errors during cleanup
            lock_fd.close()


def _cleanup_old_lock_files(max_age_seconds: int = 3600) -> None:
    """
    Clean up old checkpoint lock files from /tmp.

    Lock files older than max_age_seconds are removed. This is safe because
    if a lock file is that old, no active process should be holding it.

    Args:
        max_age_seconds: Maximum age in seconds before a lock file is removed (default: 1 hour)
    """
    import glob
    import os

    lock_pattern = "/tmp/checkpoint_*.lock"
    current_time = time.time()

    for lock_path in glob.glob(lock_pattern):
        try:
            stat = os.stat(lock_path)
            age = current_time - stat.st_mtime
            if age > max_age_seconds:
                os.unlink(lock_path)
        except OSError:
            # File might have been deleted by another process
            pass


def _load_checkpoints_file(checkpoint_file: Path) -> dict:
    """Load checkpoints from file, returning empty dict on error."""
    if not checkpoint_file.exists():
        return {}
    try:
        return json.loads(checkpoint_file.read_text())
    except (json.JSONDecodeError, IOError):
        return {}


def save_checkpoint(checkpoint_file: Path, prompt_index: int, session_id: str) -> None:
    """Save a session checkpoint after a prompt completes (with exclusive lock)."""
    with _checkpoint_lock(checkpoint_file, exclusive=True):
        checkpoints = _load_checkpoints_file(checkpoint_file)
        checkpoints[str(prompt_index)] = session_id
        checkpoint_file.write_text(json.dumps(checkpoints, indent=2))


def load_checkpoint(checkpoint_file: Path, prompt_index: int) -> Optional[str]:
    """Load a session checkpoint for a specific prompt index (with shared lock)."""
    with _checkpoint_lock(checkpoint_file, exclusive=False):
        return _load_checkpoints_file(checkpoint_file).get(str(prompt_index))


def list_checkpoints(checkpoint_file: Path) -> dict[int, str]:
    """List all available checkpoints (with shared lock)."""
    with _checkpoint_lock(checkpoint_file, exclusive=False):
        checkpoints = _load_checkpoints_file(checkpoint_file)
        return {int(k): v for k, v in checkpoints.items()}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ToolExpectations:
    must_call: list[str] = field(default_factory=list)
    must_not_call: list[str] = field(default_factory=list)
    match_mode: str = "all"  # "all" or "any"


@dataclass
class TextExpectations:
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)


@dataclass
class Expectations:
    tools: ToolExpectations = field(default_factory=ToolExpectations)
    text: TextExpectations = field(default_factory=TextExpectations)
    semantic: str = ""
    capture: dict[str, str] = field(default_factory=dict)  # var_name -> regex
    validates: str | None = None  # var_name to interpolate


@dataclass
class PromptSpec:
    prompt: str
    expect: Expectations
    index: int = 0


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: str = ""


@dataclass
class PromptResult:
    spec: PromptSpec
    response_text: str
    tools_called: list[ToolCall]
    exit_code: int
    # Assertion results
    tool_assertions: list[tuple[str, bool, str]]  # (description, passed, detail)
    text_assertions: list[tuple[str, bool, str]]
    # Judge results
    quality: str = ""  # "high", "medium", "low"
    tool_accuracy: str = ""  # "correct", "partial", "wrong"
    reasoning: str = ""
    refinement_suggestion: str = ""
    expectation_suggestion: str = ""
    # Overall
    passed: bool = False


# =============================================================================
# YAML Prompts Parser
# =============================================================================


def parse_prompts_file(filepath: Path) -> list[PromptSpec]:
    """Parse enhanced prompts file with expectations."""
    content = filepath.read_text()

    # Split by --- delimiter (YAML document separator)
    documents = content.split("\n---\n")

    specs: list[PromptSpec] = []
    for i, doc in enumerate(documents):
        doc = doc.strip()
        if not doc or doc == "---":
            continue

        # Handle leading --- for first document
        if doc.startswith("---\n"):
            doc = doc[4:]

        try:
            data = yaml.safe_load(doc)
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse YAML block {i}: {e}")
            continue

        if not data or "prompt" not in data:
            continue

        # Build expectations
        expect_data = data.get("expect", {})
        tools_data = expect_data.get("tools", {})
        text_data = expect_data.get("text", {})

        tool_exp = ToolExpectations(
            must_call=tools_data.get("must_call", []),
            must_not_call=tools_data.get("must_not_call", []),
            match_mode=tools_data.get("match_mode", "all"),
        )

        text_exp = TextExpectations(
            must_contain=text_data.get("must_contain", []),
            must_not_contain=text_data.get("must_not_contain", []),
        )

        expectations = Expectations(
            tools=tool_exp,
            text=text_exp,
            semantic=expect_data.get("semantic", ""),
            capture=expect_data.get("capture", {}),
            validates=expect_data.get("validates"),
        )

        specs.append(PromptSpec(
            prompt=data["prompt"].strip(),
            expect=expectations,
            index=len(specs),
        ))

    return specs


# =============================================================================
# Claude Runner
# =============================================================================


def run_claude_prompt(
    prompt: str,
    model: str = "sonnet",
    verbose: bool = False,
    prompt_index: int = 0,
    continue_conversation: bool = False,
    resume_session_id: str | None = None,
    fork_session: bool = False,
) -> tuple[str, list[ToolCall], int, float, str]:
    """
    Run a prompt through Claude and capture structured output.

    Args:
        continue_conversation: If True, adds --continue flag to preserve context
                              from the previous prompt in this test run.
        resume_session_id: If provided, resume from this session ID.
        fork_session: If True and resume_session_id is provided, fork the session
                     instead of continuing in place.

    Returns: (response_text, tools_called, exit_code, duration_seconds, session_id)
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",  # Required for stream-json with -p
        "--model", model,
        "--dangerously-skip-permissions",
    ]

    if resume_session_id:
        # Use --resume with session ID to restore conversation context
        # --fork-session creates a new session ID instead of reusing the original
        cmd.extend(["--resume", resume_session_id])
        if fork_session:
            cmd.append("--fork-session")
    elif continue_conversation:
        cmd.append("--continue")

    if verbose:
        print(f"  Running: claude -p '...' --model {model}")

    # Log prompt to Loki
    log_to_loki(
        f"Running prompt {prompt_index}",
        level="info",
        labels={"prompt_index": str(prompt_index), "model": model},
        extra={
            "event": "prompt_start",
            "prompt_text": prompt[:1000],
            "model": model,
            "prompt_index": prompt_index,
        },
    )

    start_time = time.time()

    with trace_span(
        "claude.prompt",
        attributes={
            "prompt_index": prompt_index,
            "model": model,
            "prompt_length": len(prompt),
            "prompt_preview": prompt[:100],
        },
    ) as span:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            log_to_loki(
                f"Prompt {prompt_index} timed out after {duration:.1f}s",
                level="error",
                labels={"prompt_index": str(prompt_index)},
                extra={"event": "prompt_timeout", "duration_seconds": duration},
            )
            if span:
                span.set_attribute("error", "timeout")
            return "", [], 1, duration, ""
        except Exception as e:
            duration = time.time() - start_time
            log_to_loki(
                f"Prompt {prompt_index} failed: {e}",
                level="error",
                labels={"prompt_index": str(prompt_index)},
                extra={"event": "prompt_error", "error": str(e)},
            )
            print(f"  Error running Claude: {e}")
            if span:
                span.set_attribute("error", str(e))
            return "", [], 1, duration, ""

        duration = time.time() - start_time

        # Parse Claude Code's stream-json output format
        response_text = ""
        tools_called = []
        token_count = 0
        cost_usd = 0.0
        session_id = ""

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            # Handle assistant message with content blocks
            if event_type == "assistant":
                message = event.get("message", {})
                content_blocks = message.get("content", [])

                for block in content_blocks:
                    block_type = block.get("type", "")

                    if block_type == "text":
                        response_text += block.get("text", "")

                    elif block_type == "tool_use":
                        tool = ToolCall(
                            name=block.get("name", ""),
                            input=block.get("input", {}),
                        )
                        tools_called.append(tool)

                        # Log each tool use
                        log_to_loki(
                            f"Tool called: {tool.name}",
                            level="debug",
                            labels={"prompt_index": str(prompt_index), "tool": tool.name},
                            extra={
                                "event": "tool_use",
                                "tool_name": tool.name,
                                "tool_input": json.dumps(tool.input)[:500],
                            },
                        )

            # Handle tool result (when Claude runs tools)
            elif event_type == "tool_result":
                tool_result = event.get("tool_result", {})
                if tools_called and tool_result:
                    tools_called[-1].output = str(tool_result.get("content", ""))[:500]

                    # Log tool result
                    log_to_loki(
                        f"Tool result for {tools_called[-1].name}",
                        level="debug",
                        labels={"prompt_index": str(prompt_index), "tool": tools_called[-1].name},
                        extra={
                            "event": "tool_result",
                            "tool_name": tools_called[-1].name,
                            "result_preview": tools_called[-1].output[:200],
                        },
                    )

            # Final result - capture metrics and session_id
            elif event_type == "result":
                if not response_text:
                    response_text = event.get("result", "")
                cost_usd = event.get("cost_usd", 0.0)
                session_id = event.get("session_id", "")
                # Token counts if available
                usage = event.get("usage", {})
                token_count = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # Add span attributes for analysis
        if span:
            span.set_attribute("response_length", len(response_text))
            span.set_attribute("tools_count", len(tools_called))
            span.set_attribute("tools_called", ",".join(t.name for t in tools_called))
            span.set_attribute("exit_code", result.returncode)
            span.set_attribute("cost_usd", cost_usd)
            span.set_attribute("token_count", token_count)
            span.set_attribute("duration_seconds", duration)

        # Log completion with full prompt and response for debugging
        log_to_loki(
            f"Prompt {prompt_index} completed in {duration:.1f}s",
            level="info",
            labels={"prompt_index": str(prompt_index)},
            extra={
                "event": "prompt_complete",
                "duration_seconds": duration,
                "response_length": len(response_text),
                "tools_count": len(tools_called),
                "tools_called": [t.name for t in tools_called],
                "exit_code": result.returncode,
                "cost_usd": cost_usd,
                "prompt": prompt[:5000],
                "response": response_text[:5000],
                "session_id": session_id,
            },
        )

        return response_text, tools_called, result.returncode, duration, session_id


# =============================================================================
# Assertions
# =============================================================================


def run_tool_assertions(
    tools_called: list[ToolCall],
    expectations: ToolExpectations,
) -> list[tuple[str, bool, str]]:
    """Run deterministic tool assertions."""
    results = []
    called_names = [t.name for t in tools_called]

    # Check must_call
    if expectations.match_mode == "all":
        for tool in expectations.must_call:
            passed = tool in called_names
            results.append((
                f"must_call: {tool}",
                passed,
                f"called: {called_names}" if not passed else "",
            ))
    elif expectations.match_mode == "any":
        if expectations.must_call:
            any_called = any(t in called_names for t in expectations.must_call)
            results.append((
                f"must_call (any): {expectations.must_call}",
                any_called,
                f"called: {called_names}" if not any_called else "",
            ))

    # Check must_not_call
    for tool in expectations.must_not_call:
        passed = tool not in called_names
        results.append((
            f"must_not_call: {tool}",
            passed,
            "but was called" if not passed else "",
        ))

    return results


def run_text_assertions(
    response_text: str,
    expectations: TextExpectations,
) -> list[tuple[str, bool, str]]:
    """Run deterministic text assertions."""
    results = []
    text_lower = response_text.lower()

    for pattern in expectations.must_contain:
        # Case-insensitive search (convert to str for YAML int patterns like "30")
        pattern = str(pattern)
        passed = pattern.lower() in text_lower
        results.append((
            f"must_contain: '{pattern}'",
            passed,
            "" if passed else "not found in response",
        ))

    for pattern in expectations.must_not_contain:
        pattern = str(pattern)
        passed = pattern.lower() not in text_lower
        results.append((
            f"must_not_contain: '{pattern}'",
            passed,
            "found in response" if not passed else "",
        ))

    return results


def capture_values(
    response_text: str,
    capture_specs: dict[str, str],
) -> dict[str, str]:
    """Capture values from response using regex patterns."""
    captured = {}
    for var_name, pattern in capture_specs.items():
        match = re.search(pattern, response_text)
        if match:
            captured[var_name] = match.group(0)
    return captured


def interpolate_prompt(prompt: str, variables: dict[str, str]) -> str:
    """Interpolate {VAR_NAME} placeholders in prompt."""
    result = prompt
    for var_name, value in variables.items():
        result = result.replace(f"{{{var_name}}}", value)
    return result


# =============================================================================
# LLM-as-Judge
# =============================================================================


JUDGE_PROMPT_TEMPLATE = """You are evaluating Claude's response quality for a JIRA automation skill test.

## How Claude Code Skills Work (CRITICAL CONTEXT)

Claude Code skills are CONTEXT-LOADING mechanisms, NOT direct executors:
1. **Skill tool** loads SKILL.md content into Claude's context (instructions, examples, CLI commands)
2. **Bash tool** executes the `jira` CLI commands described in the skill

The pattern `['Skill', 'Bash']` is CORRECT and EXPECTED for any JIRA operation:
- First operation in conversation: `['Skill', 'Bash']` - Skill loads context, Bash runs CLI
- Subsequent operations: `['Bash']` only - context already loaded
- Knowledge-only question: `['Skill']` only - no CLI execution needed

DO NOT penalize for using Bash after Skill - this is the intended design pattern.

## Expected Behavior
{semantic}

## Tool Usage
Expected to call: {must_call}
Expected NOT to call: {must_not_call}
Actually called: {tools_called}

**Tool evaluation guidance:**
- `['Skill', 'Bash']` when Skill is expected = CORRECT (Bash executes the CLI)
- `['Skill']` only when CLI execution expected = PARTIAL (missing execution)
- `['Bash']` without `['Skill']` on first call = PARTIAL (should load skill first)
- Multiple `['Skill']` calls in sequence = PARTIAL (skill should only load once)

## Actual Response
{response_text}

## Text Pattern Results
Must contain (results): {must_contain_results}
Must not contain (results): {must_not_contain_results}

---

Evaluate the response and provide:

1. **quality**: Rate overall quality
   - "high": Correct tools (Skill→Bash pattern), accurate information, clear formatting, meets semantic expectations
   - "medium": Mostly correct but minor issues (extra unnecessary tools, verbose, slight formatting issues)
   - "low": Wrong tools, missing information, errors, hallucinations, or doesn't meet expectations

2. **tool_accuracy**: Rate tool usage
   - "correct": Used exactly the right tools (Skill→Bash for first CLI operation is correct)
   - "partial": Used some right tools but also wrong ones, or missed some
   - "wrong": Used completely wrong tools

3. **reasoning**: Brief explanation of your rating

4. **refinement_suggestion**: If quality < high, suggest how to improve the SKILL (not the prompt) to get better results. Focus on skill descriptions, CLI command examples, or missing capabilities. Do NOT suggest removing Bash usage - that's the expected pattern.

5. **expectation_suggestion**: If the expectations themselves seem wrong or too strict/lenient, suggest how to adjust them.

Respond in JSON only:
{{
  "quality": "high|medium|low",
  "tool_accuracy": "correct|partial|wrong",
  "reasoning": "...",
  "refinement_suggestion": "...",
  "expectation_suggestion": "..."
}}"""


def _extract_json_from_output(output: str) -> str:
    """Extract JSON object from output, handling markdown code blocks."""
    # Handle markdown code blocks
    if "```json" in output:
        output = output.split("```json")[1].split("```")[0].strip()
    elif "```" in output:
        output = output.split("```")[1].split("```")[0].strip()

    # Find JSON object boundaries
    json_start = output.find("{")
    json_end = output.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        return output[json_start:json_end]
    return output


def run_llm_judge(
    result: PromptResult,
    model: str = "haiku",
    verbose: bool = False,
) -> dict[str, str]:
    """Run LLM-as-judge to evaluate response quality."""

    # Build context for judge
    must_call = result.spec.expect.tools.must_call or ["(none specified)"]
    must_not_call = result.spec.expect.tools.must_not_call or ["(none specified)"]
    tools_called = [t.name for t in result.tools_called] or ["(none)"]

    must_contain_results = [
        f"'{a[0].split(': ')[1]}': {'PASS' if a[1] else 'FAIL'}"
        for a in result.text_assertions
        if "must_contain:" in a[0]
    ]

    must_not_contain_results = [
        f"'{a[0].split(': ')[1]}': {'PASS' if a[1] else 'FAIL'}"
        for a in result.text_assertions
        if "must_not_contain:" in a[0]
    ]

    prompt = JUDGE_PROMPT_TEMPLATE.format(
        semantic=result.spec.expect.semantic or "(no semantic expectation specified)",
        must_call=must_call,
        must_not_call=must_not_call,
        tools_called=tools_called,
        response_text=result.response_text[:3000],  # Truncate for context
        must_contain_results=must_contain_results or ["(none)"],
        must_not_contain_results=must_not_contain_results or ["(none)"],
    )

    if verbose:
        print(f"  Running judge with model: {model}")

    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--output-format", "text",  # Use text format for simpler parsing
        "--dangerously-skip-permissions",
    ]

    start_time = time.time()

    with trace_span(
        "llm.judge",
        attributes={
            "prompt_index": result.spec.index,
            "model": model,
            "tools_called": ",".join(tools_called),
        },
    ) as span:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except Exception as e:
            duration = time.time() - start_time
            log_to_loki(
                f"Judge failed for prompt {result.spec.index}: {e}",
                level="error",
                labels={"prompt_index": str(result.spec.index)},
                extra={"event": "judge_error", "error": str(e)},
            )
            if span:
                span.set_attribute("error", str(e))
            return {
                "quality": "unknown",
                "tool_accuracy": "unknown",
                "reasoning": f"Judge failed: {e}",
                "refinement_suggestion": "",
                "expectation_suggestion": "",
            }

        duration = time.time() - start_time

        # Parse JSON response from text output
        try:
            output = proc.stdout.strip()
            json_text = _extract_json_from_output(output)
            judge_result = json.loads(json_text)
            parsed_result = {
                "quality": judge_result.get("quality", "unknown"),
                "tool_accuracy": judge_result.get("tool_accuracy", "unknown"),
                "reasoning": judge_result.get("reasoning", ""),
                "refinement_suggestion": judge_result.get("refinement_suggestion", ""),
                "expectation_suggestion": judge_result.get("expectation_suggestion", ""),
            }

            # Add span attributes
            if span:
                span.set_attribute("quality", parsed_result["quality"])
                span.set_attribute("tool_accuracy", parsed_result["tool_accuracy"])
                span.set_attribute("duration_seconds", duration)

            # Log judge result with full suggestions
            log_to_loki(
                f"Judge completed for prompt {result.spec.index}: quality={parsed_result['quality']}",
                level="info",
                labels={
                    "prompt_index": str(result.spec.index),
                    "quality": parsed_result["quality"],
                },
                extra={
                    "event": "judge_complete",
                    "duration_seconds": duration,
                    "quality": parsed_result["quality"],
                    "tool_accuracy": parsed_result["tool_accuracy"],
                    "reasoning": parsed_result["reasoning"],
                    "refinement_suggestion": parsed_result["refinement_suggestion"],
                    "expectation_suggestion": parsed_result["expectation_suggestion"],
                },
            )

            return parsed_result
        except (json.JSONDecodeError, IndexError) as e:
            if span:
                span.set_attribute("error", f"parse_failed: {e}")

            log_to_loki(
                f"Judge parse failed for prompt {result.spec.index}",
                level="error",
                labels={"prompt_index": str(result.spec.index)},
                extra={
                    "event": "judge_parse_error",
                    "error": str(e),
                    "raw_output": proc.stdout[:500],
                },
            )

            return {
                "quality": "unknown",
                "tool_accuracy": "unknown",
                "reasoning": f"Failed to parse judge response: {str(e)[:100]} - Output: {proc.stdout[:300]}",
                "refinement_suggestion": "",
                "expectation_suggestion": "",
            }


# =============================================================================
# Report Generation
# =============================================================================


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def for_quality(cls, quality: str) -> str:
        """Return color code for quality level."""
        quality_colors = {"high": cls.GREEN, "medium": cls.YELLOW, "low": cls.RED}
        return quality_colors.get(quality, cls.DIM)


def print_report(results: list[PromptResult], scenario_name: str) -> None:
    """Print formatted test report."""
    c = Colors

    print()
    print(f"{c.BOLD}{'=' * 70}{c.RESET}")
    print(f"{c.BOLD} SKILL TEST REPORT: {scenario_name}{c.RESET}")
    print(f"{c.BOLD}{'=' * 70}{c.RESET}")
    print()

    for result in results:
        status_icon = f"{c.GREEN}PASS{c.RESET}" if result.passed else f"{c.RED}FAIL{c.RESET}"
        print(f"{c.BOLD}Prompt {result.spec.index + 1}/{len(results)}: {result.spec.prompt[:60]}...{c.RESET}")

        # Tool assertions
        for desc, passed, detail in result.tool_assertions:
            icon = f"{c.GREEN}✓{c.RESET}" if passed else f"{c.RED}✗{c.RESET}"
            detail_str = f" {c.DIM}({detail}){c.RESET}" if detail else ""
            print(f"  {icon} Tool: {desc}{detail_str}")

        # Text assertions
        for desc, passed, detail in result.text_assertions:
            icon = f"{c.GREEN}✓{c.RESET}" if passed else f"{c.RED}✗{c.RESET}"
            detail_str = f" {c.DIM}({detail}){c.RESET}" if detail else ""
            print(f"  {icon} Text: {desc}{detail_str}")

        # Quality
        quality_color = c.for_quality(result.quality)
        print(f"  {c.BLUE}Quality:{c.RESET} {quality_color}{result.quality.upper()}{c.RESET}")

        # Reasoning
        if result.reasoning:
            print(f"  {c.DIM}Reasoning: {result.reasoning[:100]}...{c.RESET}")

        # Suggestions
        if result.refinement_suggestion and result.quality != "high":
            print(f"  {c.YELLOW}Skill Refinement:{c.RESET} {result.refinement_suggestion}")

        if result.expectation_suggestion:
            print(f"  {c.BLUE}Expectation Adjustment:{c.RESET} {result.expectation_suggestion}")

        print(f"  {c.BOLD}Status:{c.RESET} {status_icon}")
        print()

    # Summary
    print(f"{c.BOLD}{'=' * 70}{c.RESET}")
    print(f"{c.BOLD} SUMMARY{c.RESET}")
    print(f"{c.BOLD}{'=' * 70}{c.RESET}")

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = (passed_count / total * 100) if total > 0 else 0

    tool_correct = sum(1 for r in results if r.tool_accuracy == "correct")
    tool_rate = (tool_correct / total * 100) if total > 0 else 0

    print(f" Passed: {passed_count}/{total} ({pass_rate:.0f}%)")
    print(f" Tool Accuracy: {tool_correct}/{total} ({tool_rate:.0f}%)")
    print()

    # Quality distribution
    quality_counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for r in results:
        quality_counts[r.quality] = quality_counts.get(r.quality, 0) + 1

    print(" Quality Distribution:")
    print(f"   {c.GREEN}HIGH:{c.RESET}    {quality_counts['high']}")
    print(f"   {c.YELLOW}MEDIUM:{c.RESET}  {quality_counts['medium']}")
    print(f"   {c.RED}LOW:{c.RESET}     {quality_counts['low']}")
    if quality_counts["unknown"]:
        print(f"   {c.DIM}UNKNOWN:{c.RESET} {quality_counts['unknown']}")
    print()

    # Collect refinement suggestions
    refinements = [r.refinement_suggestion for r in results if r.refinement_suggestion and r.quality != "high"]
    if refinements:
        print(f" {c.BOLD}Top Refinement Priorities:{c.RESET}")
        for i, suggestion in enumerate(refinements[:5], 1):
            print(f"   {i}. {suggestion[:80]}...")
        print()

    # Collect expectation suggestions
    exp_suggestions = [r.expectation_suggestion for r in results if r.expectation_suggestion]
    if exp_suggestions:
        print(f" {c.BOLD}Expectation Adjustments:{c.RESET}")
        for i, suggestion in enumerate(exp_suggestions[:3], 1):
            print(f"   {i}. {suggestion[:80]}...")
        print()

    print(f"{c.BOLD}{'=' * 70}{c.RESET}")


def generate_json_report(results: list[PromptResult], scenario_name: str) -> dict:
    """Generate JSON report for programmatic consumption."""
    return {
        "scenario": scenario_name,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "tool_accuracy_correct": sum(1 for r in results if r.tool_accuracy == "correct"),
            "quality_distribution": {
                "high": sum(1 for r in results if r.quality == "high"),
                "medium": sum(1 for r in results if r.quality == "medium"),
                "low": sum(1 for r in results if r.quality == "low"),
            },
        },
        "results": [
            {
                "prompt_index": r.spec.index,
                "prompt": r.spec.prompt,
                "passed": r.passed,
                "exit_code": r.exit_code,
                "tools_called": [{"name": t.name, "input": t.input} for t in r.tools_called],
                "tool_assertions": [{"desc": a[0], "passed": a[1], "detail": a[2]} for a in r.tool_assertions],
                "text_assertions": [{"desc": a[0], "passed": a[1], "detail": a[2]} for a in r.text_assertions],
                "quality": r.quality,
                "tool_accuracy": r.tool_accuracy,
                "reasoning": r.reasoning,
                "refinement_suggestion": r.refinement_suggestion,
                "expectation_suggestion": r.expectation_suggestion,
            }
            for r in results
        ],
    }


def generate_fix_context(result: PromptResult, skills_path: str) -> dict[str, Any]:
    """Generate fix context for the skill-fix agent."""
    import subprocess

    # Validate skills_path to prevent path traversal
    skills_path_obj = Path(skills_path).resolve()
    if not skills_path_obj.is_absolute():
        raise ValueError(f"skills_path must be absolute: {skills_path}")
    if not skills_path_obj.exists():
        raise ValueError(f"skills_path does not exist: {skills_path}")

    context: dict[str, Any] = {
        "failure": {
            "prompt_index": result.spec.index,
            "prompt_text": result.spec.prompt,
            "response_text": result.response_text[:5000],  # Truncate for context
            "tools_called": [t.name for t in result.tools_called],
            "tool_assertions": [
                {"desc": a[0], "passed": a[1], "detail": a[2]}
                for a in result.tool_assertions
            ],
            "text_assertions": [
                {"desc": a[0], "passed": a[1], "detail": a[2]}
                for a in result.text_assertions
            ],
            "quality": result.quality,
            "tool_accuracy": result.tool_accuracy,
            "reasoning": result.reasoning,
            "refinement_suggestion": result.refinement_suggestion,
            "expectation_suggestion": result.expectation_suggestion,
        },
        "relevant_files": {},
        "git_history": [],
    }

    # Find relevant skill files based on the prompt
    # Try both possible locations for the plugin
    plugin_path = skills_path_obj / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = skills_path_obj / "jira-assistant-skills"
    skills_dir = plugin_path / "skills"

    if skills_dir.exists():
        # Look for skill files that might be relevant
        # For JIRA queries, likely jira-search or jira-assistant
        relevant_skills = []
        prompt_lower = result.spec.prompt.lower()

        skill_keywords = {
            "jira-search.md": ["search", "find", "query", "jql", "issues"],
            "jira-issue.md": ["create", "update", "issue", "bug", "story", "task"],
            "jira-assistant.md": ["jira", "assistant"],
            "jira-agile.md": ["sprint", "epic", "backlog", "story points"],
            "jira-lifecycle.md": ["transition", "status", "workflow"],
        }

        for skill_file, keywords in skill_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                skill_path = skills_dir / skill_file
                if skill_path.exists():
                    relevant_skills.append(skill_file)

        # Read relevant skill files
        for skill_file in relevant_skills[:3]:  # Limit to 3 most relevant
            skill_path = skills_dir / skill_file
            try:
                content = skill_path.read_text()
                context["relevant_files"][f"skills/{skill_file}"] = content[:10000]
            except Exception:
                pass

    # Get recent git history for the skills repo
    try:
        git_log = subprocess.run(
            ["git", "log", "--oneline", "-10", "--", "jira-assistant-skills/skills/"],
            cwd=skills_path_obj,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if git_log.returncode == 0:
            for line in git_log.stdout.strip().split("\n")[:5]:
                if line:
                    parts = line.split(" ", 1)
                    context["git_history"].append({
                        "commit": parts[0],
                        "message": parts[1] if len(parts) > 1 else "",
                    })
    except Exception:
        pass

    # Check if library code might be relevant (API errors, etc.)
    if "error" in result.response_text.lower() or result.quality == "low":
        lib_path = skills_path_obj / "jira-as" / "src" / "jira_as"
        if lib_path.exists():
            # Add search.py if relevant to search failures
            search_path = lib_path / "search.py"
            if search_path.exists() and "search" in prompt_lower:
                try:
                    context["relevant_files"]["lib/search.py"] = search_path.read_text()[:8000]
                except Exception:
                    pass

    return context


# =============================================================================
# Main Runner
# =============================================================================


def run_skill_test(
    prompts_file: Path,
    model: str = "sonnet",
    judge_model: str = "haiku",
    verbose: bool = False,
    json_output: bool = False,
    prompt_index: int | None = None,
    fix_context_mode: bool = False,
    conversation_mode: bool = False,
    fail_fast: bool = False,
    checkpoint_file: Path | None = None,
    fork_from: int | None = None,
) -> list[PromptResult]:
    """Run skill test for a scenario.

    Args:
        fix_context_mode: When True, all progress output goes to stderr to keep
                         stdout clean for JSON output.
        conversation_mode: When True, prompts after the first one use --continue
                          to preserve conversation context.
        fail_fast: When True, stop on first failing prompt.
        checkpoint_file: Path to JSON file for storing session checkpoints.
        fork_from: Fork from checkpoint at this prompt index instead of replaying.
    """
    # Output destination - use stderr in fix_context_mode to keep stdout clean for JSON
    out = sys.stderr if fix_context_mode else sys.stdout
    scenario_name = prompts_file.stem
    test_start_time = time.time()

    # Parse prompts file
    specs = parse_prompts_file(prompts_file)
    if not specs:
        print(f"Error: No prompts found in {prompts_file}", file=out)
        return []

    # Filter to single prompt if specified
    if prompt_index is not None:
        if prompt_index < 0 or prompt_index >= len(specs):
            print(f"Error: prompt_index {prompt_index} out of range (0-{len(specs)-1})", file=out)
            return []
        specs = [specs[prompt_index]]
        print(f"Running prompt {prompt_index} from {prompts_file.name}", file=out)
    else:
        print(f"Running {len(specs)} prompts from {prompts_file.name}", file=out)

    print(f"Model: {model}, Judge: {judge_model}", file=out)
    print(file=out)

    # Log test start
    log_to_loki(
        f"Starting skill test: {scenario_name}",
        level="info",
        extra={
            "event": "test_start",
            "scenario": scenario_name,
            "prompt_count": len(specs),
            "model": model,
            "judge_model": judge_model,
        },
    )

    results: list[PromptResult] = []
    captured_values: dict[str, str] = {}
    total_duration = 0.0

    # Load checkpoint for forking if specified
    resume_session_id = None
    fork_session = False
    if fork_from is not None and checkpoint_file:
        resume_session_id = load_checkpoint(checkpoint_file, fork_from)
        if resume_session_id:
            fork_session = True
            print(f"Forking from prompt {fork_from} checkpoint: {resume_session_id[:8]}...", file=out)
        else:
            print(f"Warning: No checkpoint found for prompt {fork_from}", file=out)

    with trace_span(
        "skill_test.run",
        attributes={
            "scenario": scenario_name,
            "prompt_count": len(specs),
            "model": model,
            "judge_model": judge_model,
        },
    ) as test_span:
        for spec in specs:
            print(f"[{spec.index + 1}/{len(specs)}] {spec.prompt[:50]}...", file=out)

            # Interpolate captured values if needed
            prompt = spec.prompt
            if spec.expect.validates and spec.expect.validates in captured_values:
                prompt = interpolate_prompt(prompt, captured_values)
                if verbose:
                    print(f"  Interpolated: {prompt[:50]}...", file=out)

            # Run Claude (now returns 5 values including duration and session_id)
            # In conversation mode, use --continue for prompts after the first
            use_continue = conversation_mode and spec.index > 0
            with trace_span(
                "skill_test.prompt",
                attributes={
                    "prompt_index": spec.index,
                    "prompt_preview": spec.prompt[:100],
                    "continue_conversation": use_continue,
                },
            ) as prompt_span:
                response_text, tools_called, exit_code, prompt_duration, session_id = run_claude_prompt(
                    prompt, model=model, verbose=verbose, prompt_index=spec.index,
                    continue_conversation=use_continue,
                    resume_session_id=resume_session_id,
                    fork_session=fork_session,
                )
                total_duration += prompt_duration

                # Save checkpoint after each prompt
                if checkpoint_file and session_id:
                    save_checkpoint(checkpoint_file, spec.index, session_id)
                    if verbose:
                        print(f"  Session checkpoint saved: {session_id[:8]}...", file=out)

                # Clear resume for subsequent prompts (only fork first one)
                resume_session_id = None
                fork_session = False

                if verbose:
                    print(f"  Response length: {len(response_text)} chars", file=out)
                    print(f"  Tools called: {[t.name for t in tools_called]}", file=out)

                # Capture values for later prompts
                if spec.expect.capture:
                    new_captures = capture_values(response_text, spec.expect.capture)
                    captured_values.update(new_captures)
                    if verbose and new_captures:
                        print(f"  Captured: {new_captures}", file=out)

                # Run assertions
                tool_assertions = run_tool_assertions(tools_called, spec.expect.tools)
                text_assertions = run_text_assertions(response_text, spec.expect.text)

                # Log assertion results
                failed_tool_assertions = [a for a in tool_assertions if not a[1]]
                failed_text_assertions = [a for a in text_assertions if not a[1]]

                if failed_tool_assertions or failed_text_assertions:
                    log_to_loki(
                        f"Assertions failed for prompt {spec.index}",
                        level="warning",
                        labels={"prompt_index": str(spec.index)},
                        extra={
                            "event": "assertion_failure",
                            "failed_tool_assertions": [
                                {"desc": a[0], "detail": a[2]} for a in failed_tool_assertions
                            ],
                            "failed_text_assertions": [
                                {"desc": a[0], "detail": a[2]} for a in failed_text_assertions
                            ],
                        },
                    )

                # Build result
                result = PromptResult(
                    spec=spec,
                    response_text=response_text,
                    tools_called=tools_called,
                    exit_code=exit_code,
                    tool_assertions=tool_assertions,
                    text_assertions=text_assertions,
                )

                # Determine if passed (all assertions must pass)
                all_tool_passed = all(a[1] for a in tool_assertions)
                all_text_passed = all(a[1] for a in text_assertions)

                # Run LLM judge
                judge_result = run_llm_judge(result, model=judge_model, verbose=verbose)
                result.quality = judge_result["quality"]
                result.tool_accuracy = judge_result["tool_accuracy"]
                result.reasoning = judge_result["reasoning"]
                result.refinement_suggestion = judge_result["refinement_suggestion"]
                result.expectation_suggestion = judge_result["expectation_suggestion"]

                # Overall pass: assertions pass AND quality is not low
                result.passed = all_tool_passed and all_text_passed and result.quality != "low"

                # Log comprehensive failure_detail event for failed prompts
                if not result.passed:
                    log_to_loki(
                        f"Prompt {spec.index} failed",
                        level="warning",
                        labels={
                            "prompt_index": str(spec.index),
                            "quality": result.quality,
                            "status": "fail",
                        },
                        extra={
                            "event": "failure_detail",
                            "prompt": prompt[:5000],
                            "response": response_text[:5000],
                            "tools_called": [t.name for t in tools_called],
                            "tool_assertions": [
                                {"desc": a[0], "passed": a[1], "detail": a[2]}
                                for a in tool_assertions
                            ],
                            "text_assertions": [
                                {"desc": a[0], "passed": a[1], "detail": a[2]}
                                for a in text_assertions
                            ],
                            "quality": result.quality,
                            "tool_accuracy": result.tool_accuracy,
                            "reasoning": result.reasoning,
                            "refinement_suggestion": result.refinement_suggestion,
                            "expectation_suggestion": result.expectation_suggestion,
                        },
                    )

                # Update prompt span with results
                if prompt_span:
                    prompt_span.set_attribute("passed", result.passed)
                    prompt_span.set_attribute("quality", result.quality)
                    prompt_span.set_attribute("tool_accuracy", result.tool_accuracy)
                    prompt_span.set_attribute("tools_called", ",".join(t.name for t in tools_called))

                results.append(result)
                print(f"  -> {'PASS' if result.passed else 'FAIL'} (quality: {result.quality})", file=out)

                # Stop on first failure if fail_fast is enabled
                if fail_fast and not result.passed:
                    print("  Stopping early (--fail-fast enabled)", file=out)
                    break

        # Calculate summary stats
        test_duration = time.time() - test_start_time
        passed_count = sum(1 for r in results if r.passed)
        quality_high = sum(1 for r in results if r.quality == "high")
        quality_medium = sum(1 for r in results if r.quality == "medium")
        quality_low = sum(1 for r in results if r.quality == "low")

        # Update test span with summary
        if test_span:
            test_span.set_attribute("passed_count", passed_count)
            test_span.set_attribute("failed_count", len(results) - passed_count)
            test_span.set_attribute("pass_rate", passed_count / len(results) if results else 0)
            test_span.set_attribute("quality_high", quality_high)
            test_span.set_attribute("quality_medium", quality_medium)
            test_span.set_attribute("quality_low", quality_low)
            test_span.set_attribute("total_duration_seconds", test_duration)
            test_span.set_attribute("claude_duration_seconds", total_duration)

        # Log test completion
        log_to_loki(
            f"Skill test completed: {scenario_name} - {passed_count}/{len(results)} passed",
            level="info" if passed_count == len(results) else "warning",
            extra={
                "event": "test_complete",
                "scenario": scenario_name,
                "passed_count": passed_count,
                "failed_count": len(results) - passed_count,
                "pass_rate": passed_count / len(results) if results else 0,
                "quality_high": quality_high,
                "quality_medium": quality_medium,
                "quality_low": quality_low,
                "total_duration_seconds": test_duration,
                "claude_duration_seconds": total_duration,
            },
        )

    # Clean up old lock files from previous test runs
    _cleanup_old_lock_files()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Skill Test Runner - Test Claude Code skills against expectations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python skill-test.py scenarios/search.prompts
    python skill-test.py scenarios/search.prompts --model opus --judge-model sonnet
    python skill-test.py scenarios/search.prompts --verbose --json
    python skill-test.py scenarios/search.prompts --prompt-index 0  # Single prompt
    python skill-test.py scenarios/search.prompts --fix-context /path/to/skills
    python skill-test.py scenarios/search.prompts --no-debug  # Disable telemetry

Telemetry (enabled by default):
    - Traces: Sent to Tempo via OTLP (http://localhost:4318 or OTEL_EXPORTER_OTLP_ENDPOINT)
    - Logs: Sent to Loki (http://localhost:3100 or LOKI_ENDPOINT)
    - Spans: skill_test.run, skill_test.prompt, claude.prompt, llm.judge
        """,
    )
    parser.add_argument("prompts_file", type=Path, help="Path to .prompts file with expectations")
    parser.add_argument("--model", default="sonnet", help="Model for running prompts (default: sonnet)")
    parser.add_argument("--judge-model", default="haiku", help="Model for LLM judge (default: haiku)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--prompt-index", type=int, help="Run only a specific prompt by index (0-based)")
    parser.add_argument("--fix-context", type=str, metavar="SKILLS_PATH",
                        help="Output fix context JSON for first failure (requires path to Jira-Assistant-Skills)")
    parser.add_argument("--no-debug", action="store_true",
                        help="Disable telemetry (traces and logs) - telemetry is ON by default")
    parser.add_argument("--conversation", action="store_true",
                        help="Enable conversation mode - prompts after the first use --continue to preserve context")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Stop on first failing prompt (useful with --conversation to avoid wasted API calls)")
    parser.add_argument("--mock", action="store_true",
                        help="Enable JIRA API mocking for faster, deterministic tests")
    parser.add_argument("--checkpoint-file", type=Path, metavar="FILE",
                        help="Path to JSON file for session checkpoints (enables fast iteration)")
    parser.add_argument("--fork-from", type=int, metavar="N",
                        help="Fork from checkpoint after prompt N (use with --prompt-index and --checkpoint-file)")
    parser.add_argument("--list-checkpoints", action="store_true",
                        help="List available checkpoints and exit (use with --checkpoint-file)")
    args = parser.parse_args()

    # Set mock mode environment variable if requested
    if args.mock:
        os.environ["JIRA_MOCK_MODE"] = "true"

    # Auto-select mock prompts file if in mock mode and -mock variant exists
    if args.mock or os.environ.get("JIRA_MOCK_MODE", "").lower() == "true":
        mock_prompts_file = args.prompts_file.with_name(
            args.prompts_file.stem + "-mock" + args.prompts_file.suffix
        )
        if mock_prompts_file.exists():
            print(f"Mock mode: using {mock_prompts_file.name} instead of {args.prompts_file.name}")
            args.prompts_file = mock_prompts_file

    if not args.prompts_file.exists():
        print(f"Error: File not found: {args.prompts_file}")
        sys.exit(1)

    # Handle --list-checkpoints
    if args.list_checkpoints:
        if not args.checkpoint_file:
            print("Error: --list-checkpoints requires --checkpoint-file")
            sys.exit(1)
        checkpoints = list_checkpoints(args.checkpoint_file)
        if not checkpoints:
            print(f"No checkpoints found in {args.checkpoint_file}")
        else:
            print(f"Checkpoints in {args.checkpoint_file}:")
            for idx, session_id in sorted(checkpoints.items()):
                print(f"  Prompt {idx}: {session_id[:16]}...")
        sys.exit(0)

    # Validate fork-from usage
    if args.fork_from is not None:
        if not args.checkpoint_file:
            print("Error: --fork-from requires --checkpoint-file")
            sys.exit(1)
        if args.prompt_index is None:
            print("Error: --fork-from requires --prompt-index to specify which prompt to run")
            sys.exit(1)
        if args.fork_from >= args.prompt_index:
            print(f"Error: --fork-from ({args.fork_from}) must be less than --prompt-index ({args.prompt_index})")
            sys.exit(1)

    scenario_name = args.prompts_file.stem

    # Initialize telemetry (enabled by default)
    init_telemetry(
        service_name="skill-test",
        scenario=scenario_name,
        debug=not args.no_debug,
    )
    # Register shutdown to ensure telemetry flushes on any exit path
    atexit.register(shutdown_telemetry)

    results = run_skill_test(
        prompts_file=args.prompts_file,
        model=args.model,
        judge_model=args.judge_model,
        verbose=args.verbose,
        json_output=args.json,
        prompt_index=args.prompt_index,
        fix_context_mode=bool(args.fix_context),
        conversation_mode=args.conversation,
        fail_fast=args.fail_fast,
        checkpoint_file=args.checkpoint_file,
        fork_from=args.fork_from,
    )

    if not results:
        sys.exit(1)

    # Output fix context for first failure if requested
    if args.fix_context:
        failed_results = [r for r in results if not r.passed]
        if failed_results:
            fix_ctx = generate_fix_context(failed_results[0], args.fix_context)
            print(json.dumps(fix_ctx, indent=2))
            sys.exit(1)
        else:
            print(json.dumps({"status": "all_passed", "message": "No failures to fix"}))
            sys.exit(0)

    if args.json:
        report = generate_json_report(results, scenario_name)
        print(json.dumps(report, indent=2))
    else:
        print_report(results, scenario_name)

    # Shutdown telemetry (flushes pending spans)
    shutdown_telemetry()

    # Exit with failure if any tests failed
    if not all(r.passed for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
