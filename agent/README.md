# Boss Zhipin Agent System

This directory contains the LangGraph-based agent system for automating Boss Zhipin recruitment workflows. The system consists of two main agents: a **Manager Agent** that orchestrates the overall process and a **Recruiter Agent** that handles individual candidate interactions.

## 🏗️ Architecture

### Core Components

- **`states.py`** - State schemas and data models
- **`tools.py`** - Agent tools that wrap FastAPI endpoints
- **`graph.py`** - LangGraph workflow definitions
- **`__init__.py`** - Package initialization

### Agent Types

1. **Manager Agent** (`manager_graph`)
   - Orchestrates the overall recruitment process
   - Manages job and assistant data
   - Coordinates candidate processing
   - Handles error recovery

2. **Recruiter Agent** (`recruiter_graph`)
   - Processes individual candidates
   - Executes recruitment actions
   - Manages candidate interactions
   - Handles tool execution

## 📊 State Management

### Context Schema
```python
class ContextSchema(TypedDict):
    browser_endpoint: str    # FastAPI server URL
    web_portal: str          # Web portal URL
    timeout: float          # Request timeout
    model: str              # LLM model name
    limit: int              # Processing limit
```

### Manager State
```python
class ManagerState(TypedDict):
    mode: Literal["recommend", "greet", "chat", "followup"]
    jobs: List[Dict]                    # Available jobs
    assistants: List[Dict]              # Available assistants
    candidates: List[Dict]              # Candidate list
    processed_candidates: List[Dict]    # Processed results
    messages: List[AnyMessage]          # Chat messages
    chat_id: Optional[str]              # Chat identifier
    recommend_index: Optional[int]      # Recommendation index
    limit: int                          # Processing limit
```

### Recruiter State
```python
class RecruiterState(TypedDict):
    candidate: Dict                     # Current candidate
    messages: List[AnyMessage]          # Chat messages
    tools_result: List[Dict]            # Tool execution results
```

## 🛠️ Available Tools

The agent system provides comprehensive tools for recruitment automation:

### Job Management
- `get_jobs_tool()` - Retrieve available jobs
- `get_job_details_tool()` - Get specific job details

### Assistant Management
- `get_assistants_tool()` - Retrieve available assistants
- `get_assistant_details_tool()` - Get specific assistant details

### Candidate Operations
- `get_candidates_tool()` - Search and retrieve candidates
- `get_candidate_details_tool()` - Get detailed candidate information
- `get_candidate_resume_tool()` - Retrieve candidate resume
- `get_candidate_contact_tool()` - Get candidate contact information

### Chat Operations
- `get_chat_list_tool()` - Retrieve chat conversations
- `get_chat_messages_tool()` - Get chat message history
- `send_chat_message_tool()` - Send messages to candidates
- `get_chat_status_tool()` - Check chat status

### Resume Management
- `get_resume_tool()` - Retrieve resume details
- `analyze_resume_tool()` - Analyze resume content
- `get_resume_analysis_tool()` - Get resume analysis results

### Recommendation System
- `get_recommendations_tool()` - Get candidate recommendations
- `get_recommendation_details_tool()` - Get specific recommendation details
- `accept_recommendation_tool()` - Accept candidate recommendations
- `reject_recommendation_tool()` - Reject candidate recommendations

### Automation Control
- `start_automation_tool()` - Start automation processes
- `stop_automation_tool()` - Stop automation processes
- `get_automation_status_tool()` - Check automation status

## 🚀 Usage

### Basic Setup

1. **Start the FastAPI service** (browser automation):
```bash
python start_service.py
```

2. **Configure the agent**:
```python
from agent.graph import manager_graph, recruiter_graph
from agent.states import ContextSchema, ManagerState

# Configure context
context = ContextSchema(
    browser_endpoint="http://localhost:8000",
    web_portal="http://localhost:8501",
    timeout=30.0,
    model="gpt-4",
    limit=10
)

# Initialize state
state = ManagerState(
    mode="recommend",
    jobs=[],
    assistants=[],
    candidates=[],
    processed_candidates=[],
    messages=[],
    chat_id=None,
    recommend_index=None,
    limit=10
)
```

### Running the Manager Agent

```python
# Run the manager workflow
result = manager_graph.invoke(state, config={"context": context})
```

