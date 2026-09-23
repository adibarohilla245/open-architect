import json
from typing import Any, List

from pydantic import BaseModel
from openai import OpenAI
import streamlit as st

from src.helpers.github import GHHelper
from src.helpers.board import BoardHelper
from src.lib.terminal import colorize
from src.models import Ticket


class ArchitectAgentRequest(BaseModel):
    question: str
    history: Any

class CreateTicketsRequest(BaseModel):
    question: str
    history: Any

class CreateSubtasksRequest(BaseModel):
    question: str
    history: Any

class AskFollowupQuestionsRequest(BaseModel):
    question: str 
    history: Any

class ReferenceExistingCodeRequest(BaseModel):
    question: str
    history: Any


class Architect:
    def __init__(self, name, gh_helper: GHHelper, board_helper: BoardHelper):
        self.name = name
        self.gh_helper = gh_helper
        self.board_helper = board_helper
        self.log_name = colorize(f"[{self.name} the Architect]", bold=True, color="green")
        print(
            f"{self.log_name} Nice to meet you, I'm {self.name} the Architect! I'm here to help you break down your tasks into smaller tickets and create them for you! 🏗️🔨📝"
        )

    def run(self):
        st.title("Open Architect")

        if "messages" not in st.session_state:
            st.session_state.messages = []
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Hey! What new features would you like to add to your project " + str(self.gh_helper.repo.full_name) + " today?  I'll help you break it down to subtasks, figure out how to integrate with your existing code and then set my crew of SWE agents to get it built out for you!"
            })

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("What do you want to build today?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                architectureAgentReq = ArchitectAgentRequest(
                    question=prompt,
                    history=[msg["content"] for msg in st.session_state.messages],
                )
                response = self.compute_response(architectureAgentReq)
                st.write(response)

            st.session_state.messages.append({"role": "assistant", "content": response})

    def compute_response(self, architectAgentRequest: ArchitectAgentRequest):
        # Conversation history ki length ke hisaab se tool force karo
        history_len = len(architectAgentRequest.history)
        last_msg = architectAgentRequest.history[-1].lower() if architectAgentRequest.history else ""

        print(f"[Architect] History length: {history_len}, Last msg: {last_msg[:50]}")

        # STEP 1: Pehla message (user ka initial request) → reference_existing_code
        if history_len <= 2:
            forced_tool = "reference_existing_code"
            print(f"[Architect] STEP 1: Forcing tool -> {forced_tool}")

        # STEP 2: User ne confirm kiya (sure/yes/ok) → create_subtasks
        elif any(word in last_msg for word in ["sure", "yes", "ok", "okay", "go ahead", "break it down", "break down"]):
            # Agar abhi tak subtasks nahi bane → create_subtasks
            history_text = " ".join(architectAgentRequest.history).lower()
            if "break down of your task" not in history_text and "subtask" not in history_text:
                forced_tool = "create_subtasks"
                print(f"[Architect] STEP 2: Forcing tool -> {forced_tool}")
            # Agar subtasks ban chuke → create_tasks
            else:
                forced_tool = "create_tasks"
                print(f"[Architect] STEP 3: Forcing tool -> {forced_tool}")

        # STEP 3: User ne "create the tasks" bola → create_tasks
        elif any(word in last_msg for word in ["create the task", "create task", "create ticket", "create the ticket", "make the ticket"]):
            forced_tool = "create_tasks"
            print(f"[Architect] STEP 3: Forcing tool -> {forced_tool}")

        # Default: reference_existing_code
        else:
            forced_tool = "reference_existing_code"
            print(f"[Architect] DEFAULT: Forcing tool -> {forced_tool}")

        messages = [
            {"role": "system", "content": f"""You are a principal software engineer who breaks down tasks into tickets.

You have been given the following question: {architectAgentRequest.question}
Conversation so far: {architectAgentRequest.history}

Follow the conversation flow strictly."""},
            {"role": "user", "content": f"address the user's question: {architectAgentRequest.question}"}
        ]

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_subtasks",
                    "description": "Break the task down into detailed subtasks.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_tasks",
                    "description": "Create Trello tickets from the subtasks.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "reference_existing_code",
                    "description": "Analyze the codebase to understand how to build the requested feature.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            },
        ]

        openai_client = OpenAI()

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": forced_tool}},
        )
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        function_request_mapping = {
            "create_tasks": CreateTicketsRequest(
                question=architectAgentRequest.question,
                history=architectAgentRequest.history,
            ),
            "create_subtasks": CreateSubtasksRequest(
                question=architectAgentRequest.question,
                history=architectAgentRequest.history,
            ),
            "reference_existing_code": ReferenceExistingCodeRequest(
                question=architectAgentRequest.question,
                history=architectAgentRequest.history,
            )
        }

        if tool_calls:
            available_functions = {
                "create_tasks": self.create_tasks,
                "create_subtasks": self.create_subtasks,
                "reference_existing_code": self.reference_existing_code,
            }
            messages.append(response_message)

            results = []
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                print("Function called is: " + str(function_name))
                function_to_call = available_functions[function_name]
                function_args = function_request_mapping[function_name]

                result = function_to_call(function_args)
                results.append(result)

            if len(results) == 1:
                return results[0]
            return "\n\n---\n\n".join(str(r) for r in results)

        return response_message.content


    def reference_existing_code(self, referenceExistingCodeRequest: ReferenceExistingCodeRequest):
        codebase_dict = self.gh_helper.get_entire_codebase()
        codebase = codebase_dict.files

        try:
            questionPrompt = f"""Given the description of the project so far {referenceExistingCodeRequest.history} and the user's latest question {referenceExistingCodeRequest.question}, figure out which files in the codebase are most relevant for the user in order to best design a solution to the feature requests. You have this codebase to reference {codebase}.

            Your response should be something like:

            Going through your existing codebase, I would suggest that we build out _feature_ by modifying the following files _files_ and adding the following functionality to them _functionality description_.

            At the end, ASK: "Should I break this down into subtasks?"
            """
            openai_client = OpenAI()

            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior staff engineer, who analyzes codebases and creates execution plans.",
                    },
                    {"role": "user", "content": questionPrompt},
                ],
            )
            return response.choices[0].message.content

        except Exception as e:
            print("Failed to reference code with error " + str(e))
            return "Failed to reference code with error " + str(e)

    def create_tasks(self, createTicketsRequest: CreateTicketsRequest):
        """Create Trello tickets from the subtasks — DIRECTLY in To Do."""
        try:
            questionPrompt = f"""Given the following conversation history {createTicketsRequest.history}, generate a list of tasks in the following json format:
            {{
                "subtasks": [
                    {{
                        "title": "title of the ticket",
                        "description": "description of the ticket"
                    }}
                ]
            }}

            Take each subtask mentioned in the history and generate a title and description. Create a ticket for each one. Return ONLY valid JSON.
            """

            openai_client = OpenAI()
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior staff engineer. Return only valid JSON.",
                    },
                    {"role": "user", "content": questionPrompt},
                ],
                response_format={"type": "json_object"},
            )

            subtasks = response.choices[0].message.content
            print("The tasks created are: " + str(subtasks))
            subtask_json = json.loads(subtasks)["subtasks"]

            tickets = []
            for subtask in subtask_json:
                ticket = Ticket(title=subtask["title"], description=subtask["description"])
                tickets.append(ticket)

            # ✅ CHANGE: Ab cards DIRECTLY To Do mein banenge (Backlog mein nahi)
            createdTickets = self.board_helper.push_tickets_to_todo_and_assign(tickets)
            ticketMarkdown = generate_ticket_markdown(createdTickets)

            return "Great! I've just created the following tickets in **To Do** and assigned them to our agents:\n\n" + ticketMarkdown

        except Exception as e:
            print("Failed to create tasks with error " + str(e))
            return "Failed to create tasks with error " + str(e)

    def create_subtasks(self, createSubtasksRequest: CreateSubtasksRequest):
        """Break the task into subtasks (text output)."""
        try:
            questionPrompt = f"""Given the following conversation history {createSubtasksRequest.history} and the user's latest question {createSubtasksRequest.question}, please break the task down into smaller subtasks. Each subtask should include a title and a detailed description. Focus only on engineering tasks.

            Format:

            Here is a break down of your task into a list of more manageable subtasks -

            1. Title of the task
                Detailed description of the task
            2. Title of the task
                Detailed description of the task
            3. Title of the task
                Detailed description of the task

            At the end, ASK: "Should I create these as Trello tickets?"
            """

            openai_client = OpenAI()
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior staff engineer, who breaks down large tasks into small, granular subtasks.",
                    },
                    {"role": "user", "content": questionPrompt},
                ],
            )
            return response.choices[0].message.content

        except Exception as e:
            print("Failed to generate subtasks with error " + str(e))
            return "Failed to generate subtasks with error " + str(e)


def generate_ticket_markdown(tickets: List[Ticket]):
    markdown = ""
    for ticket in tickets:
        markdown += f"- **{ticket.title}**: {ticket.description}\n"
    return markdown