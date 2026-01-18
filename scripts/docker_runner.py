"""
Docker command builder for skill test containers.

Provides a unified way to build docker run commands for skill testing,
eliminating duplication across parallel test scripts.

Usage:
    from docker_runner import build_skill_test_command

    cmd, inner_cmd = build_skill_test_command(
        scenario="search",
        mock_mode=True,
        fix_context=True,
    )
    subprocess.run(cmd + [inner_cmd], ...)
"""

import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from parallel_test_common import (
    CHECKPOINTS_DIR,
    CLAUDE_SESSIONS_DIR,
    CONTAINER_CHECKPOINTS_DIR,
    CONTAINER_SESSIONS_DIR,
    DEMO_NETWORK,
    JIRA_SKILLS_PATH,
    PROJECT_ROOT,
    get_claude_token,
    get_plugin_paths,
)

# Secure env file for Docker (avoids token exposure in ps output)
_ENV_FILE_PATH = Path("/tmp/docker_skill_test.env")


@dataclass
class SkillTestConfig:
    """Configuration for skill test docker command."""

    # Required
    scenario: str

    # Test mode
    mock_mode: bool = False
    conversation_mode: bool = False
    fail_fast: bool = False
    fix_context: bool = False
    verbose: bool = False

    # Checkpoint/fork options
    checkpoint_file: Optional[str] = None
    fork_from: Optional[int] = None
    prompt_index: Optional[int] = None

    # Model options
    model: str = "sonnet"
    judge_model: str = "haiku"

    # Mount options - which local files to mount into container
    mount_skill_test: bool = False  # Mount local skill-test.py
    mount_scenarios: bool = False  # Mount local scenarios/
    mount_patches: bool = True  # Mount patches for mock persistence
    mount_sessions: bool = False  # Mount session persistence dir
    mount_checkpoints: bool = False  # Mount checkpoints dir

    # Session directory (only used if mount_sessions=True)
    sessions_dir: Path = field(default_factory=lambda: CLAUDE_SESSIONS_DIR)

    # Extra test arguments
    extra_args: list[str] = field(default_factory=list)


def _write_secure_env_file(token: str) -> Path:
    """
    Write OAuth token to a secure env file for Docker.

    Uses a fixed path with restricted permissions (0600) to prevent
    token exposure in `ps` output. The file is overwritten on each call.

    Args:
        token: The OAuth token to write

    Returns:
        Path to the env file
    """
    # Write with restricted permissions to prevent other users from reading
    env_content = f"CLAUDE_CODE_OAUTH_TOKEN={token}\n"

    # Remove existing file first (to reset permissions if needed)
    if _ENV_FILE_PATH.exists():
        _ENV_FILE_PATH.unlink()

    # Create with restricted permissions (owner read/write only)
    _ENV_FILE_PATH.touch(mode=stat.S_IRUSR | stat.S_IWUSR)
    _ENV_FILE_PATH.write_text(env_content)

    return _ENV_FILE_PATH


