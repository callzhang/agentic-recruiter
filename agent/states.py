# Improved State Definition
from typing import Dict, List, Optional, Annotated, TypedDict, Literal
import json
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage
import operator
import uuid
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from yaml import load, Loader
from agent.prompts import STAGES, ACTIONS, ACTION_PROMPTS

with open('config/jobs.yaml', 'r') as f:
    jobs = load(f, Loader=Loader)



def add_candidates(left: list[Dict], right: list[Dict]) -> list[Dict]:
    """Add candidates to the list, and deduplicate"""
    from src.global_logger import logger
    if not isinstance(left, list):
        left = [left]
    if not isinstance(right, list):
        right = [right]
    all_candidates = left + right
    seen = set()
    result = []
    for d in all_candidates:
        # JSON with sorted keys ensures identical content → identical string
        key = json.dumps(d, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(d)
        else:
            logger.warning(f"Candidate {d} already exists in the list")
    return result
    

class ContextSchema(BaseModel):
    """Context schema for the manager and recruiter agents"""
    web_portal: str = Field(description="Server address to interact with boss直聘 local browser service, and get the jobs and assistants", default="http://127.0.0.1:5001")
    timeout: float = Field(description="The timeout for the API calls", default=30.0)
    model: str = Field(description="The model to use for the API calls", default="gpt-5-mini")
    limit: int = Field(description="The limit for the number of candidates to process", default=10)

class ManagerState(BaseModel):
    """Manager agent state to manage the recruitment process"""
    mode: Literal["recommend", "greet", "chat", "followup"] = Field(description="The mode to look for candidates", default="recommend")
    jobs: List[Dict] = Field(description="All available jobs from the web portal", default=[])
    messages: Annotated[list[AnyMessage], add_messages] = Field(description="The messages to process", default=[])
    assistants: List[Dict] = Field(description="All available assistant personas from the web portal", default=[])
    candidates: Annotated[list[Dict], add_candidates] = Field(description="All candidates fetched from the jobs", default=[])
    processed_candidates: Annotated[list[Dict], operator.add] = Field(description="All candidates that have been processed", default=[])

class RecruiterState(BaseModel):
    """Recruiter agent state to process a single candidate"""
    mode: Literal["recommend", "greet", "chat", "followup"] = Field(description="The mode to look for candidates", default="recommend")
    stage: Literal["GREET", "PASS", "CHAT", "SEEK", "CONTACT"] = Field(description="The stage of the candidate", default="GREET")
    candidate: Dict = Field(description="The candidate to process")
    job_info: Dict = Field(description="The job description to analyze the candidate")
    assistant_info: Dict = Field(description="The assistant persona to analyze the candidate")
    analysis: Dict = Field(description="The analysis of the candidate", default={})
    messages: Annotated[list[AnyMessage], add_messages] = Field(description="The messages to process with the candidate", default=[])
