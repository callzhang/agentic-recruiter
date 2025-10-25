# LangGraph Comprehensive Notes

## Table of Contents
1. [Core Concepts](#core-concepts)
2. [Thinking in LangGraph](#thinking-in-langgraph)
3. [Workflows and Agents](#workflows-and-agents)
4. [Graph API Overview](#graph-api-overview)
5. [State Management](#state-management)
6. [Nodes and Edges](#nodes-and-edges)
7. [Functional API](#functional-api)
8. [API Endpoints and SDK](#api-endpoints-and-sdk)
9. [Advanced Features](#advanced-features)
10. [Deployment and Production](#deployment-and-production)
11. [Best Practices](#best-practices)

## Core Concepts

### What is LangGraph?
LangGraph is a low-level orchestration framework for building, managing, and deploying long-running, stateful agents and workflows. It provides:

- **Durable execution**: Handles interruptions and resumes
- **Comprehensive memory**: Short-term and long-term state management
- **Human-in-the-loop**: Interactive workflows
- **Production-ready deployment**: Scalable and reliable

### Key Philosophy
LangGraph models agent workflows as **graphs** where:
- **State**: Shared data structure representing the current snapshot
- **Nodes**: Functions that encode agent logic and perform computations
- **Edges**: Functions that determine which node to execute next

### Execution Model
LangGraph uses a **message-passing system** inspired by Google's Pregel:
- Nodes run in discrete "super-steps"
- Nodes become active when they receive messages
- Execution terminates when all nodes are inactive and no messages are in transit
- Parallel nodes run in the same super-step
- Sequential nodes run in separate super-steps

## Thinking in LangGraph

### Mental Model
LangGraph encourages thinking about agent workflows as **graphs of computation** where:

1. **State is the single source of truth** - All nodes read from and write to the same state
2. **Nodes are pure functions** - They receive state, perform computation, and return state updates
3. **Edges define control flow** - They determine which node executes next based on current state
4. **Execution is message-driven** - Nodes become active when they receive messages

### Key Thinking Principles

#### 1. **State-Centric Design**
- Design your state schema first
- All nodes should be stateless functions that operate on state
- Use reducers to control how state updates are applied

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_task: str
    results: dict[str, Any]
    next_action: str
```

#### 2. **Node Responsibility**
- Each node should have a single, clear responsibility
- Nodes should be testable in isolation
- Avoid side effects in nodes (use tools for external interactions)

```python
def llm_call_node(state: AgentState) -> dict:
    """Node responsible for LLM reasoning and decision making"""
    # Pure function - no side effects
    response = llm.invoke(state["messages"])
    return {"messages": [response], "next_action": determine_next_action(response)}
```

#### 3. **Edge Logic**
- Edges should be simple routing functions
- Use conditional edges for dynamic routing
- Keep routing logic separate from business logic

```python
def should_continue(state: AgentState) -> str:
    """Simple routing logic"""
    last_message = state["messages"][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return "end"
```

#### 4. **Tool Integration**
- Tools are external capabilities that nodes can use
- Use `ToolNode` for tool execution
- Bind tools to LLMs for automatic tool calling

```python
from langgraph.prebuilt import ToolNode

# Create tool node
tool_node = ToolNode(tools)

# Bind tools to LLM
llm_with_tools = llm.bind_tools(tools)
```

### Design Patterns

#### 1. **ReAct Pattern**
Reasoning and Acting in a loop:
```python
# Agent reasons about what to do
def agent_node(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# Tools execute the action
def tool_node(state: AgentState):
    # Execute tools based on last message
    return {"messages": execute_tools(state["messages"][-1])}

# Conditional routing
def should_continue(state: AgentState):
    if state["messages"][-1].tool_calls:
        return "tools"
    return "end"
```

#### 2. **Multi-Agent Coordination**
Multiple specialized agents working together:
```python
def supervisor_node(state: AgentState):
    """Decides which agent to use"""
    return {"next_agent": determine_agent(state)}

def worker_agent(state: AgentState):
    """Specialized agent for specific tasks"""
    return {"result": process_task(state["task"])}
```

#### 3. **Human-in-the-Loop**
Interactive workflows with human input:
```python
def human_review_node(state: AgentState):
    """Pause for human input"""
    if needs_human_review(state):
        interrupt("Waiting for human review")
    return {"status": "approved"}
```

## Workflows and Agents

### Workflows vs Agents

#### **Workflows**
- **Purpose**: Orchestrate a sequence of steps to complete a task
- **Characteristics**: 
  - Linear or branching execution paths
  - Deterministic flow control
  - Focus on data processing and transformation
- **Use Cases**: Data pipelines, document processing, content generation

```python
# Example: Content Generation Workflow
def content_workflow(topic: str):
    # Step 1: Research
    research = research_node(topic)
    # Step 2: Outline
    outline = outline_node(research)
    # Step 3: Write
    content = write_node(outline)
    # Step 4: Review
    reviewed = review_node(content)
    return reviewed
```

#### **Agents**
- **Purpose**: Make decisions and take actions autonomously
- **Characteristics**:
  - Dynamic decision making
  - Tool usage and external interactions
  - Adaptive behavior based on context
- **Use Cases**: Customer service, research assistants, automation

```python
# Example: Research Agent
def research_agent(query: str):
    # Agent decides what to do next
    while not task_complete:
        action = decide_action(state)
        if action == "search":
            result = search_tool(query)
        elif action == "analyze":
            result = analyze_tool(data)
        # Continue until task is complete
    return final_result
```

### Building Agents with LangGraph

#### 1. **Tool-Calling Agents**
Agents that can use external tools:

```python
from langgraph.prebuilt import create_react_agent

# Create ReAct agent
agent = create_react_agent(
    llm=llm,
    tools=[search_tool, calculator_tool, email_tool],
    prompt="You are a helpful assistant that can use tools to help users."
)

# Use in workflow
def agent_workflow(user_input: str):
    result = agent.invoke({"messages": [HumanMessage(content=user_input)]})
    return result["messages"][-1].content
```

#### 2. **Multi-Agent Systems**
Multiple agents working together:

```python
# Supervisor agent
def supervisor(state: MultiAgentState):
    task = state["task"]
    if "research" in task:
        return {"next_agent": "researcher"}
    elif "analysis" in task:
        return {"next_agent": "analyst"}
    return {"next_agent": "generalist"}

# Specialist agents
def researcher_agent(state: MultiAgentState):
    return {"research": perform_research(state["task"])}

def analyst_agent(state: MultiAgentState):
    return {"analysis": perform_analysis(state["research"])}
```

#### 3. **Hierarchical Agent Teams**
Agents with different roles and responsibilities:

```python
# Team structure
class TeamState(TypedDict):
    task: str
    supervisor_decision: str
    worker_results: dict[str, Any]
    final_output: str

def supervisor_node(state: TeamState):
    """Decides which worker to assign"""
    return {"supervisor_decision": assign_worker(state["task"])}

def worker_node(state: TeamState):
    """Executes assigned task"""
    worker_type = state["supervisor_decision"]
    result = execute_worker_task(worker_type, state["task"])
    return {"worker_results": {worker_type: result}}
```

### Agent Patterns

#### 1. **ReAct (Reasoning + Acting)**
```python
def react_agent(state: AgentState):
    # Reason about what to do
    thought = llm.invoke(f"Think about: {state['task']}")
    
    # Act based on reasoning
    if "search" in thought.content:
        result = search_tool(state["query"])
    elif "calculate" in thought.content:
        result = calculator_tool(state["expression"])
    
    return {"messages": [thought, result]}
```

#### 2. **Tool-Using Agents**
```python
def tool_agent(state: AgentState):
    # LLM decides which tool to use
    response = llm_with_tools.invoke(state["messages"])
    
    if response.tool_calls:
        # Execute tools
        tool_results = []
        for tool_call in response.tool_calls:
            result = execute_tool(tool_call)
            tool_results.append(result)
        return {"messages": [response] + tool_results}
    
    return {"messages": [response]}
```

#### 3. **Conversational Agents**
```python
def conversational_agent(state: AgentState):
    # Maintain conversation context
    context = build_context(state["messages"])
    
    # Generate response
    response = llm.invoke([
        SystemMessage(content="You are a helpful assistant."),
        *context
    ])
    
    return {"messages": [response]}
```

### Agent State Management

#### 1. **Message History**
```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_task: str
    context: dict[str, Any]
    tools_used: list[str]
```

#### 2. **Task Tracking**
```python
class TaskState(TypedDict):
    task_id: str
    status: str  # "pending", "in_progress", "completed", "failed"
    steps_completed: list[str]
    current_step: str
    results: dict[str, Any]
```

#### 3. **Memory Management**
```python
class MemoryState(TypedDict):
    short_term: dict[str, Any]  # Current session
    long_term: dict[str, Any]   # Persistent across sessions
    working_memory: list[str]   # Current focus
```

### Agent Evaluation and Testing

#### 1. **Unit Testing Nodes**
```python
def test_agent_node():
    state = {"messages": [HumanMessage(content="Hello")]}
    result = agent_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
```

#### 2. **Integration Testing**
```python
def test_agent_workflow():
    graph = create_agent_workflow()
    result = graph.invoke({"messages": [HumanMessage(content="Test")]})
    assert result["messages"][-1].content is not None
```

#### 3. **Agent Performance Metrics**
```python
def evaluate_agent_performance():
    metrics = {
        "task_completion_rate": 0.95,
        "average_response_time": 2.3,
        "tool_usage_efficiency": 0.87,
        "user_satisfaction": 4.2
    }
    return metrics
```

## Graph API Overview

### StateGraph Class
The main graph class parameterized by a user-defined State object:

```python
from langgraph.graph import StateGraph

# Define state schema
class State(TypedDict):
    messages: list[str]
    result: str

# Create graph builder
builder = StateGraph(State)
```

### Compiling Graphs
**MUST** compile before use:

```python
graph = builder.compile()
```

Compilation provides:
- Basic structural checks (no orphaned nodes)
- Runtime argument specification (checkpointers, breakpoints)
- Graph optimization

### State Definition

#### Schema Types
1. **TypedDict** (recommended for performance)
2. **Pydantic BaseModel** (for validation)
3. **Dataclass** (for default values)

```python
from typing_extensions import TypedDict
from typing import Annotated
import operator

class State(TypedDict):
    messages: Annotated[list[str], operator.add]  # Custom reducer
    count: int  # Default reducer (last write wins)
```

#### Multiple Schemas
Support for input, output, and internal schemas:

```python
class InputState(TypedDict):
    user_input: str

class OutputState(TypedDict):
    graph_output: str

class OverallState(TypedDict):
    foo: str
    user_input: str
    graph_output: str

class PrivateState(TypedDict):
    bar: str

builder = StateGraph(
    OverallState,
    input_schema=InputState,
    output_schema=OutputState
)
```

#### Reducers
Control how state updates are applied:

```python
# Default reducer (last write wins)
count: int

# Custom reducer (append to list)
items: Annotated[list[str], operator.add]

# Messages reducer
messages: Annotated[list[AnyMessage], add_messages]
```

## State Management

### State Updates
Nodes return partial state updates:

```python
def my_node(state: State) -> dict:
    return {
        "messages": ["New message"],
        "count": state["count"] + 1
    }
```

### State Channels
- Nodes can read from any state channel
- Nodes can write to any state channel in the graph state
- Private channels for internal communication

### MessagesState
Pre-built state for message handling:

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]  # Custom fields
```

## Nodes and Edges

### Node Functions
Nodes receive state and return updates:

```python
def node_function(state: State) -> dict:
    # Process state
    return {"result": "processed"}
```

#### Node Arguments
```python
from langgraph.runtime import Runtime
from langchain_core.runnables import RunnableConfig

def node_with_runtime(state: State, runtime: Runtime[Context]):
    # Access runtime context
    pass

def node_with_config(state: State, config: RunnableConfig):
    # Access configuration
    pass
```

### Edge Types

#### Normal Edges
Fixed transitions between nodes:

```python
from langgraph.graph import START, END

builder.add_edge(START, "node_a")
builder.add_edge("node_a", "node_b")
builder.add_edge("node_b", END)
```

#### Conditional Edges
Dynamic routing based on state:

```python
def routing_function(state: State) -> str:
    if state["condition"]:
        return "node_b"
    else:
        return "node_c"

builder.add_conditional_edges(
    "node_a", 
    routing_function,
    {"node_b": "node_b", "node_c": "node_c"}
)
```

#### Entry Points
```python
# Fixed entry point
builder.add_edge(START, "node_a")

# Conditional entry point
builder.add_conditional_edges(START, routing_function)
```

### Special Nodes

#### START Node
Virtual node marking graph entry point:

```python
from langgraph.graph import START
builder.add_edge(START, "first_node")
```

#### END Node
Virtual node marking graph termination:

```python
from langgraph.graph import END
builder.add_edge("last_node", END)
```

### Advanced Control Flow

#### Send API
For map-reduce patterns and dynamic edges:

```python
from langgraph.types import Send

def continue_to_workers(state: State):
    return [Send("worker", {"task": task}) for task in state["tasks"]]

builder.add_conditional_edges("orchestrator", continue_to_workers)
```

#### Command API
Combine state updates and routing:

```python
from langgraph.graph import Command
from typing import Literal

def my_node(state: State) -> Command[Literal["next_node"]]:
    return Command(
        update={"foo": "bar"},
        goto="next_node"
    )
```

#### Cross-Graph Navigation
Navigate from subgraph to parent:

```python
def my_node(state: State) -> Command[Literal["parent_node"]]:
    return Command(
        update={"shared_key": "value"},
        goto="parent_node",
        graph=Command.PARENT
    )
```

## Functional API

### Core Decorators

#### @entrypoint
Marks workflow entry points:

```python
from langgraph.func import entrypoint

@entrypoint()
def my_workflow(inputs: dict) -> dict:
    return {"result": "processed"}
```

#### @task
Defines asynchronous work units:

```python
from langgraph.func import task

@task
def my_task(input_data: str) -> str:
    # Perform work
    return "result"
```

### Injectable Parameters
Entrypoints can request dependencies:

```python
@entrypoint(checkpointer=checkpointer, store=store)
def my_workflow(
    inputs: dict,
    *,
    previous: Any = None,  # Short-term memory
    store: BaseStore,       # Long-term memory
    writer: StreamWriter,   # Streaming
    config: RunnableConfig # Configuration
) -> dict:
    pass
```

### Task Execution
Tasks return future-like objects:

```python
@entrypoint()
def workflow(inputs: dict):
    # Sequential execution
    result1 = my_task(inputs["data"]).result()
    result2 = another_task(result1).result()
    return result2

    # Parallel execution
    future1 = my_task(inputs["data1"])
    future2 = my_task(inputs["data2"])
    return combine(future1.result(), future2.result())
```

### Streaming
Send custom messages during execution:

```python
from langgraph.config import get_stream_writer

@entrypoint()
def workflow(inputs: dict):
    writer = get_stream_writer()
    writer("Started processing")
    # ... work ...
    writer("Completed processing")
    return result
```

## API Endpoints and SDK

### LangGraph Cloud API

#### Core Endpoints
- **Assistants**: Manage graph instances with configurations
- **Threads**: Conversation sessions
- **Runs**: Graph executions
- **Crons**: Scheduled executions

#### Authentication
```python
# Environment variables
CONTROL_PLANE_HOST = os.getenv("CONTROL_PLANE_HOST")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")

# Headers
headers = {
    "X-Api-Key": LANGSMITH_API_KEY,
    "Content-Type": "application/json"
}
```

#### Client SDK
```python
from langgraph_sdk import get_client

# Initialize client
client = get_client()  # Local
client = get_client(url="https://api.langchain.ai")  # Remote

# Create thread
thread = await client.threads.create()

# Start streaming run
async for chunk in client.runs.stream(
    thread_id,
    assistant_id,
    input={"messages": [{"role": "human", "content": "Hello"}]},
    stream_mode="updates"
):
    print(chunk)
```

### REST API Examples

#### Health Check
```bash
curl http://localhost:8123/ok
# Response: {"ok": true}
```

#### Create Thread
```bash
curl --request POST \
  --url <DEPLOYMENT_URL>/threads \
  --header 'Content-Type: application/json' \
  --data '{}'
```

#### Stream Run
```bash
curl --request POST \
  --url <DEPLOYMENT_URL>/threads/<THREAD_ID>/runs/stream \
  --header 'Content-Type: application/json' \
  --header 'x-api-key: <API_KEY>' \
  --data '{
    "assistant_id": "agent",
    "input": {"topic": "ice cream"},
    "stream_mode": "updates"
  }'
```

### Stream Modes
- **updates**: State changes
- **events**: All operational events
- **values**: Final state values

## Advanced Features

### Persistence and Memory

#### Checkpointers
Short-term memory for conversation threads:

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

# Use with thread_id
config = {"configurable": {"thread_id": "thread_123"}}
result = graph.invoke(inputs, config)
```

#### Stores
Long-term memory for cross-thread persistence:

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

@entrypoint(store=store)
def workflow(inputs: dict, store: BaseStore):
    # Access store for long-term memory
    pass
```

### Human-in-the-Loop

#### Interrupts
Pause execution for user input:

```python
from langgraph.graph import interrupt

def human_review_node(state: State):
    # Process state
    if needs_human_input(state):
        interrupt("Waiting for human review")
    return {"status": "approved"}
```

#### Resume with Command
```python
# Resume with user input
Command(resume="User input")
```

### Node Caching
Optimize performance with caching:

```python
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy

# Configure cache
cache = InMemoryCache()
graph = builder.compile(cache=cache)

# Node with cache policy
builder.add_node(
    "expensive_node", 
    expensive_function,
    cache_policy=CachePolicy(ttl=300)  # 5 minutes
)
```

### Runtime Context
Pass external dependencies:

```python
@dataclass
class ContextSchema:
    llm_provider: str = "openai"
    api_key: str = ""

graph = StateGraph(State, context_schema=ContextSchema)

def node_with_context(state: State, runtime: Runtime[ContextSchema]):
    llm = get_llm(runtime.context.llm_provider)
    # Use llm...
```

### Recursion Limits
Control execution depth:

```python
graph.invoke(
    inputs, 
    config={"recursion_limit": 10}
)
```

## Deployment and Production

### Local Development
```bash
# Start local server
langgraph up

# Or with Docker
docker run -p 8123:8123 langgraph/langgraph
```

### Configuration
```json
{
  "graphs": {
    "my_agent": {
      "path": "./my_agent/agent.py:graph",
      "description": "A description of what the agent does"
    }
  },
  "env": ".env"
}
```

### Environment Variables
```bash
# Required
LANGSMITH_API_KEY=your_key
OPENAI_API_KEY=your_key

# Optional
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_PROJECT=my_project
```

### Health Monitoring
```bash
# Check API health
curl http://localhost:8123/ok

# Expected response
{"ok": true}
```

## Best Practices

### Graph Design
1. **Keep nodes focused**: Single responsibility
2. **Use meaningful names**: Clear node and edge names
3. **Handle errors gracefully**: Proper error handling in nodes
4. **Test thoroughly**: Unit and integration tests

### State Management
1. **Use appropriate reducers**: Choose right aggregation strategy
2. **Minimize state size**: Only store necessary data
3. **Use private channels**: For internal communication
4. **Validate state**: Use Pydantic for complex validation

### Performance
1. **Use caching**: For expensive computations
2. **Parallel execution**: Use tasks for independent work
3. **Streaming**: For real-time updates
4. **Resource limits**: Set appropriate recursion limits

### Error Handling
1. **Graceful failures**: Handle exceptions in nodes
2. **Retry logic**: For transient failures
3. **Logging**: Comprehensive logging
4. **Monitoring**: Track execution metrics

### Security
1. **API keys**: Use environment variables
2. **Input validation**: Validate all inputs
3. **Access control**: Implement proper authentication
4. **Rate limiting**: Prevent abuse

## Common Patterns

### ReAct Agent
```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    tools=[tool1, tool2],
    prompt="You are a helpful assistant"
)
```

### Map-Reduce
```python
def orchestrate(state: State):
    return [Send("worker", {"task": task}) for task in state["tasks"]]

def worker(state: WorkerState):
    return {"result": process_task(state["task"])}

def aggregate(state: State):
    return {"final_result": combine_results(state["results"])}
```

### Human-in-the-Loop
```python
def review_node(state: State):
    if needs_review(state):
        interrupt("Human review required")
    return {"status": "approved"}

# Resume with user input
Command(resume="Approved by human")
```

This comprehensive guide covers all major aspects of LangGraph, from basic concepts to advanced deployment patterns. Use this as a reference for building robust, stateful agent workflows.
