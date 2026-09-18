import json
import os
import time

from src.helpers.github import GHHelper
from src.helpers.trello import TrelloHelper
from src.agents.intern.processors import generate_code_change
from src.lib.terminal import colorize

TRACK_FILE = "backlog_comment_tracker.json"
POLL_EVERY = 15  # seconds


def load_tracker():
    if os.path.exists(TRACK_FILE):
        with open(TRACK_FILE, "r") as f:
            return json.load(f)
    return {}


def save_tracker(data):
    with open(TRACK_FILE, "w") as f:
        json.dump(data, f, indent=2)


class BacklogWatcher:
    def __init__(self, trello_helper: TrelloHelper, gh_helper: GHHelper):
        self.trello_helper = trello_helper
        self.gh_helper = gh_helper
        self.tracker = load_tracker()
        self.log_name = colorize("[backlog watcher]", bold=True, color="blue")

    def check_ticket(self, ticket):
        comments = self.trello_helper.get_comments(ticket.id)
        seen_count = self.tracker.get(ticket.id, 0)

        if len(comments) <= seen_count:
            return  # no new comments

        new_comments = comments[seen_count:]
        self.tracker[ticket.id] = len(comments)
        save_tracker(self.tracker)

        # Ignore comments the agent itself posted, to avoid loops
        new_comments = [
            c for c in new_comments
            if "PR ready for review" not in c.get("data", {}).get("text", "")
        ]
        if not new_comments:
            return

        feedback_text = "\n".join(
            c["data"]["text"] for c in new_comments
        )

        print(f"{self.log_name} New comment on '{ticket.title}': {feedback_text[:80]}...")

        # Build an augmented ticket: original description + new instruction
        ticket.description = f"{ticket.description}\n\n[New request from comment]: {feedback_text}"

        new_files, body = generate_code_change(
            ticket, self.gh_helper.get_entire_codebase()
        )

        branch_name = f"{ticket.id}_{ticket.title.lower().replace(' ', '_')}_update"
        pr_url = self.gh_helper.push_changes(
            branch_name=branch_name,
            pr_title=f"resolve: {ticket.title}",
            pr_body=body,
            new_files=new_files,
            ticket_id=ticket.id,
            author_id=ticket.assignee_id,
            commit_message=f"resolve: {ticket.title}",
        )

        self.trello_helper.add_comment(ticket.id, f"PR ready for review: {pr_url}")
        self.trello_helper.move_to_waiting_for_review(ticket_id=ticket.id)
        self.trello_helper.mark_due_complete(ticket.id)

        print(f"{self.log_name} Resolved and moved to Ready for Review.")

    def run(self):
        print(f"{self.log_name} Watching Backlog for new comments...")
        while True:
            tickets = self.trello_helper.get_backlog_tickets()
            for ticket in tickets:
                try:
                    self.check_ticket(ticket)
                except Exception as e:
                    print(f"{self.log_name} Error processing {ticket.id}: {e}")
            time.sleep(POLL_EVERY)