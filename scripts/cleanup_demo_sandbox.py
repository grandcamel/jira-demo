#!/usr/bin/env python3
"""
Clean up JIRA sandbox after demo sessions.

Deletes user-created issues (key > 10) and resets seed issues
to their initial state.

Usage:
    python cleanup_demo_sandbox.py
    python cleanup_demo_sandbox.py --dry-run
    python cleanup_demo_sandbox.py --full  # Also delete seed issues
"""

import argparse
import sys
from typing import Any

try:
    from jira_assistant_skills_lib import get_jira_client, print_error, print_success
    from jira_assistant_skills_lib.error_handler import JiraError
except ImportError:
    print("Error: jira-assistant-skills-lib not installed")
    print("Run: pip install jira-assistant-skills-lib")
    sys.exit(1)

from otel_setup import init_telemetry, traced, trace_span, add_span_attribute


# =============================================================================
# Configuration
# =============================================================================

DEMO_PROJECT = "DEMO"
DEMO_SERVICE_DESK = "DEMOSD"

# Seed issues to preserve (issues 1-10)
SEED_ISSUE_COUNT = 10

# Initial states for seed issues
SEED_ISSUE_STATES = {
    "DEMO-1": {"status": "Open"},
    "DEMO-2": {"status": "Open"},
    "DEMO-3": {"status": "Open"},
    "DEMO-4": {"status": "To Do"},
    "DEMO-5": {"status": "In Progress"},
    "DEMO-6": {"status": "To Do"},
    "DEMO-7": {"status": "Open"},
    "DEMO-8": {"status": "Open"},
    "DEMO-9": {"status": "Open"},
    "DEMO-10": {"status": "To Do"},
}


@traced("cleanup.delete_user_issues")
def delete_user_created_issues(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all issues created by demo users (key > SEED_ISSUE_COUNT)."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Cleaning up user-created issues in {project_key}...")

    # Search for issues beyond seed data
    # JIRA doesn't support key > DEMO-10 directly, so we search all and filter
    jql = f"project = {project_key} ORDER BY created DESC"

    try:
        result = client.search_issues(jql, fields=["key", "summary"], max_results=100)
        issues = result.get("issues", [])

        for issue in issues:
            key = issue["key"]
            # Extract issue number
            try:
                issue_num = int(key.split("-")[1])
            except (IndexError, ValueError):
                continue

            # Skip seed issues
            if issue_num <= SEED_ISSUE_COUNT:
                continue

            summary = issue["fields"]["summary"]

            if dry_run:
                print(f"  Would delete: {key} - {summary[:50]}")
            else:
                try:
                    client.delete_issue(key)
                    print(f"  Deleted: {key} - {summary[:50]}")
                except JiraError as e:
                    print(f"  Error deleting {key}: {e}")
                    continue

            deleted_count += 1

    except JiraError as e:
        print(f"  Error searching {project_key}: {e}")

    return deleted_count


@traced("cleanup.reset_seed_issues")
def reset_seed_issues(client: Any, dry_run: bool = False) -> int:
    """Reset seed issues to their initial state."""
    reset_count = 0
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Resetting seed issues...")

    for issue_key, target_state in SEED_ISSUE_STATES.items():
        try:
            # Get current issue state
            issue = client.get_issue(issue_key, fields=["status", "assignee", "resolution"])

            current_status = issue["fields"]["status"]["name"]
            target_status = target_state["status"]

            # Check if status needs to be reset
            if current_status != target_status:
                if dry_run:
                    print(f"  Would reset: {issue_key} from '{current_status}' to '{target_status}'")
                else:
                    # Get available transitions
                    transitions = client.get_transitions(issue_key)

                    # Find transition to target status
                    transition_id = None
                    for t in transitions.get("transitions", []):
                        if t["to"]["name"].lower() == target_status.lower():
                            transition_id = t["id"]
                            break

                    if transition_id:
                        client.transition_issue(issue_key, transition_id)
                        print(f"  Reset: {issue_key} from '{current_status}' to '{target_status}'")
                        reset_count += 1
                    else:
                        print(f"  Warning: Cannot transition {issue_key} to '{target_status}'")

            # Unassign if assigned
            if issue["fields"].get("assignee"):
                if dry_run:
                    print(f"  Would unassign: {issue_key}")
                else:
                    client.update_issue(issue_key, {"assignee": None})
                    print(f"  Unassigned: {issue_key}")

            # Clear resolution if resolved
            if issue["fields"].get("resolution"):
                if dry_run:
                    print(f"  Would clear resolution: {issue_key}")
                else:
                    try:
                        client.update_issue(issue_key, {"resolution": None})
                        print(f"  Cleared resolution: {issue_key}")
                    except JiraError:
                        pass  # May not be editable

        except JiraError as e:
            print(f"  Error with {issue_key}: {e}")

    return reset_count


