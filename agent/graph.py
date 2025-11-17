from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.prebuilt.interrupt import HumanInterrupt
# from langchain.agents.interrupt import HumanInterrupt
from langgraph.runtime import Runtime
from langgraph.types import interrupt, Command
from langgraph.utils.config import patch_configurable
# from langgraph.store.postgres import PostgresStore # By default, LangSmith Deployments automatically create PostgreSQL and Redis instances for you. You can also configure external PostgreSQL and Redis services using environment variables like POSTGRES_URI_CUSTOM and REDIS_URI_CUSTOM.
from langchain_core.runnables import RunnableConfig
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, messages_to_dict, messages_from_dict
from typing import Dict, Literal, cast
# import json
from agent.states import ManagerState, RecruiterState, ContextSchema, ManagerInputState, Candidate
from agent.tools import manager_tools, chat_tools, resume_tools, action_tools, _call_api
from agent.prompts import MANAGER_PROMPT, RECRUITER_PROMPT
import os
from agent.tools import current_timestr

version = os.environ["__VERSION__"].replace('.', '_')
NAME_SPACE = ('RECRUITER_AGENT', version)
# ----------------------------------------------------------------------------
# Recruiter Graph (separate, focused)
# ----------------------------------------------------------------------------
def recruiter_think(state: RecruiterState, runtime: Runtime[ContextSchema]) -> RecruiterState:
    """Recruiter decides next action"""
    assert runtime.store is not None, "Store is required"
    assert runtime.context is not None, "Context is required"

    # Add status message for recruiter thinking
    model = init_chat_model(
        model=runtime.context.model, 
        tags = ['recruiter_graph']
    )
    recruiter_model = model.bind_tools(chat_tools+resume_tools+action_tools, parallel_tool_calls=False)
    agent_message = recruiter_model.invoke([SystemMessage(content=RECRUITER_PROMPT), *state.messages])

    return {
        'messages': agent_message,
    }


#TODO: remove this after testing
def recruiter_think_router(state: RecruiterState, runtime: Runtime[ContextSchema]) -> Literal["execute_tools", "recruiter_think", END]:
    '''Route based on last message's tool calls'''
    last_message = state.messages[-1]
    if last_message.type == 'tool' and last_message.name == 'finish_tool' and last_message.status == 'success':
        return END # we should not reach here, but just in case
    elif last_message.type == 'ai' and last_message.tool_calls:
        return "execute_tools"
    elif last_message.type in ['ai', 'human', 'user', 'system']:
        # if last message is a AIMessage, return 'recruiter_think'
        return 'recruiter_think'
    else:
        return END

def recruiter_tool_router(state: RecruiterState) -> Literal["recruiter_think", END]:
    last_message = next((m for m in state.messages[::-1] if m.type == 'tool'), None)
    assert last_message, "missing last tool message"
    if last_message.status != 'success':
        return 'recruiter_think'
    elif last_message.name == 'finish_tool':
        return END
    else:
        return 'recruiter_think'

recruiter_builder = StateGraph(RecruiterState, context_schema=ContextSchema)

# Add nodes
recruiter_builder.add_node("recruiter_think", recruiter_think)
recruiter_builder.add_node("execute_tools", ToolNode(chat_tools+resume_tools+action_tools))
recruiter_builder.set_entry_point("recruiter_think")
# Add edges
# recruiter_builder.add_conditional_edges("recruiter_think", tools_condition, {'tools': 'execute_tools', END: 'recruiter_think'})
recruiter_builder.add_conditional_edges('recruiter_think', tools_condition, {'tools': 'execute_tools', END: 'recruiter_think'})
recruiter_builder.add_conditional_edges('execute_tools', recruiter_tool_router)
# build graph
recruiter_graph = recruiter_builder.compile()

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
            jobs_response = _call_api("GET", f"{web_portal}/jobs/api/list", timeout=runtime.context.timeout)
            # jobs endpoint returns {"success": True, "data": [...]}
            jobs = jobs_response.get('data', jobs_response) if isinstance(jobs_response, dict) else jobs_response
            # get assistants from web portal
            assistants_response = _call_api("GET", f"{web_portal}/assistant/list")
            # assistants endpoint returns a list directly, not wrapped in dict
            assistants = assistants_response if isinstance(assistants_response, list) else (assistants_response.get('data', []) if isinstance(assistants_response, dict) else [])
            assert len(jobs) > 0 and len(assistants) > 0, "Jobs or Assistants Status: Disconnected"
            names = [candidate.name for candidate in state.processed_candidates]
            system_message = SystemMessage(content=f'''浏览器成功链接，当前有{status["new_message_count"]}条新消息，{status["new_greet_count"]}条新问候。\n
            当前有{len(jobs)}个职位: {[j['position'] for j in jobs]}\n
            当前有{len(assistants)}个助手风格: {[a['name'] for a in assistants]}\n
            当前有{len(names)}个已处理候选人: {names}\n
            如果你想修改助手风格或者添加职位，请访问 {web_portal}/web 进行修改''')
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
    # otherwise, continue to think
    model = init_chat_model(
        model=runtime.context.model, 
        tags = ['manager_graph']
    )
    manager_model = model.bind_tools(manager_tools, parallel_tool_calls=False)
    thinking_message = manager_model.invoke([SystemMessage(MANAGER_PROMPT), *state.messages])
    # Add status message for manager thinking
    agent_message = cast(AIMessage, thinking_message)
    return {
        "messages": agent_message,
    }