### Running the Recruiter Agent

```python
# Run the recruiter workflow for a specific candidate
recruiter_state = RecruiterState(
    candidate=candidate_data,
    messages=[],
    tools_result=[]
)

result = recruiter_graph.invoke(recruiter_state, config={"context": context})
```

## 🔄 Workflow Flow

### Manager Workflow
1. **Environment Check** - Verify browser and service connectivity
2. **Manager Thinking** - Analyze requirements and plan actions
3. **Pool Candidates** - Retrieve and filter candidates
4. **Invoke Recruiter** - Process each candidate with recruiter agent
5. **Error Handling** - Manage failures and recovery

### Recruiter Workflow
1. **Recruiter Thinking** - Analyze candidate and plan actions
2. **Execute Tools** - Run recruitment tools and actions
3. **Result Processing** - Handle tool results and updates

## 🎯 Key Features

### Status Messages
The system provides real-time status updates through `AIMessage` objects:
- Browser connection status
- Job and assistant counts
- Processing progress
- Error notifications
- Tool execution results

### Error Handling
- **Browser Disconnection**: Shows "Fixed" button in LangSmith Studio
- **Tool Failures**: Graceful error handling with status messages
- **Recovery**: Automatic retry mechanisms for transient failures

### Human-in-the-Loop
- **Interrupts**: Pause execution for user input
- **Resume**: Continue after user intervention
- **Custom Messages**: Contextual status updates

## 🔧 Configuration

### Environment Variables
```bash
# FastAPI service
BROWSER_ENDPOINT=http://localhost:8000
WEB_PORTAL=http://localhost:8501

# LLM configuration
OPENAI_API_KEY=your_api_key
MODEL_NAME=gpt-4

# Processing limits
DEFAULT_LIMIT=10
REQUEST_TIMEOUT=30.0
```

### Runtime Context
The system uses `Runtime[ContextSchema]` to pass configuration to all tools and nodes, ensuring consistent access to:
- API endpoints
- Timeout settings
- Model configuration
- Processing limits

## 🧪 Testing

### Test Graph Compilation
```bash
python -m agent.test_graph
```

### Test Individual Components
```python
# Test state definitions
from agent.states import ContextSchema, ManagerState

# Test tool execution
from agent.tools import get_candidates_tool

# Test graph execution
from agent.graph import manager_graph
```

## 📚 Dependencies

- **LangGraph** - Workflow orchestration
- **LangChain Core** - Message handling and tools
- **FastAPI** - Browser automation service
- **Requests** - HTTP client for tool execution
- **Pydantic** - Data validation (optional)

## 🚨 Troubleshooting

### Common Issues

1. **Pydantic Schema Errors**
   - Ensure TypedDict definitions are correct
   - Remove `@dataclass` from TypedDict classes
   - Use proper field definitions

2. **Tool Execution Failures**
   - Verify FastAPI service is running
   - Check network connectivity
   - Validate API endpoints

3. **State Access Errors**
   - Use dictionary access (`state['field']`) instead of attribute access
   - Ensure all required fields are present
   - Check state initialization

### Debug Mode
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check state structure
print("Manager State:", state)
print("Context:", context)
```

## 🔄 Development Workflow

1. **Modify Tools** - Update `tools.py` for new capabilities
2. **Update States** - Modify `states.py` for new data structures
3. **Adjust Graphs** - Update `graph.py` for new workflows
4. **Test Changes** - Run tests to verify functionality
5. **Deploy** - Update the FastAPI service with new tools

## 📖 Related Documentation

- [LangGraph Comprehensive Notes](../../docs/langgraph_comprehensive_notes.md)
- [Technical Specifications](../../docs/technical.md)
- [Architecture Overview](../../docs/architecture.mermaid)
- [API Endpoints](../../docs/api/endpoints.md)

## 🤝 Contributing

When adding new tools or modifying the system:

1. **Follow the existing patterns** in `tools.py`
2. **Update state schemas** if new data is needed
3. **Test thoroughly** with the graph system
4. **Update this README** with new features
5. **Maintain backward compatibility** where possible

## 📝 Notes

- All tools are **synchronous** for compatibility with LangGraph
- State management uses **TypedDict** for type safety
- Error handling includes **human-in-the-loop** capabilities
- The system is designed for **production use** with proper error recovery
