"""
Shared utilities for JIRA sandbox scripts.

Provides common imports, constants, and helpers for seed_demo_data.py
and cleanup_demo_sandbox.py.
"""

import sys
from typing import Any

# =============================================================================
# JIRA Library Imports (with fallback)
# =============================================================================

try:
    from jira_assistant_skills_lib import get_jira_client, print_error, print_success
    from jira_assistant_skills_lib.error_handler import JiraError
except ImportError:
    print("Error: jira-assistant-skills-lib not installed")
    print("Run: pip install jira-assistant-skills-lib")
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
