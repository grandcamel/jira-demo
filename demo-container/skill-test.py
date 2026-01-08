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
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

# =============================================================================
# Telemetry Setup
# =============================================================================

# OpenTelemetry imports - optional dependency
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

# Module-level tracer and config
_tracer: Optional[Any] = None
_loki_endpoint: Optional[str] = None
_debug_enabled: bool = True
_scenario_name: str = "unknown"


# Module-level provider for shutdown
_trace_provider: Optional[Any] = None


def init_telemetry(
    service_name: str = "skill-test",
    scenario: str = "unknown",
    debug: bool = True,
) -> Optional[Any]:
    """Initialize OpenTelemetry tracing and Loki logging."""
    global _tracer, _loki_endpoint, _debug_enabled, _scenario_name, _trace_provider

    _debug_enabled = debug
    _scenario_name = scenario

    if not debug:
        print("[OTEL] Debug mode disabled, telemetry off", file=sys.stderr)
        return None

    # Configure endpoints
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    _loki_endpoint = os.environ.get("LOKI_ENDPOINT", "http://localhost:3100")

    # For Docker containers, use host.docker.internal
    if os.path.exists("/.dockerenv"):
        otel_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://host.docker.internal:4318"
        )
        _loki_endpoint = os.environ.get(
            "LOKI_ENDPOINT", "http://host.docker.internal:3100"
        )

    # Initialize tracing if available
    if OTEL_AVAILABLE:
        try:
            resource = Resource.create({
                "service.name": service_name,
                "service.version": "1.0.0",
                "scenario": scenario,
            })

            _trace_provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=f"{otel_endpoint}/v1/traces")
            _trace_provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(_trace_provider)
            _tracer = trace.get_tracer(service_name)

            print(f"[OTEL] Tracing initialized -> {otel_endpoint}", file=sys.stderr)
        except Exception as e:
            print(f"[OTEL] Failed to initialize tracing: {e}", file=sys.stderr)
            _tracer = None
    else:
        print("[OTEL] OpenTelemetry not installed, tracing disabled", file=sys.stderr)

    print(f"[OTEL] Loki logging -> {_loki_endpoint}", file=sys.stderr)
    return _tracer


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush all pending spans."""
    global _trace_provider
    if _trace_provider is not None:
        try:
            _trace_provider.force_flush(timeout_millis=5000)
            _trace_provider.shutdown()
            print("[OTEL] Telemetry shutdown complete", file=sys.stderr)
        except Exception as e:
            print(f"[OTEL] Shutdown error: {e}", file=sys.stderr)


def log_to_loki(
    message: str,
    level: str = "info",
    labels: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> None:
    """Send a log entry to Loki."""
    if not _debug_enabled or not _loki_endpoint:
        return

    try:
        timestamp_ns = str(int(time.time() * 1e9))

        # Build log line with extra data
        log_data = {"message": message, "level": level}
        if extra:
            log_data.update(extra)

        log_line = json.dumps(log_data)

        # Build stream labels
        stream_labels = {
            "job": "skill-test",
            "scenario": _scenario_name,
            "level": level,
        }
        if labels:
            stream_labels.update(labels)

        payload = {
            "streams": [{
                "stream": stream_labels,
                "values": [[timestamp_ns, log_line]],
            }]
        }

        # Fire and forget
        requests.post(
            f"{_loki_endpoint}/loki/api/v1/push",
            json=payload,
            timeout=2,
        )
    except Exception:
        pass  # Don't fail tests due to logging issues


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[dict] = None,
    record_exception: bool = True,
):
    """Context manager for creating trace spans with timing."""
    start_time = time.time()

    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, str(value) if not isinstance(value, (int, float, bool)) else value)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            if record_exception:
                span.record_exception(e)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            span.set_attribute("duration_ms", duration_ms)


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

    specs = []
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
) -> tuple[str, list[ToolCall], int, float]:
    """
    Run a prompt through Claude and capture structured output.

    Returns: (response_text, tools_called, exit_code, duration_seconds)
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",  # Required for stream-json with -p
        "--model", model,
        "--dangerously-skip-permissions",
    ]

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
            return "", [], 1, duration
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
            return "", [], 1, duration

        duration = time.time() - start_time

        # Parse Claude Code's stream-json output format
        response_text = ""
        tools_called = []
        token_count = 0
        cost_usd = 0.0

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

            # Final result - capture metrics
            elif event_type == "result":
                if not response_text:
                    response_text = event.get("result", "")
                cost_usd = event.get("cost_usd", 0.0)
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

        # Log completion
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
                "response_preview": response_text[:500],
            },
        )

        return response_text, tools_called, result.returncode, duration


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

