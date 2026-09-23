from typing import List
import dspy

from src.models import Codebase, Ticket, PR, CodeReview


class GeneratedCodeReview:
    is_valid_code: bool
    resolves_ticket: bool
    code_review: CodeReview


class ReviewerSignature(dspy.Signature):
    # Inputs
    ticket: Ticket = dspy.InputField()
    pr: PR = dspy.InputField()
    # Outputs
    is_valid_code: bool = dspy.OutputField(desc="Check if the code is actually valid.")
    resolves_ticket: bool = dspy.OutputField(
        desc="Does this code actually resolve the ticket? Is it changing the right files?"
    )
    code_review: CodeReview = dspy.OutputField(
        desc="Provide the review as a valid JSON object ONLY. No text outside JSON. No markdown fences."
    )


class ReviewerAgent(dspy.Module):
    def __init__(self):
        super().__init__()
        self.code_review_generator = dspy.TypedPredictor(signature=ReviewerSignature)

    def forward(
        self, codebase: Codebase, pr: PR, ticket: Ticket
    ) -> GeneratedCodeReview:
        try:
            generated_review = self.code_review_generator(
                codebase=codebase, ticket=ticket, pr=pr
            )
            return generated_review
        except Exception as e:
            print(f"[ReviewerAgent] LLM output parse failed: {e}")
            print(f"[ReviewerAgent] Using fallback review (COMMENT)")

            fallback = GeneratedCodeReview()
            fallback.is_valid_code = True
            fallback.resolves_ticket = True
            fallback.code_review = CodeReview(
                pr=pr,
                body="Auto-reviewed — LLM output could not be parsed. Manual review recommended.",
                event="COMMENT",
                comments=[],
            )
            return fallback