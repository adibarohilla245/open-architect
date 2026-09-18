import sys
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


def process_pr(gh_helper, pr_number, chrome_path):
    pr_url = f"https://github.com/adibarohilla245/oa-demo-repo/pull/{pr_number}"

    print(f"[Conflict Resolver] Opening PR #{pr_number} to check its status...")
    os.system(f'start "" {chrome_path} "{pr_url}"')
    time.sleep(2)

    print(f"[Conflict Resolver] Checking mergeability of PR #{pr_number}...")
    mergeable = gh_helper.is_mergeable(pr_number)

    if mergeable:
        print(f"[Conflict Resolver] PR #{pr_number} has no conflicts. Skipping.")
        return

    print(f"[Conflict Resolver] Conflict detected on PR #{pr_number}! Starting resolution...")

    branch_name = get_pr_branch(gh_helper, pr_number)
    print(f"[Conflict Resolver] Working on branch: {branch_name}")

    print(f"[Conflict Resolver] Opening my project folder...")
    subprocess.Popen(["code", "-n", DEMO_DIR], shell=True)
    time.sleep(2)

    subprocess.run(["git", "fetch", "origin"], cwd=DEMO_DIR)
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
        print(f"[Conflict Resolver] PR #{pr_number}: merge succeeded with no file conflicts.")
        subprocess.run(["git", "commit", "--no-edit"], cwd=DEMO_DIR)
        subprocess.run(["git", "push", "origin", branch_name], cwd=DEMO_DIR)
        return

    print(f"[Conflict Resolver] Conflicted files: {conflicted}")

    for file_path in conflicted:
        full_path = os.path.join(DEMO_DIR, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            content_with_markers = f.read()

        try:
            subprocess.Popen(["code", "-r", full_path], shell=True)
        except Exception as e:
            print(f"[Conflict Resolver] Couldn't auto-open in VS Code: {e}")
        time.sleep(1.5)

        print(f"[Conflict Resolver] Asking AI to resolve {file_path}...")
        resolved = resolve_file_conflict(file_path, content_with_markers)

        print(f"[Conflict Resolver] Typing out the resolved version of {file_path}...")
        open(full_path, "w", encoding="utf-8").close()
        with open(full_path, "w", encoding="utf-8") as f:
            for char in resolved:
                f.write(char)
                f.flush()
                time.sleep(0.004)

        print(f"[Conflict Resolver] Resolved {file_path}")
        subprocess.run(["git", "add", file_path], cwd=DEMO_DIR)

    print(f"[Conflict Resolver] Committing the merge resolution for PR #{pr_number}...")
    subprocess.run(
        ["git", "commit", "-m", f"resolve: merge conflicts in PR #{pr_number}"],
        cwd=DEMO_DIR,
    )

    print(f"[Conflict Resolver] Pushing resolution for PR #{pr_number}...")
    subprocess.run(["git", "push", "origin", branch_name], cwd=DEMO_DIR)

    print(f"[Conflict Resolver] Done with PR #{pr_number}! Checking it again...")
    time.sleep(2)
    os.system(f'start "" {chrome_path} "{pr_url}?t={int(time.time())}"')


def main():
    chrome_path = r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --profile-directory="Default"'
    gh_helper = GHHelper(GITHUB_TOKEN, GITHUB_REPO)

    if len(sys.argv) >= 2:
        pr_numbers = [int(sys.argv[1])]
    else:
        print("[Conflict Resolver] No PR number given — checking ALL open PRs...")
        open_prs = gh_helper.repo.get_pulls(state="open")
        pr_numbers = [pr.number for pr in open_prs]
        print(f"[Conflict Resolver] Found {len(pr_numbers)} open PR(s): {pr_numbers}")

    for pr_number in pr_numbers:
        print(f"\n{'='*50}")
        print(f"[Conflict Resolver] Processing PR #{pr_number}")
        print(f"{'='*50}")
        try:
            process_pr(gh_helper, pr_number, chrome_path)
        except Exception as e:
            print(f"[Conflict Resolver] Error processing PR #{pr_number}: {e}")
        time.sleep(1)

    print("\n[Conflict Resolver] All PRs checked!")


if __name__ == "__main__":
    main()