@traced("cleanup.delete_comments")
def delete_comments(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all comments on seed issues."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Cleaning up comments in {project_key}...")

    for i in range(1, SEED_ISSUE_COUNT + 1):
        issue_key = f"{project_key}-{i}"

        try:
            # Get comments
            comments = client.get_comments(issue_key)

            for comment in comments.get("comments", []):
                comment_id = comment["id"]
                body_preview = comment.get("body", {})
                if isinstance(body_preview, dict):
                    # ADF format
                    body_preview = "..."
                else:
                    body_preview = body_preview[:30] + "..."

                if dry_run:
                    print(f"  Would delete comment on {issue_key}: {body_preview}")
                else:
                    try:
                        client.delete_comment(issue_key, comment_id)
                        print(f"  Deleted comment on {issue_key}")
                        deleted_count += 1
                    except JiraError:
                        pass

        except JiraError:
            pass  # Issue may not exist

    return deleted_count


@traced("cleanup.delete_worklogs")
def delete_worklogs(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all worklogs on seed issues."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Cleaning up worklogs in {project_key}...")

    for i in range(1, SEED_ISSUE_COUNT + 1):
        issue_key = f"{project_key}-{i}"

        try:
            # Get worklogs
            worklogs = client.get_worklogs(issue_key)

            for worklog in worklogs.get("worklogs", []):
                worklog_id = worklog["id"]
                time_spent = worklog.get("timeSpent", "?")

                if dry_run:
                    print(f"  Would delete worklog on {issue_key}: {time_spent}")
                else:
                    try:
                        client.delete_worklog(issue_key, worklog_id)
                        print(f"  Deleted worklog on {issue_key}: {time_spent}")
                        deleted_count += 1
                    except JiraError:
                        pass

        except JiraError:
            pass  # Issue may not exist

    return deleted_count


def main():
    parser = argparse.ArgumentParser(
        description="Clean up JIRA sandbox after demo sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python cleanup_demo_sandbox.py
    python cleanup_demo_sandbox.py --dry-run
    python cleanup_demo_sandbox.py --full  # Delete everything
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without making changes")
    parser.add_argument("--full", action="store_true", help="Also delete seed issues (requires re-seeding)")
    parser.add_argument("--profile", default="demo", help="JIRA profile to use (default: demo)")
    args = parser.parse_args()

    # Initialize OpenTelemetry tracing
    init_telemetry("jira-demo-cleanup")

    try:
        client = get_jira_client(profile=args.profile)

        print("=" * 60)
        print("JIRA Demo Sandbox Cleanup")
        print("=" * 60)

        # Delete user-created issues in DEMO project
        demo_deleted = delete_user_created_issues(client, DEMO_PROJECT, args.dry_run)

        # Delete user-created issues in DEMOSD service desk
        sd_deleted = delete_user_created_issues(client, DEMO_SERVICE_DESK, args.dry_run)

        # Clean up comments and worklogs on seed issues
        comments_deleted = delete_comments(client, DEMO_PROJECT, args.dry_run)
        worklogs_deleted = delete_worklogs(client, DEMO_PROJECT, args.dry_run)

        # Reset seed issues to initial state
        reset_count = reset_seed_issues(client, args.dry_run)

        # Summary
        print("\n" + "=" * 60)
        if args.dry_run:
            print("[DRY RUN] Would process:")
        else:
            print("Cleanup complete:")
        print(f"  {demo_deleted} issues deleted from {DEMO_PROJECT}")
        print(f"  {sd_deleted} requests deleted from {DEMO_SERVICE_DESK}")
        print(f"  {comments_deleted} comments deleted")
        print(f"  {worklogs_deleted} worklogs deleted")
        print(f"  {reset_count} seed issues reset")
        print("=" * 60)

        if not args.dry_run:
            print_success("Sandbox cleanup complete!")

    except JiraError as e:
        print_error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