def dispatch_recruiter(state: ManagerState, runtime: Runtime[ContextSchema], config: RunnableConfig):
    # check if the candidate is already processed
    candidate = state.current_candidate
    past_execution = runtime.store.get(NAME_SPACE, candidate.chat_id) if candidate.chat_id else None
    state_input = past_execution.value.get('state') if past_execution else None
    # prepare initial/resumed states for recruiter graph
    if not state_input:
        # pick one candidate from the candidates list, and invoke the recruiter graph
        processed_chat_id_or_index = [candidate.chat_id or candidate.index for candidate in state.processed_candidates]
        # candidate = next(candidate for candidate in state.candidates if candidate.chat_id not in processed_chat_id_or_index and candidate.index not in processed_chat_id_or_index)
        if state.current_candidate.chat_id in processed_chat_id_or_index or \
        state.current_candidate.index in processed_chat_id_or_index:
            return {
                "messages": [SystemMessage(content="已处理过该候选人，请勿重复提交。")]
            }
        job_info = next((job for job in state.jobs if state.current_candidate.job_applied in job['position']), None)
        assistant_info = next((assistant for assistant in state.assistants if state.assistant_name in assistant['name']), None)
        system_message = SystemMessage(content=f'现在我们来处理候选人{state.current_candidate.name}，现在时间是：{current_timestr()}，我们使用的沟通风格如下：\n{assistant_info}，我们的岗位要求(job requirements)如下：\n{job_info}')
        human_message = HumanMessage(content=f"这是我的描述：\n {state.current_candidate}")
        state_input = {
            'candidate': state.current_candidate,
            'messages': [system_message, human_message]
        }
    else:
        # resuming old messages
        state_input['messages'] = messages_from_dict(state_input['messages'])
        resume_message = f"我们继续分析一下候选人{state.current_candidate.name}，时间：{current_timestr()}."
        state_input['messages'].append(SystemMessage(content=resume_message))
        state_input['candidate'] = Candidate(**state_input['candidate'])
    
    # invoke recruiter graph
    result = recruiter_graph.invoke(
        input=state_input,
    )

    # save the result to the store
    processed_candidate = result['candidate']
    result['candidate'] = result['candidate'].model_dump()
    result['messages'] = messages_to_dict(result['messages'])
    runtime.store.put(NAME_SPACE, candidate.chat_id, result)
    # extract the resume message
    report = result['messages'][-1]['data']['content']
    recruiter_message = HumanMessage(f'这是招聘顾问对候选人的report：\n{report}')

    return {
        'processed_candidates': [processed_candidate],
        'messages': [recruiter_message],
    }

def tool_router(state: ManagerState) -> Literal["dispatch_recruiter", "manager_plan", END]:
    last_message = state.messages[-1]
    assert last_message.type == 'tool', "Last message must be a tool message"
    if last_message.status != 'success':
        return 'manager_plan'
    elif last_message.name == 'dispatch_candidate_tool':
        return 'dispatch_recruiter'
    elif last_message.name == 'finish_tool':
        return END
    else:
        return 'manager_plan'

# Manager Graph
manager_builder = StateGraph(ManagerState, input_schema=ManagerInputState, context_schema=ContextSchema)

# Add nodes
manager_builder.add_node("check_env", check_environment)
manager_builder.add_node("manager_plan", manager_plan)
manager_builder.add_node("manager_tool_node", ToolNode(manager_tools))
manager_builder.add_node("dispatch_recruiter", dispatch_recruiter)
manager_builder.set_entry_point("check_env")
# Add edges
manager_builder.add_edge("check_env", "manager_plan")
manager_builder.add_conditional_edges("manager_plan", tools_condition, {'tools': 'manager_tool_node', END: END})
manager_builder.add_conditional_edges("manager_tool_node", tool_router)
manager_builder.add_edge("dispatch_recruiter", 'manager_plan')


# Compile graphs
manager_graph = manager_builder.compile()

if __name__ == "__main__":
    # test the manager graph
    for message, metadata in manager_graph.stream(
        input={
            'messages': [HumanMessage(content="我需要处理候选人张三，请帮我分析一下他是否符合我们的岗位要求")],
        },
        context=ContextSchema(
            web_portal="http://localhost:5001",
            timeout=30.0,
            model="gpt-5-mini",
            limit=10
        )
    ):
        print(message)
        print(metadata)