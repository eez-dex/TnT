"""Shared Pydantic schemas used across the project."""

from pydantic import BaseModel, Field
from typing import List, Literal


class MCQQuestion(BaseModel):
    question: str = Field(description="The question text")
    options: List[str] = Field(description="Exactly 4 answer options")
    answer_index: int = Field(description="Index of the correct option (0-3)")
    explanation: str = Field(description="Detailed step-by-step explanation")
    topic: str = Field(description="The SSC CGL topic this question covers")
    difficulty: str = Field(description="Easy, Medium, or Hard")


class VerificationResult(BaseModel):
    independent_answer_index: int = Field(description="Index the verifier independently believes is correct")
    answer_matches: bool = Field(description="True if independent answer equals stated answer")
    explanation_is_correct: bool = Field(description="True if explanation justifies the answer")
    is_unambiguous: bool = Field(description="True if exactly one interpretation exists")
    has_four_distinct_options: bool = Field(description="True if all 4 options are distinct")
    quality_issues: List[str] = Field(description="Specific problems found")
    verdict: Literal["VALID", "INVALID"] = Field(description="Final verdict")