import os
import subprocess
import time
import re
from dotenv import load_dotenv
from openai import OpenAI

from src.helpers.github import GHHelper

load_dotenv()

DEMO_DIR = r"C:\Users\Expertizo\oa-demo-repo"
GITHUB_REPO = os.getenv("GITHUB_REPO_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN_INTERN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

POLL_EVERY = 30  # seconds between checks

client = OpenAI(api_key=OPENAI_API_KEY)


def get_pr_branch(gh_helper, pr_number):
    pr = gh_helper.repo.get_pull(pr_number)
    return pr.head.ref


def resolve_file_conflict(file_path, content_with_markers):
    prompt = f"""The following file has git merge conflict markers (<<<<<<<, =======, >>>>>>>).
Resolve the conflict by intelligently combining both versions where sensible, keeping the code correct and functional.
Return ONLY the full resolved file content, with no markers and no explanation, no markdown code fences.

File: {file_path}

Content with conflict markers:
{content_with_markers}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    resolved = response.choices[0].message.content
    resolved = re.sub(r"^```[a-zA-Z]*\n", "", resolved)
    resolved = re.sub(r"\n```$", "", resolved)
    return resolved


def resolve_pr_conflict(gh_helper, pr_number):
    """Same logic as the old resolve_conflict.py main(), just callable per-PR."""
    print(f"[Conflict Resolver] Conflict detected on PR #{pr_number}! Starting resolution...")

    branch_name = get_pr_branch(gh_helper, pr_number)
    print(f"[Conflict Resolver] Working on branch: {branch_name}")

    subprocess.run(["git", "fetch", "origin"], cwd=DEMO_DIR)

    print(f"[Conflict Resolver] Cleaning up any leftover local changes...")
    subprocess.run(["git", "checkout", "--", "."], cwd=DEMO_DIR)
    subprocess.run(["git", "clean", "-fd"], cwd=DEMO_DIR)

    subprocess.run(["git", "checkout", branch_name], cwd=DEMO_DIR)
    subprocess.run(["git", "checkout", "--", "."], cwd=DEMO_DIR)
    subprocess.run(["git", "pull", "origin", branch_name], cwd=DEMO_DIR)

    print(f"[Conflict Resolver] Merging main into {branch_name}...")
    merge_result = subprocess.run(
        ["git", "merge", "origin/main"], cwd=DEMO_DIR, capture_output=True, text=True
    )
    print(merge_result.stdout)
    print(merge_result.stderr)

    conflicted = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=DEMO_DIR,
        capture_output=True,
        text=True,
    ).stdout.strip().split("\n")
    conflicted = [f for f in conflicted if f]

    if not conflicted:
        print(f"[Conflict Resolver] PR #{pr_number}: no conflicted files found after merge attempt.")
        return

    print(f"[Conflict Resolver] Conflicted files: {conflicted}")

    for file_path in conflicted:
        full_path = os.path.join(DEMO_DIR, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            content_with_markers = f.read()

        print(f"[Conflict Resolver] Asking AI to resolve {file_path}...")
        resolved = resolve_file_conflict(file_path, content_with_markers)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(resolved)

        print(f"[Conflict Resolver] Resolved {file_path}")
        subprocess.run(["git", "add", file_path], cwd=DEMO_DIR)

    print("[Conflict Resolver] Committing the merge resolution...")
    subprocess.run(
        ["git", "commit", "-m", f"resolve: merge conflicts in PR #{pr_number}"],
        cwd=DEMO_DIR,
    )

    print("[Conflict Resolver] Pushing resolution...")
    subprocess.run(["git", "push", "origin", branch_name], cwd=DEMO_DIR)

    print(f"[Conflict Resolver] Done! PR #{pr_number} should now be mergeable.")


def watch():
    gh_helper = GHHelper(GITHUB_TOKEN, GITHUB_REPO)
    print(f"[Conflict Resolver] Watching open PRs every {POLL_EVERY}s for conflicts...")

    while True:
        try:
            open_prs = gh_helper.list_open_prs()
            for pr in open_prs:
                mergeable = gh_helper.is_mergeable(pr.id)
                if mergeable is False:
                    resolve_pr_conflict(gh_helper, pr.id)
                # mergeable is None -> GitHub hasn't finished computing it yet, skip this cycle
        except Exception as e:
            print(f"[Conflict Resolver] Error during check: {e}")

        time.sleep(POLL_EVERY)


if __name__ == "__main__":
    watch()