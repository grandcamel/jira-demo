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

    state = {
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


def _patch_mock_client_base(cls):
    """Patch MockJiraClientBase to use file-based persistence."""
    original_init = cls.__init__
    original_create = cls.create_issue
    original_update = cls.update_issue
    original_transition = cls.transition_issue
    original_assign = cls.assign_issue

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Load persisted state after normal init
        persisted_issues, next_id = _load_issues_state()
        if persisted_issues:
            self._issues.update(persisted_issues)
            self._next_issue_id = max(self._next_issue_id, next_id)

    def patched_create(self, fields):
        result = original_create(self, fields)
        _save_issues_state(self._issues, self._next_issue_id)
        return result

    def patched_update(self, issue_key, fields=None, update=None):
        result = original_update(self, issue_key, fields, update)
        _save_issues_state(self._issues, self._next_issue_id)
        return result

    def patched_transition(self, issue_key, transition_id, fields=None, update=None, comment=None):
        result = original_transition(self, issue_key, transition_id, fields, update, comment)
        _save_issues_state(self._issues, self._next_issue_id)
        return result

    def patched_assign(self, issue_key, account_id=None):
        result = original_assign(self, issue_key, account_id)
        _save_issues_state(self._issues, self._next_issue_id)
        return result

    cls.__init__ = patched_init
    cls.create_issue = patched_create
    cls.update_issue = patched_update
    cls.transition_issue = patched_transition
    cls.assign_issue = patched_assign

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
sys.meta_path.insert(0, MockPersistenceImportHook())