def build_skill_test_command(config: SkillTestConfig) -> tuple[list[str], str]:
    """
    Build docker run command for skill testing.

    Args:
        config: SkillTestConfig with all options

    Returns:
        Tuple of (docker_cmd_list, inner_bash_command)
        Use as: subprocess.run(docker_cmd + [inner_cmd], ...)
    """
    plugin_path, lib_path, dist_path = get_plugin_paths()
    claude_token = get_claude_token()

    # Ensure sessions dir exists if mounting
    if config.mount_sessions:
        config.sessions_dir.mkdir(parents=True, exist_ok=True)

    # Build docker command
    cmd = [
        "docker", "run", "--rm",
        "--network", DEMO_NETWORK,
    ]

    # Environment variables
    if config.mock_mode:
        cmd.extend(["-e", "JIRA_MOCK_MODE=true"])

    if config.mount_patches:
        cmd.extend(["-e", "PYTHONPATH=/workspace/patches"])

    # Telemetry endpoints
    cmd.extend([
        "-e", "OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318",
        "-e", "LOKI_ENDPOINT=http://lgtm:3100",
    ])

    # Claude auth via secure env file (avoids token exposure in ps output)
    env_file = _write_secure_env_file(claude_token)
    cmd.extend(["--env-file", str(env_file)])

    # Required mounts - plugin and dist
    cmd.extend([
        "-v", f"{plugin_path}:/home/devuser/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev:ro",
        "-v", f"{dist_path}:/opt/jira-dist:ro",
    ])

    # Optional mounts
    if config.mount_patches:
        cmd.extend([
            "-v", f"{PROJECT_ROOT}/demo-container/patches:/workspace/patches:ro",
        ])

    if config.mount_skill_test:
        cmd.extend([
            "-v", f"{PROJECT_ROOT}/demo-container/skill-test.py:/workspace/skill-test.py:ro",
        ])

    if config.mount_scenarios:
        cmd.extend([
            "-v", f"{PROJECT_ROOT}/demo-container/scenarios:/workspace/scenarios:ro",
        ])

    if config.mount_sessions:
        cmd.extend([
            "-v", f"{config.sessions_dir}:{CONTAINER_SESSIONS_DIR}:rw",
        ])

    if config.mount_checkpoints:
        cmd.extend([
            "-v", f"{CHECKPOINTS_DIR}:{CONTAINER_CHECKPOINTS_DIR}",
        ])

    # Entrypoint
    cmd.extend([
        "--entrypoint", "bash",
        "jira-demo-container:latest",
        "-c",
    ])

    # Build inner command
    inner_parts = [
        # Install wheel for jira-as CLI
        "pip install -q /opt/jira-dist/*.whl 2>/dev/null",
        # Remove old plugin symlink
        "rm -f ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null",
        # Create new symlink to dev version
        "ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 2>/dev/null",
    ]

    if config.mount_checkpoints:
        inner_parts.append(f"mkdir -p {CONTAINER_CHECKPOINTS_DIR}")

    # Build skill-test.py command
    test_cmd_parts = [
        "cd /tmp &&",
        "python /workspace/skill-test.py",
        f"/workspace/scenarios/{config.scenario}.prompts",
        f"--model {config.model}",
        f"--judge-model {config.judge_model}",
    ]

    if config.mock_mode:
        test_cmd_parts.append("--mock")

    if config.conversation_mode:
        test_cmd_parts.append("--conversation")

    if config.fail_fast:
        test_cmd_parts.append("--fail-fast")

    if config.verbose:
        test_cmd_parts.append("--verbose")

    if config.fix_context:
        test_cmd_parts.append(f"--fix-context {JIRA_SKILLS_PATH}")

    if config.checkpoint_file:
        test_cmd_parts.append(f"--checkpoint-file {config.checkpoint_file}")

    if config.fork_from is not None:
        test_cmd_parts.append(f"--fork-from {config.fork_from}")

    if config.prompt_index is not None:
        test_cmd_parts.append(f"--prompt-index {config.prompt_index}")

    # Add any extra arguments
    test_cmd_parts.extend(config.extra_args)

    # Join inner command
    inner_parts.append(" ".join(test_cmd_parts))
    inner_cmd = "; ".join(inner_parts)

    return cmd, inner_cmd


def build_simple_skill_test_command(
    scenario: str,
    mock_mode: bool = True,
    fix_context: bool = True,
    verbose: bool = False,
) -> tuple[list[str], str]:
    """
    Simplified builder for common mock test case.

    This is a convenience function for the most common use case:
    running a mock test with fix context output.
    """
    config = SkillTestConfig(
        scenario=scenario,
        mock_mode=mock_mode,
        fix_context=fix_context,
        verbose=verbose,
        mount_patches=True,
    )
    return build_skill_test_command(config)


def build_refine_skill_test_command(
    scenario: str,
    checkpoint_file: str,
    fork_from: Optional[int] = None,
    prompt_index: Optional[int] = None,
    verbose: bool = False,
) -> tuple[list[str], str]:
    """
    Builder for refinement loop test case.

    This is a convenience function for running tests during
    the refinement loop with checkpoint and fork support.
    """
    config = SkillTestConfig(
        scenario=scenario,
        mock_mode=True,
        conversation_mode=True,
        fail_fast=True,
        fix_context=True,
        verbose=verbose,
        checkpoint_file=checkpoint_file,
        fork_from=fork_from,
        prompt_index=prompt_index,
        mount_patches=True,
        mount_skill_test=True,
        mount_scenarios=True,
        mount_sessions=True,
        mount_checkpoints=True,
    )
    return build_skill_test_command(config)
