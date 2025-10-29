from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.prebuilt.interrupt import HumanInterrupt
from langgraph.runtime import Runtime
from langgraph.types import interrupt, Command
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage, AnyMessage
from typing import Dict, Literal, cast
import json
from robust_json import loads
from agent.states import ManagerState, RecruiterState, ContextSchema, ManagerInputState, Candidate
from agent.tools import manager_tools, chat_tools, resume_tools, _call_api
from agent.prompts import MANAGER_PROMPT, RECRUITER_PROMPT

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
            status_message = f"❌ Browser Status: Disconnected\n⚠️ Error: {str(e)}\n请确认浏览器和网页是否正常运行。"
            interrupt(status_message)
        
    
    return {
        "messages": system_message,
        'jobs': jobs,
        'assistants': assistants,
    }
        

def manager_plan(state: ManagerState, runtime: Runtime[ContextSchema]) -> ManagerState:
    """Manager decides what to do next"""
    # check if last message is a tool message, if so, extract the candidates from the tool call
    manager_model = init_chat_model(runtime.context.model).bind_tools(manager_tools, parallel_tool_calls=False)
    thinking_message = manager_model.invoke([SystemMessage(content=MANAGER_PROMPT), *state.messages])
    # Add status message for manager thinking
    agent_message = cast(AIMessage, thinking_message)
    return {
        "messages": agent_message,
    }


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
            new_state['candidates'] = [Candidate(**candidate) for candidate in json.loads(candidates)]
        elif last_message.name == 'invoke_recruiter_tool':
            tool_result = json.loads(last_message.content)
            candidate = tool_result.pop('candidate')
            Candidate(**candidate) # validate the candidate
            new_state['processed_candidates'] = [candidate]
    return new_state


# def manager_plan_router(state: ManagerState, runtime: Runtime[ContextSchema]) -> Literal["manager_tool_node", END]:
#     '''Route based on last message's tool calls'''
#     if state.messages[-1].tool_calls:
#         return "manager_tool_node"
#     else:
#         return END

# ----------------------------------------------------------------------------
# Recruiter Graph (separate, focused)
# ----------------------------------------------------------------------------
def recruiter_think(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Recruiter decides next action"""
    new_state = {}
    # Add status message for recruiter thinking
    recruiter_model = init_chat_model(runtime.context.model).bind_tools(chat_tools+resume_tools, parallel_tool_calls=False)
    agent_message = recruiter_model.invoke([SystemMessage(content=RECRUITER_PROMPT), *state.messages])
    new_state['messages'] = agent_message
    #TODO: additional processing for analysis json result
    try:
        analysis = loads(agent_message.content)
        if analysis:
            assert analysis['overall'] is not None
            new_state['analysis'] = analysis
    except Exception as e:
        print(e)

    return new_state


def tool_post_processing(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Postprocess tool results"""
    from src.global_logger import logger

    new_state = {}
    tool_call = state.messages[-2].tool_calls[0] # only one tool call is allowed from llm call
    tool_message = state.messages[-1]
    assert isinstance(tool_message, ToolMessage) or tool_message.type == "tool", "Last message is not a tool message"
    
    #  --------- Error Handling ---------
    if tool_message.status == "error":
        runtime.stream_writer(f"❌ Error: {tool_message.text}")
        return
    #  --------- Resume Tools ---------
    if tool_message.name == 'analyze_resume_tool':
        agent_message = AIMessage(content=f"以下是对于候选人的分析结果: {tool_message.content}")
        new_state.update({'messages': [agent_message], 'analysis': tool_message.content})
    elif tool_message.name == 'request_full_resume_tool':
        new_state['messages'] = [AIMessage(content=f"已向候选人请求完整简历")]
    elif tool_message.name == 'view_online_resume_tool':
        online_resume = tool_message.content
        new_state['messages'] = [HumanMessage(content=f"这是我的在线简历，请查收：\n {online_resume}")]
    elif tool_message.name == 'view_full_resume_tool':
        full_resume = tool_message.content
        new_state['messages'] = [HumanMessage(content=f"这是我的完整简历，请查收：\n {full_resume}")]
    #  --------- Chat Tools ---------
    elif tool_message.name == 'send_chat_message_tool':
        new_state['messages'] = [AIMessage(content=tool_call['args']['message'])]
    elif tool_message.name == 'get_chat_messages_tool':
        # convert candidate message to human message
        all_messages_in_boss = json.loads(tool_message.content)
        all_state_candidate_messagess = [m.content for m in state.messages if m.type == 'human']
        candidate_messages = []
        for message in all_messages_in_boss:
            if message['role'] == 'user' and message['content'] not in all_state_candidate_messagess:
                candidate_message = HumanMessage(content=message['content'])
                agent_message.append(candidate_message)
                logger.info(f"Inserted candidate message: {message}")
        new_state['messages'] = candidate_messages
    elif tool_message.name == 'greet_candidate_tool':
        assert tool_message.content == 'true', "Greet candidate tool should return True"
        ai_message = AIMessage(content=tool_call['args']['message'])
        new_state['messages'] = [ai_message]
    elif tool_message.name == 'check_resume_availability_tool':
        pass
    elif tool_message.name == 'request_contact_tool':
        new_state['messages'] = [AIMessage(content=f'已向候选人请求联系方式: {tool_call['args']['message']}')]
    else:
        raise ValueError(f"Unknown tool: {tool_message.name}")
    return new_state

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
manager_builder = StateGraph(ManagerState, input_schema=ManagerInputState, context_schema=ContextSchema)

# Add nodes
manager_builder.add_node("check_env", check_environment)
manager_builder.add_node("manager_plan", manager_plan)
manager_builder.add_node("manager_tool_node", ToolNode(manager_tools))
manager_builder.add_node("tool_post_processing", manager_tool_postprocessing)
# manager_builder.add_node("invoke_recruiter", invoke_recruiter)

# Add edges
manager_builder.add_edge(START, "check_env")
manager_builder.add_edge("check_env", "manager_plan")
manager_builder.add_conditional_edges("manager_plan", tools_condition, {'tools': 'manager_tool_node', END: END})
manager_builder.add_edge("manager_tool_node", "tool_post_processing")
manager_builder.add_edge("tool_post_processing", 'manager_plan')

# ----------------------------------------------------------------------------
# Recruiter Graph (separate)
# ----------------------------------------------------------------------------
recruiter_builder = StateGraph(RecruiterState, context_schema=ContextSchema)

# Add nodes
recruiter_builder.add_node("recruiter_think", recruiter_think)
recruiter_builder.add_node("execute_tools", ToolNode(chat_tools+resume_tools))
recruiter_builder.add_node("tool_post_processing", tool_post_processing)
# Add edges
recruiter_builder.add_edge(START, "recruiter_think")
recruiter_builder.add_conditional_edges("recruiter_think", tools_condition, {'tools': 'execute_tools', END: END})
recruiter_builder.add_edge("execute_tools", 'tool_post_processing')
recruiter_builder.add_edge("tool_post_processing", "recruiter_think")

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