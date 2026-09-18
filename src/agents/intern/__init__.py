from random import choice
import time
from threading import Thread
from typing import List

from src.lib.terminal import colorize
from src.agents.intern.processors import better_code_change, generate_code_change
from src.models import Ticket
from src.helpers.github import GHHelper
from src.helpers.board import BoardHelper
import os
import subprocess
import webbrowser
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
REFRESH_EVERY = 5
PROCESS_EVERY = 5
MAX_REFRESH_CYCLES_WITHOUT_WORK = 50000
MAX_PROCESS_CYCLES_WITHOUT_WORK = 10000


def determine_commit_type(title: str) -> str:
    title_lower = title.lower()
    if any(word in title_lower for word in ["fix", "bug", "error", "crash"]):
        return "fix"
    elif any(word in title_lower for word in ["refactor", "restructure", "reorganize", "clean up"]):
        return "refactor"
    elif any(word in title_lower for word in ["optimize", "performance", "speed up", "faster"]):
        return "perf"
    elif any(word in title_lower for word in ["test", "testing"]):
        return "test"
    elif any(word in title_lower for word in ["docs", "documentation", "readme", "comment"]):
        return "docs"
    else:
        return "feat"


def generate_commit_message(ticket_title: str, body: str, commit_type: str) -> str:
    try:
        prompt = f"""Write a single-line, professional git commit message summary (no more than 12 words, no period at the end) for this change.
Do not include the type prefix (like "feat:" or "fix:") — just the description part.

Ticket: {ticket_title}
What was actually implemented: {body[:800]}

Return ONLY the summary line, nothing else."""

        response = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
        )
        summary = response.choices[0].message.content.strip().strip('"').strip("'")
        return f"{commit_type}: {summary}"
    except Exception as e:
        print(f"Couldn't generate commit message via AI, falling back: {e}")
        return f"{commit_type}: {ticket_title}"


def run_git_visible(cmd, cwd):
    print(f"    $ {' '.join(cmd)}")
    time.sleep(0.5)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    time.sleep(0.8)
    return result


def run_commit_push_in_new_terminal(demo_dir, branch_name, commit_message):
    safe_commit_message = commit_message.replace('"', "'")
    sentinel_path = os.path.join(demo_dir, f"_git_done_{branch_name}.tmp")
    bat_path = os.path.join(os.getcwd(), f"_git_steps_{branch_name}.bat")

    if os.path.exists(sentinel_path):
        os.remove(sentinel_path)

    bat_content = f'''@echo off
cd /d "{demo_dir}"
echo    $ git add .
git add .
echo    $ git status
git status
echo    $ git commit -m "{safe_commit_message}"
git commit -m "{safe_commit_message}"
echo    $ git push -u origin {branch_name}
git push -u origin {branch_name}
echo. > "{sentinel_path}"
'''
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(
        f'start "Alex - oa-demo-repo" cmd /k "{bat_path}"',
        shell=True,
    )

    waited = 0
    while not os.path.exists(sentinel_path) and waited < 60:
        time.sleep(1)
        waited += 1

    if os.path.exists(sentinel_path):
        os.remove(sentinel_path)
    if os.path.exists(bat_path):
        os.remove(bat_path)


