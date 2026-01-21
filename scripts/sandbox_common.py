"""
Shared utilities for JIRA sandbox scripts.

Provides common imports, constants, and helpers for seed_demo_data.py
and cleanup_demo_sandbox.py.
"""

import sys
from typing import Any, Callable

# =============================================================================
# JIRA Library Imports (with fallback)
# =============================================================================

try:
    from jira_as import get_jira_client, print_error, print_success  # type: ignore[import-untyped]
    from jira_as.error_handler import JiraError  # type: ignore[import-untyped]
except ImportError:
    print("Error: jira-as not installed")
    print("Run: pip install jira-as")
    sys.exit(1)

# Re-export for convenience
__all__ = [
    # JIRA library
    "get_jira_client",
    "print_error",
    "print_success",
    "JiraError",
    # Telemetry
    "init_telemetry",
    "traced",
    "add_span_attribute",
    # Constants
    "DEMO_PROJECT",
    "DEMO_SERVICE_DESK",
    "SEED_LABEL",
    # Helpers
    "dry_run_prefix",
    "build_adf_description",
    "build_jql",
    "for_each_issue",
]

# =============================================================================
# Telemetry Imports
# =============================================================================

from otel_setup import init_telemetry, traced, add_span_attribute

# =============================================================================
# Shared Constants
# =============================================================================

# Project keys for demo sandbox
DEMO_PROJECT = "DEMO"
DEMO_SERVICE_DESK = "DEMOSD"

# Label used to identify seed issues (vs user-created issues)
SEED_LABEL = "demo"


# =============================================================================
# Helpers
# =============================================================================


def dry_run_prefix(dry_run: bool) -> str:
    """Return prefix string for dry-run mode messages."""
    return "[DRY RUN] " if dry_run else ""


def build_adf_description(text: str) -> dict:
    """Build Atlassian Document Format description for JIRA API.

    Args:
        text: Plain text description content

    Returns:
        ADF-formatted description dict
    """
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def build_jql(
    project_key: str | None = None,
    is_seed: bool | None = None,
    order_by: str = "key ASC",
) -> str:
    """Build JQL query for sandbox operations.

    Args:
        project_key: Filter by project (e.g., "DEMO")
        is_seed: True for seed issues only, False for non-seed only, None for all
        order_by: ORDER BY clause (default: "key ASC")

    Returns:
        JQL query string
    """
    parts = []
    if project_key:
        parts.append(f"project = {project_key}")
    if is_seed is True:
        parts.append(f"labels = {SEED_LABEL}")
    elif is_seed is False:
        parts.append(f"labels != {SEED_LABEL}")

    jql = " AND ".join(parts) if parts else ""
    if jql:
        jql += f" ORDER BY {order_by}"
    return jql


def for_each_issue(
    client: Any,
    jql: str,
    operation: Callable[[Any, Any, bool], bool],
    dry_run: bool = False,
    fields: list[str] | None = None,
) -> int:
    """Iterate over issues matching JQL and apply operation.

    Args:
        client: JIRA client instance
        jql: JQL query to find issues
        operation: Function(client, issue, dry_run) -> bool (True if processed)
        dry_run: If True, operation should only print what it would do
        fields: Fields to fetch (default: ["key"])

    Returns:
        Count of processed items
    """
    if fields is None:
        fields = ["key"]

    count = 0
    try:
        result = client.search_issues(jql, fields=fields, max_results=100)
        for issue in result.get("issues", []):
            if operation(client, issue, dry_run):
                count += 1
    except JiraError as e:
        print(f"  Error searching issues: {e}")

    return count
