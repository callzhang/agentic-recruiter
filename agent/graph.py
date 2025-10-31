from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.prebuilt.interrupt import HumanInterrupt
from langgraph.runtime import Runtime
from langgraph.types import interrupt, Command
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage, AnyMessage
from typing import Dict, Literal, cast
# import json
from robust_json import loads
from agent.states import ManagerState, RecruiterState, ContextSchema, ManagerInputState, Candidate
from agent.tools import manager_tools, chat_tools, resume_tools, action_tools, _call_api
from agent.prompts import MANAGER_PROMPT, RECRUITER_PROMPT


# ----------------------------------------------------------------------------
# Recruiter Graph (separate, focused)
# ----------------------------------------------------------------------------
def recruiter_think(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Recruiter decides next action"""
    last_message = state.messages[-1]
    if last_message.type == 'tool' and last_message.name == 'finish_tool' and last_message.status == 'success':
        return Command(goto=END)
    new_state = {}
    # Add status message for recruiter thinking
    recruiter_model = init_chat_model(runtime.context.model).bind_tools(chat_tools+resume_tools+action_tools, parallel_tool_calls=False)
    agent_message = recruiter_model.invoke([SystemMessage(content=RECRUITER_PROMPT), *state.messages])
    new_state['messages'] = agent_message

    return new_state



def recruiter_think_router(state: RecruiterState, runtime: Runtime[ContextSchema]) -> Literal["execute_tools", "recruiter_think", END]:
    '''Route based on last message's tool calls'''
    last_message = state.messages[-1]
    if last_message.type == 'tool' and last_message.name == 'finish_tool' and last_message.status == 'success':
        return END
    elif last_message.type == 'ai' and last_message.tool_calls:
        return "execute_tools"
    elif last_message.type in ['ai', 'human', 'user', 'system']:
        # if last message is a AIMessage, return 'recruiter_think'
        return 'recruiter_think'
    else:
        return END

recruiter_builder = StateGraph(RecruiterState, context_schema=ContextSchema)

# Add nodes
recruiter_builder.add_node("recruiter_think", recruiter_think)
recruiter_builder.add_node("execute_tools", ToolNode(chat_tools+resume_tools+action_tools))
# Add edges
recruiter_builder.add_edge(START, "recruiter_think")
# recruiter_builder.add_conditional_edges("recruiter_think", tools_condition, {'tools': 'execute_tools', END: 'recruiter_think'})
recruiter_builder.add_conditional_edges('recruiter_think', recruiter_think_router)
recruiter_builder.add_edge("execute_tools", 'recruiter_think')
# build graph
recruiter_graph = recruiter_builder.compile()

# ----------------------------------------------------------------------------
# Manager Graph
# ----------------------------------------------------------------------------
def check_environment(state: ManagerInputState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Check browser status, web portal status, job status, persona status"""
    web_portal = runtime.context.web_portal
    
    # Check browser status
    while True:
        try:
            status = _call_api("GET", f"{web_portal}/status")
            # Create status message for chat interface
            # agent_message = AIMessage(content=f'浏览器成功链接，当前有{status["new_message_count"]}条新消息，{status["new_greet_count"]}条新问候。')
            # get jobs from web portal
            jobs = _call_api("GET", f"{web_portal}/web/jobs/api/list", timeout=runtime.context.timeout)['data']
            # get assistants from web portal
            assistants = _call_api("GET", f"{web_portal}/web/assistants/api/list")['data']
            assert len(jobs) > 0 and len(assistants) > 0, "Jobs or Assistants Status: Disconnected"
            system_message = SystemMessage(content=f'''浏览器成功链接，当前有{status["new_message_count"]}条新消息，{status["new_greet_count"]}条新问候。\n
            当前有{len(jobs)}个职位: {[j['position'] for j in jobs]}\n
            当前有{len(assistants)}个助手风格: {[a['name'] for a in assistants]}''')
            break
        except Exception as e:
            status_message = f"⚠️ Error: {str(e)}\n请确认浏览器和网页是否正常运行。"
            interrupt(status_message)
        
    
    return {
        "messages": system_message,
        'jobs': jobs,
        'assistants': assistants,
    }
        

def manager_plan(state: ManagerState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Manager decides what to do next"""
    # check if last message is a tool message, if so, extract the candidates from the tool call
    last_message = state.messages[-1]
    if last_message.type == 'tool' and last_message.status == 'success':
        if last_message.name == 'dispatch_candidate_tool':
            return
        elif last_message.name == 'finish_tool':
            return Command(goto=END)
    # otherwise, continue to think
    manager_model = init_chat_model(runtime.context.model).bind_tools(manager_tools, parallel_tool_calls=False)
    thinking_message = manager_model.invoke([SystemMessage(content=MANAGER_PROMPT), *state.messages])
    # Add status message for manager thinking
    agent_message = cast(AIMessage, thinking_message)
    return {
        "messages": agent_message,
    }


def dispatch_recruiter(state: ManagerState):
    # pick one candidate from the candidates list, and invoke the recruiter graph
    processed_chat_id_or_index = [candidate.chat_id or candidate.index for candidate in state.processed_candidates]
    # candidate = next(candidate for candidate in state.candidates if candidate.chat_id not in processed_chat_id_or_index and candidate.index not in processed_chat_id_or_index)

    if state.current_candidate.chat_id in processed_chat_id_or_index or \
    state.current_candidate.index in processed_chat_id_or_index:
        return "We have already processed this candidate"

    # prepare initial states for recruiter graph
    job_info = next((job for job in state.jobs if state.current_candidate.job_applied in job['position']), None)
    assistant_info = next((assistant for assistant in state.assistants if state.assistant_name in assistant['name']), None)
    system_message = SystemMessage(content=f'现在我们来处理候选人{state.current_candidate.name}，我们使用的助手风格信息如下：\n{assistant_info}')
    human_message = HumanMessage(content=f"这是我的描述：\n {state.current_candidate}")
    ai_message = AIMessage(content=f"你好，我们的岗位描述如下，现在开始对你进行评估: {job_info}")

    # invoke recruiter graph
    result: RecruiterState = recruiter_graph.invoke(input={
        'mode': state.current_candidate.mode,
        'candidate': state.current_candidate,
        'job_info': job_info,
        'assistant_info': assistant_info,
        'messages': [system_message, human_message, ai_message],
    })
    processed_candidate = result['candidate']
    report = result['messages'][-1].content
    recruiter_message = HumanMessage(f'我已经处理了候选人{processed_candidate.name}, 汇报如下：\n{report}')
    return {
        'processed_candidates': [processed_candidate],
        'messages': [recruiter_message],
    }


# Manager Graph
manager_builder = StateGraph(ManagerState, input_schema=ManagerInputState, context_schema=ContextSchema)

# Add nodes
manager_builder.add_node("check_env", check_environment)
manager_builder.add_node("manager_plan", manager_plan)
manager_builder.add_node("manager_tool_node", ToolNode(manager_tools))
manager_builder.add_node("dispatch_recruiter", dispatch_recruiter)

# Add edges
manager_builder.add_edge(START, "check_env")
manager_builder.add_edge("check_env", "manager_plan")
manager_builder.add_conditional_edges("manager_plan", tools_condition, {'tools': 'manager_tool_node', END: END})
manager_builder.add_edge("manager_tool_node", 'manager_plan')
manager_builder.add_edge("dispatch_recruiter", 'manager_plan')


# Compile graphs
manager_graph = manager_builder.compile()

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