class Intern:
    def __init__(self, name, gh_helper: GHHelper, board_helper: BoardHelper):
        self.name = name
        self.id = choice(board_helper.get_intern_list())
        self.ticket_todo_list: List[Ticket] = []
        self.seen_ticket_ids = set()
        self.pr_backlog = []
        self.gh_helper = gh_helper
        self.board_helper = board_helper
        self.fetch_thread = Thread(target=self.refresh_loop)
        self.process_thread = Thread(target=self.process_loop)
        self.log_name = colorize(f"[{self.name} the intern]", bold=True, color="red")
        print(
            f"{self.log_name} Hey! I'm {self.name} the software dev intern 😁, excited to start working! I'll look for tickets to code!"
        )

    def refresh_ticket_todo_list(self):
        next_tickets = [
            t
            for t in self.board_helper.get_tickets_todo_list()
            if t not in self.ticket_todo_list and t.id not in self.seen_ticket_ids
        ]
        for t in next_tickets:
            self.seen_ticket_ids.add(t.id)
        self.ticket_todo_list.extend(next_tickets)
        return len(next_tickets) != 0

    def refresh_pr_backlog(self):
        return False  # Not implemented yet
        print(f"[INTERN {self.name}] Looking on GitHub for reviewed PRs")
        next_prs = [
            pr
            for pr in self.gh_helper.list_open_prs()
            if pr not in self.pr_backlog and pr.assignee_id == self.id
        ]
        self.pr_backlog.extend(next_prs)
        return len(next_prs) != 0

    def process_pr(self):
        pr = self.pr_backlog.pop(0)
        self.board_helper.move_to_wip(pr.ticket_id)
        comment = self.gh_helper.get_comments(pr)
        code_change = generate_code_change("", comment)
        self.gh_helper.push_changes(code_change, pr.ticket_id, pr.assignee_id)
        print(f"[{self.log_name}] Moving card to waiting for review")
        self.board_helper.move_to_waiting_for_review(pr.ticket_id)

    def process_ticket(self):
        ticket = self.ticket_todo_list.pop(0)

        print(f'{self.log_name} Starting to work on ticket "{ticket.title:.30}..."')

        # --- DEMO: open card, set due date (visible), move to WIP (visible), then open project folder ---
        chrome_path = r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --profile-directory="Default"'
        card_url = f"https://trello.com/c/{ticket.id}"
        board_url = f"https://trello.com/b/{self.board_helper.board_id}"
        demo_dir = r"C:\Users\Expertizo\oa-demo-repo"

        print(f"{self.log_name} Opening my task card...")
        os.system(f'start "" {chrome_path} "{card_url}"')
        time.sleep(3)

        print(f"{self.log_name} Setting a due date for this ticket...")
        self.board_helper.set_due_date(ticket.id)
        time.sleep(1)
        os.system(f'start "" {chrome_path} "{card_url}?t={int(time.time())}"')
        time.sleep(2)

        print(f"{self.log_name} Moving the ticket to WIP...")
        self.board_helper.move_to_wip(ticket.id)
        time.sleep(1)
        os.system(f'start "" {chrome_path} "{board_url}?t={int(time.time())}"')
        time.sleep(2.5)

        print(f"{self.log_name} Opening my project folder...")
        subprocess.Popen(["code", "-n", demo_dir], shell=True)
        time.sleep(3)
        # --- END DEMO ---

        new_files, body = generate_code_change(
            ticket, self.gh_helper.get_entire_codebase()
        )

        commit_type = determine_commit_type(ticket.title)
        conventional_message = generate_commit_message(ticket.title, body, commit_type)

        raw_branch = f"{ticket.id}_{ticket.title.lower().replace(' ', '_')}"
        branch_name = re.sub(r"[^a-zA-Z0-9_\-]", "", raw_branch)

        # --- Clean up and create the branch FIRST, before writing any new code ---
        print(f"{self.log_name} Preparing a clean branch off main...")
        run_git_visible(["git", "checkout", "--", "."], demo_dir)
        run_git_visible(["git", "clean", "-fd"], demo_dir)
        run_git_visible(["git", "checkout", "main"], demo_dir)
        run_git_visible(["git", "checkout", "--", "."], demo_dir)
        run_git_visible(["git", "pull", "origin", "main"], demo_dir)
        run_git_visible(["git", "checkout", "-B", branch_name], demo_dir)

        # --- DEMO: open file, then "type" the code live in VS Code ---
        for file_path, content in new_files.items():
            local_path = os.path.join(demo_dir, file_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            open(local_path, "w", encoding="utf-8").close()
            try:
                subprocess.Popen(["code", "-r", local_path], shell=True)
            except Exception as e:
                print(f"{self.log_name} Couldn't auto-open in VS Code: {e}")
            time.sleep(1.5)

            print(f"{self.log_name} Typing out {file_path}...")
            with open(local_path, "w", encoding="utf-8") as f:
                for char in content:
                    f.write(char)
                    f.flush()
                    time.sleep(0.008)
        # --- END DEMO ---

        # --- Now commit and push in a dedicated terminal, AFTER files are written ---
        print(f"{self.log_name} Opening a terminal in my project folder to commit and push...")
        run_commit_push_in_new_terminal(demo_dir, branch_name, conventional_message)

        print(f"{self.log_name} Opening a pull request...")
        pr_url = self.gh_helper.create_pr_for_branch(
            branch_name=branch_name,
            pr_title=conventional_message,
            pr_body=body,
            ticket_id=ticket.id,
            author_id=ticket.assignee_id,
        )

        print(f"{self.log_name} Adding PR link as a comment on the ticket...")
        self.board_helper.add_comment(ticket.id, f"PR ready for review: {pr_url}")

        self.board_helper.move_to_waiting_for_review(ticket_id=ticket.id)

        print(f"{self.log_name} Marking my task as complete...")
        self.board_helper.mark_due_complete(ticket.id)

        print(f"{self.log_name} PR Created! Feel free to review it!")

        # --- DEMO: open the actual PR page in Chrome ---
        time.sleep(2)
        os.system(f'start "" {chrome_path} "{pr_url}"')
        # --- END DEMO ---

    def refresh_loop(self):
        cycles_without_work = 0
        while True:
            if not self.refresh_pr_backlog() and not self.refresh_ticket_todo_list():
                cycles_without_work += 1
                if cycles_without_work == MAX_REFRESH_CYCLES_WITHOUT_WORK:
                    print(f"{self.log_name} No more work to do, bye bye!")
                    break
            else:
                cycles_without_work = 0
            time.sleep(REFRESH_EVERY)
        self.process_thread.join()
        self.fetch_thread.join()

    def process_loop(self):
        number_of_attempts = 0
        while True:
            if len(self.pr_backlog) > 0:
                self.process_pr()
                number_of_attempts = 0
            elif len(self.ticket_todo_list) > 0:
                self.process_ticket()
                number_of_attempts = 0
            else:
                number_of_attempts += 1
                if number_of_attempts == MAX_PROCESS_CYCLES_WITHOUT_WORK:
                    print(f"{self.log_name} No more work to do, bye bye!")
                    break
                time.sleep(10)

        self.fetch_thread.join()
        self.process_thread.join()

    def run(self):
        self.fetch_thread.start()
        self.process_thread.start()