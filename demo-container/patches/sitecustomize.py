"""Mock persistence patch for JIRA demo container.

This sitecustomize.py is automatically loaded by Python on startup.
It installs an import hook that patches the mock client to use file-based
persistence, allowing created issues to persist across CLI invocations.

State file: /tmp/mock_state.json (reset per scenario)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

MOCK_STATE_FILE = Path(os.environ.get("MOCK_STATE_FILE", "/tmp/mock_state.json"))


SEED_ISSUE_KEYS = {
    "DEMO-84", "DEMO-85", "DEMO-86", "DEMO-87", "DEMO-91",
    "DEMOSD-1", "DEMOSD-2", "DEMOSD-3", "DEMOSD-4", "DEMOSD-5",
}


def _save_issues_state(issues: dict, next_id: int) -> None:
    """Save issue state to file."""
    # Only save if in mock mode
    if os.environ.get("JIRA_MOCK_MODE", "").lower() != "true":
        return

    state: dict[str, Any] = {
        "next_issue_id": next_id,
        "issues": {},
    }
    # Only save non-seed issues (exclude original mock seed data)
    for key, issue in issues.items():
        if key not in SEED_ISSUE_KEYS:
            state["issues"][key] = issue

    try:
        MOCK_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass  # Silently fail - don't break CLI operations


def _load_issues_state() -> tuple[dict, int]:
    """Load issue state from file. Returns (issues_dict, next_issue_id)."""
    if not MOCK_STATE_FILE.exists():
        return {}, 100

    try:
        state = json.loads(MOCK_STATE_FILE.read_text())
        return state.get("issues", {}), state.get("next_issue_id", 100)
    except Exception:
        return {}, 100


def _wrap_with_persistence(original_method):
    """Wrap a method to save state after execution."""
    def wrapper(self, *args, **kwargs):
        result = original_method(self, *args, **kwargs)
        _save_issues_state(self._issues, self._next_issue_id)
        return result
    return wrapper


def _patch_mock_client_base(cls):
    """Patch MockJiraClientBase to use file-based persistence."""
    original_init = cls.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Load persisted state after normal init
        persisted_issues, next_id = _load_issues_state()
        if persisted_issues:
            self._issues.update(persisted_issues)
            self._next_issue_id = max(self._next_issue_id, next_id)

    cls.__init__ = patched_init

    # Wrap mutation methods to persist state after each call
    for method_name in ("create_issue", "update_issue", "transition_issue", "assign_issue"):
        original = getattr(cls, method_name)
        setattr(cls, method_name, _wrap_with_persistence(original))

    # Mark as patched to avoid double-patching
    cls._mock_persistence_patched = True


class MockPersistenceImportHook:
    """Import hook that patches mock client when it's imported."""

    def find_module(self, fullname, path=None):
        # Only intercept the mock base module
        if fullname == "jira_assistant_skills_lib.mock.base":
            return self
        return None

    def load_module(self, fullname):
        # Check if already loaded
        if fullname in sys.modules:
            module = sys.modules[fullname]
            # Patch if not already patched
            if hasattr(module, "MockJiraClientBase"):
                cls = module.MockJiraClientBase
                if not getattr(cls, "_mock_persistence_patched", False):
                    _patch_mock_client_base(cls)
            return module

        # Remove ourselves temporarily to avoid recursion
        sys.meta_path.remove(self)
        try:
            import importlib

            module = importlib.import_module(fullname)
            sys.modules[fullname] = module

            # Patch the class
            if hasattr(module, "MockJiraClientBase"):
                _patch_mock_client_base(module.MockJiraClientBase)

            return module
        finally:
            # Re-add ourselves
            sys.meta_path.insert(0, self)


# Install the import hook
sys.meta_path.insert(0, MockPersistenceImportHook())  # type: ignore[arg-type]