## Expected Behavior
{semantic}

## Tool Usage
Expected to call: {must_call}
Expected NOT to call: {must_not_call}
Actually called: {tools_called}

## Actual Response
{response_text}

## Text Pattern Results
Must contain (results): {must_contain_results}
Must not contain (results): {must_not_contain_results}

---

Evaluate the response and provide:

1. **quality**: Rate overall quality
   - "high": Correct tools, accurate information, clear formatting, meets semantic expectations
   - "medium": Mostly correct but minor issues (extra tools, verbose, slight formatting issues)
   - "low": Wrong tools, missing information, errors, hallucinations, or doesn't meet expectations

2. **tool_accuracy**: Rate tool usage
   - "correct": Used exactly the right tools
   - "partial": Used some right tools but also wrong ones, or missed some
   - "wrong": Used completely wrong tools

3. **reasoning**: Brief explanation of your rating

4. **refinement_suggestion**: If quality < high, suggest how to improve the SKILL (not the prompt) to get better results. Focus on skill descriptions, tool selection guidance, or missing capabilities.

5. **expectation_suggestion**: If the expectations themselves seem wrong or too strict/lenient, suggest how to adjust them.

Respond in JSON only:
{{
  "quality": "high|medium|low",
  "tool_accuracy": "correct|partial|wrong",
  "reasoning": "...",
  "refinement_suggestion": "...",
  "expectation_suggestion": "..."
}}"""


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

            # Try to extract JSON from response
            # Handle potential markdown code blocks
            if "```json" in output:
                output = output.split("```json")[1].split("```")[0].strip()
            elif "```" in output:
                output = output.split("```")[1].split("```")[0].strip()

            # Try to find JSON object in output
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                output = output[json_start:json_end]

            judge_result = json.loads(output)
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

            # Log judge result
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
                    "reasoning": parsed_result["reasoning"][:300],
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
        quality_color = {
            "high": c.GREEN,
            "medium": c.YELLOW,
            "low": c.RED,
        }.get(result.quality, c.DIM)
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


def generate_fix_context(result: PromptResult, skills_path: str) -> dict:
    """Generate fix context for the skill-fix agent."""
    import subprocess

    context = {
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
    plugin_path = Path(skills_path) / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = Path(skills_path) / "jira-assistant-skills"
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
            cwd=skills_path,
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
        lib_path = Path(skills_path) / "jira-assistant-skills-lib" / "src" / "jira_assistant_skills_lib"
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
) -> list[PromptResult]:
    """Run skill test for a scenario.

    Args:
        fix_context_mode: When True, all progress output goes to stderr to keep
                         stdout clean for JSON output.
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
    total_cost = 0.0

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

            # Run Claude (now returns 4 values including duration)
            with trace_span(
                "skill_test.prompt",
                attributes={
                    "prompt_index": spec.index,
                    "prompt_preview": spec.prompt[:100],
                },
            ) as prompt_span:
                response_text, tools_called, exit_code, prompt_duration = run_claude_prompt(
                    prompt, model=model, verbose=verbose, prompt_index=spec.index
                )
                total_duration += prompt_duration

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

                # Update prompt span with results
                if prompt_span:
                    prompt_span.set_attribute("passed", result.passed)
                    prompt_span.set_attribute("quality", result.quality)
                    prompt_span.set_attribute("tool_accuracy", result.tool_accuracy)
                    prompt_span.set_attribute("tools_called", ",".join(t.name for t in tools_called))

                results.append(result)
                print(f"  -> {'PASS' if result.passed else 'FAIL'} (quality: {result.quality})", file=out)

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
    args = parser.parse_args()

    if not args.prompts_file.exists():
        print(f"Error: File not found: {args.prompts_file}")
        sys.exit(1)

    scenario_name = args.prompts_file.stem

    # Initialize telemetry (enabled by default)
    init_telemetry(
        service_name="skill-test",
        scenario=scenario_name,
        debug=not args.no_debug,
    )

    results = run_skill_test(
        prompts_file=args.prompts_file,
        model=args.model,
        judge_model=args.judge_model,
        verbose=args.verbose,
        json_output=args.json,
        prompt_index=args.prompt_index,
        fix_context_mode=bool(args.fix_context),
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
