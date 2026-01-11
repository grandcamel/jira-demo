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

from sandbox_common import (
    DEMO_PROJECT,
    DEMO_SERVICE_DESK,
    JiraError,
    add_span_attribute,
    build_jql,
    dry_run_prefix,
    get_jira_client,
    init_telemetry,
    print_error,
    print_success,
    traced,
)


# =============================================================================
# Configuration
# =============================================================================

# Default status to reset seed issues to
DEFAULT_STATUS = "Open"


@traced("cleanup.delete_user_issues")
def delete_user_created_issues(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all issues NOT labeled with SEED_LABEL (user-created issues)."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Cleaning up user-created issues in {project_key}...")

    # Search for issues without the seed label
    jql = build_jql(project_key=project_key, is_seed=False, order_by="created DESC")

    try:
        result = client.search_issues(jql, fields=["key", "summary"], max_results=100)
        issues = result.get("issues", [])

        for issue in issues:
            key = issue["key"]
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

        if not issues:
            print("  No user-created issues found")

    except JiraError as e:
        print(f"  Error searching {project_key}: {e}")

    return deleted_count


@traced("cleanup.reset_seed_issues")
def reset_seed_issues(client: Any, dry_run: bool = False) -> int:
    """Reset seed issues (labeled with SEED_LABEL) to their initial state."""
    reset_count = 0
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Resetting seed issues...")

    # Find all seed issues by label
    jql = build_jql(is_seed=True)

    try:
        result = client.search_issues(jql, fields=["key", "status", "assignee", "resolution"], max_results=100)
        issues = result.get("issues", [])

        if not issues:
            print("  No seed issues found")
            return 0

        for issue in issues:
            issue_key = issue["key"]
            current_status = issue["fields"]["status"]["name"]

            try:
                # Reset to Open status if not already
                if current_status != DEFAULT_STATUS:
                    if dry_run:
                        print(f"  Would reset: {issue_key} from '{current_status}' to '{DEFAULT_STATUS}'")
                    else:
                        # Get available transitions
                        transitions = client.get_transitions(issue_key)

                        # Find transition to target status
                        transition_id = None
                        for t in transitions.get("transitions", []):
                            if t["to"]["name"].lower() == DEFAULT_STATUS.lower():
                                transition_id = t["id"]
                                break

                        if transition_id:
                            client.transition_issue(issue_key, transition_id)
                            print(f"  Reset: {issue_key} from '{current_status}' to '{DEFAULT_STATUS}'")
                            reset_count += 1
                        else:
                            print(f"  Warning: Cannot transition {issue_key} to '{DEFAULT_STATUS}'")

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

    except JiraError as e:
        print(f"  Error searching for seed issues: {e}")

    return reset_count


@traced("cleanup.delete_comments")
def delete_comments(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all comments on seed issues (identified by label)."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Cleaning up comments in {project_key}...")

    # Find seed issues by label
    jql = build_jql(project_key=project_key, is_seed=True)

    try:
        result = client.search_issues(jql, fields=["key"], max_results=100)
        issues = result.get("issues", [])

        if not issues:
            print("  No seed issues found")
            return 0

        for issue in issues:
            issue_key = issue["key"]

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

    except JiraError as e:
        print(f"  Error searching for seed issues: {e}")

    return deleted_count


@traced("cleanup.delete_worklogs")
def delete_worklogs(client: Any, project_key: str, dry_run: bool = False) -> int:
    """Delete all worklogs on seed issues (identified by label)."""
    deleted_count = 0
    add_span_attribute("project.key", project_key)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Cleaning up worklogs in {project_key}...")

    # Find seed issues by label
    jql = build_jql(project_key=project_key, is_seed=True)

    try:
        result = client.search_issues(jql, fields=["key"], max_results=100)
        issues = result.get("issues", [])

        if not issues:
            print("  No seed issues found")
            return 0

        for issue in issues:
            issue_key = issue["key"]

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

    except JiraError as e:
        print(f"  Error searching for seed issues: {e}")

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
    args = parser.parse_args()

    # Initialize OpenTelemetry tracing
    init_telemetry("jira-demo-cleanup")

    try:
        client = get_jira_client()

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
