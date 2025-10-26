from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.interrupt import HumanInterrupt
from langgraph.runtime import Runtime
from langgraph.types import interrupt, Command
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from typing import Dict, Literal, cast
import json
import ast
from agent.states import ManagerState, RecruiterState, ContextSchema
from agent.tools import manager_tools, chat_tools, resume_tools, manager_tool_node, recruiter_tool_node
from agent.prompts import MANAGER_PROMPT

# ----------------------------------------------------------------------------
# Manager Graph
# ----------------------------------------------------------------------------
def check_environment(state: ManagerState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Check browser status, web portal status, job status, persona status"""
    web_portal = runtime.context.web_portal
    
    # Check browser status
    while True:
        try:
            status = _call_api("GET", f"{web_portal}/status")
            # Create status message for chat interface
            # agent_message = AIMessage(content=f'浏览器成功链接，当前有{status["new_message_count"]}条新消息，{status["new_greet_count"]}条新问候。')
            # get jobs from web portal
            jobs = _call_api("GET", f"{web_portal}/web/jobs/api/list")['data']
            # get assistants from web portal
            assistants = _call_api("GET", f"{web_portal}/web/assistants/api/list")['data']
            assert len(jobs) > 0 and len(assistants) > 0, "Jobs or Assistants Status: Disconnected"
            agent_message = AIMessage(content=f'''浏览器成功链接，当前有{status["new_message_count"]}条新消息，{status["new_greet_count"]}条新问候。\n
            当前有{len(jobs)}个职位: {[j['position'] for j in jobs]}\n
            当前有{len(assistants)}个助手: {[a['name'] for a in assistants]}''')
            break
        except Exception as e:
            status_message = f"❌ Browser Status: Disconnected\n⚠️ Error: {str(e)}\n请确认浏览器和网页是否正常运行。"
            interrupt(status_message)
        
    
    return {
        "messages": [agent_message],
        "jobs": jobs,
        "assistants": assistants
    }
        

def manager_plan(state: ManagerState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Manager decides what to do next"""
    # check if last message is a tool message, if so, extract the candidates from the tool call
    manager_model = init_chat_model(runtime.context.model).bind_tools(manager_tools, parallel_tool_calls=False)
    thinking_message = manager_model.invoke([SystemMessage(content=MANAGER_PROMPT), *state.messages])
    # Add status message for manager thinking
    agent_message = cast(AIMessage, thinking_message)
    return agent_message


def manager_tool_postprocessing(state: ManagerState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Postprocess tool results"""
    new_state = {}
    last_message = state.messages[-1]
    if isinstance(last_message, ToolMessage) or last_message.type == "tool":
        if last_message.status == "error":
            error_message = AIMessage(content=f"❌ Error: {last_message.text}")
            state.messages.append(error_message)
        elif last_message.name == 'get_candidates_tool':
            candidates = last_message.content
            # Use ast.literal_eval instead of json.loads to handle Python dict strings
            new_state['candidates'] = json.loads(candidates)
        elif last_message.name == 'invoke_recruiter_tool':
            tool_result = json.loads(last_message.content)
            new_state['processed_candidates'] = [tool_result['candidate']]
    return new_state


def manager_plan_router(state: ManagerState, runtime: Runtime[ContextSchema]) -> Literal["manager_tool_node", END]:
    '''Route based on last message's tool calls'''
    if state.messages[-1].tool_calls:
        return "manager_tool_node"
    else:
        return END

# ----------------------------------------------------------------------------
# Recruiter Graph (separate, focused)
# ----------------------------------------------------------------------------
def recruiter_think(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Recruiter decides next action"""
    # Add status message for recruiter thinking
    recruiter_model = init_chat_model(runtime.context.model).bind_tools(chat_tools+resume_tools, parallel_tool_calls=False)

    thinking_message = "🧠 Recruiter: Analyzing candidate and deciding next action..."
    agent_message = AIMessage(content=thinking_message)
    return {"messages": [agent_message]}


def tool_postprocessing(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Postprocess tool results"""
    last_message = state.messages[-1]
    assert isinstance(last_message, ToolMessage) or last_message.type == "tool", "Last message is not a tool message"
    if last_message.name == 'analyze_resume_tool':
        agent_message = AIMessage(content=f"以下是对于候选人的分析结果: {last_message.content}")
    return {
        'messages': agent_message
    }

def recruiter_think_router(state: RecruiterState, runtime: Runtime[ContextSchema]) -> Literal["execute_tools", END]:
    '''Route based on last message's tool calls'''
    if state.messages[-1].tool_calls:
        return "execute_tools"
    else:
        return END


# ----------------------------------------------------------------------------
# Tool Postprocessing
# ----------------------------------------------------------------------------
# Manager Graph
manager_builder = StateGraph(ManagerState, context_schema=ContextSchema)

# Add nodes
manager_builder.add_node("check_env", check_environment)
manager_builder.add_node("manager_plan", manager_plan)
manager_builder.add_node("manager_tool_node", manager_tool_node)
manager_builder.add_node("tool_postprocessing", manager_tool_postprocessing)
# manager_builder.add_node("invoke_recruiter", invoke_recruiter)

# Add edges
manager_builder.add_edge(START, "check_env")
manager_builder.add_edge("check_env", "manager_plan")
manager_builder.add_conditional_edges("manager_plan", manager_plan_router)
manager_builder.add_edge("manager_tool_node", "tool_postprocessing")
manager_builder.add_edge("tool_postprocessing", 'manager_plan')

# ----------------------------------------------------------------------------
# Recruiter Graph (separate)
# ----------------------------------------------------------------------------
recruiter_builder = StateGraph(RecruiterState, context_schema=ContextSchema)

# Add nodes
recruiter_builder.add_node("recruiter_think", recruiter_think)
recruiter_builder.add_node("execute_tools", recruiter_tool_node)
recruiter_builder.add_node("tool_postprocessing", tool_postprocessing)
# Add edges
recruiter_builder.add_edge(START, "recruiter_think")
recruiter_builder.add_conditional_edges("recruiter_think", recruiter_think_router)
recruiter_builder.add_edge("execute_tools", 'tool_postprocessing')
recruiter_builder.add_edge("tool_postprocessing", "recruiter_think")

# Compile graphs
manager_graph = manager_builder.compile()
recruiter_graph = recruiter_builder.compile()

# Example usage function
# def run_manager_with_status(initial_state: ManagerState, config: Dict) -> ManagerState:
#     """Run manager graph and return results with status messages"""
#     try:
#         result = manager_graph.invoke(initial_state, config)
#         return result
#     except Exception as e:
#         error_message = f"❌ Graph Execution Error: {str(e)}"
#         agent_message = AIMessage(content=error_message)
#         return {"messages": [agent_message], "error": str(e)}

# def run_recruiter_with_status(initial_state: RecruiterState, config: Dict) -> RecruiterState:
#     """Run recruiter graph and return results with status messages"""
#     try:
#         result = recruiter_graph.invoke(initial_state, config)
#         return result
#     except Exception as e:
#         error_message = f"❌ Graph Execution Error: {str(e)}"
#         agent_message = AIMessage(content=error_message)
#         return {"messages": [agent_message], "error": str(e)}