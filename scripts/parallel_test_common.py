"""
Common utilities for parallel test orchestrators.

Shared constants, path resolution, network management, and token retrieval
used by both parallel-mock-test.py and parallel-refine-loop.py.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

# Constants
DEMO_NETWORK = os.environ.get("DEMO_NETWORK", "demo-telemetry-network")
PROJECT_ROOT = Path(__file__).parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "demo-container" / "scenarios"

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

# Session and checkpoint paths - configurable via env vars (matching Makefile)
CLAUDE_SESSIONS_DIR = Path(os.environ.get("CLAUDE_SESSIONS_DIR", "/tmp/claude-sessions"))
CHECKPOINTS_DIR = Path(os.environ.get("CHECKPOINTS_DIR", "/tmp/checkpoints"))

# Container-side paths (used in docker mounts)
CONTAINER_CHECKPOINTS_DIR = "/tmp/checkpoints"
CONTAINER_SESSIONS_DIR = "/home/devuser/.claude/projects"


def get_checkpoint_file(scenario: str) -> str:
    """Get the checkpoint file path for a scenario (container-side path)."""
    return f"{CONTAINER_CHECKPOINTS_DIR}/{scenario}.json"


def ensure_checkpoint_dir() -> None:
    """Ensure the checkpoint directory exists on the host."""
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_sessions_dir() -> None:
    """Ensure the sessions directory exists on the host."""
    CLAUDE_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


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


def get_plugin_paths() -> tuple[Path, Path, Path]:
    """
    Get paths to JIRA plugin, library, and dist.

    Returns:
        Tuple of (plugin_path, lib_path, dist_path)
    """
    skills_path = Path(JIRA_SKILLS_PATH)

    # Try different plugin path patterns
    plugin_path = skills_path / "plugins" / "jira-assistant-skills"
    if not plugin_path.exists():
        plugin_path = skills_path / "jira-assistant-skills"

    lib_path = skills_path / "jira-assistant-skills-lib"
    # Use consolidated wheel from lib dist (contains both library and CLI)
    dist_path = skills_path / "jira-assistant-skills-lib" / "dist"

    return plugin_path, lib_path, dist_path


def get_claude_token() -> str:
    """
    Get Claude auth token from environment or macOS keychain.

    First checks CLAUDE_CODE_OAUTH_TOKEN env var, then falls back
    to macOS keychain lookup.
    """
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
                 "-s", "CLAUDE_CODE_OAUTH_TOKEN", "-w"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                token = result.stdout.strip()
        except Exception:
            pass
    return token


def parse_test_output(stdout: str) -> Optional[dict]:
    """
    Parse JSON fix context from test output.

    Handles both clean JSON output and output with non-JSON preamble.

    Args:
        stdout: Raw stdout from test command

    Returns:
        Parsed JSON dict or None if parsing fails
    """
    stdout = stdout.strip()

    # Try direct parse first
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in output (may have non-JSON preamble)
    # Look for first { character
    brace_idx = stdout.find("{")
    if brace_idx >= 0:
        try:
            return json.loads(stdout[brace_idx:])
        except json.JSONDecodeError:
            pass

    # Try scanning from end (in case of trailing output)
    for line in reversed(stdout.split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    return None


def validate_scenarios(scenarios: list[str]) -> list[str]:
    """
    Validate that scenario .prompts files exist.

    Args:
        scenarios: List of scenario names to validate

    Returns:
        List of missing scenario names (empty if all valid)
    """
    missing = []
    for s in scenarios:
        if not (SCENARIOS_DIR / f"{s}.prompts").exists():
            missing.append(s)
    return missing


def parse_scenario_arg(scenarios_arg: str) -> list[str]:
    """
    Parse scenarios argument into list.

    Args:
        scenarios_arg: Either "all" or comma-separated scenario names

    Returns:
        List of scenario names
    """
    if scenarios_arg == "all":
        return ALL_SCENARIOS.copy()
    return [s.strip() for s in scenarios_arg.split(",")]
