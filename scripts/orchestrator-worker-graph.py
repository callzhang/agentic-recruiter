from langchain.chat_models import init_chat_model
from langgraph.types import Send
from typing_extensions import TypedDict, Annotated
import operator
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from IPython.display import Image
from pydantic import BaseModel, Field
from typing import Annotated, List


# Schema for structured output to use in planning
class Section(BaseModel):
    name: str = Field(
        description="Name for this section of the report.",
    )
    description: str = Field(
        description="Brief overview of the main topics and concepts to be covered in this section.",
    )


class Sections(BaseModel):
    sections: List[Section] = Field(
        description="Sections of the report.",
    )

llm = init_chat_model("gpt-4o-mini")    

# Augment the LLM with schema for structured output
planner = llm.with_structured_output(Sections)


# Graph state
class State(TypedDict):
    topic: str  # Report topic
    sections: list[Section]  # List of report sections
    completed_sections: Annotated[
        list, operator.add
    ]  # All workers write to this key in parallel
    final_report: str  # Final report


# Worker state
class WorkerState(TypedDict):
    section: Section
    completed_sections: Annotated[list, operator.add]


# Nodes
def orchestrator(state: State):
    """Orchestrator that generates a plan for the report"""

    # Generate queries
    report_sections = planner.invoke(
        [
            SystemMessage(content="Generate a plan for the report."),
            HumanMessage(content=f"Here is the report topic: {state['topic']}"),
        ]
    )

    return {"sections": report_sections.sections}


def llm_call(state: WorkerState):
    """Worker writes a section of the report"""

    # Generate section
    section = llm.invoke(
        [
            SystemMessage(
                content="Write a report section following the provided name and description. Include no preamble for each section. Use markdown formatting."
            ),
            HumanMessage(
                content=f"Here is the section name: {state['section'].name} and description: {state['section'].description}"
            ),
        ]
    )

    # Write the updated section to completed sections
    return {"completed_sections": [section.content]}


def synthesizer(state: State):
    """Synthesize full report from sections"""

    # List of completed sections
    completed_sections = state["completed_sections"]

    # Format completed section to str to use as context for final sections
    completed_report_sections = "\n\n---\n\n".join(completed_sections)

    return {"final_report": completed_report_sections}


# Conditional edge function to create llm_call workers that each write a section of the report
def assign_workers(state: State):
    """Assign a worker to each section in the plan"""

    # Kick off section writing in parallel via Send() API
    return [Send("llm_call", {"section": s}) for s in state["sections"]]


# Build workflow
orchestrator_worker_builder = StateGraph(State)

# Add the nodes
orchestrator_worker_builder.add_node("orchestrator", orchestrator)
orchestrator_worker_builder.add_node("llm_call", llm_call)
orchestrator_worker_builder.add_node("synthesizer", synthesizer)

# Add edges to connect nodes
orchestrator_worker_builder.add_edge(START, "orchestrator")
orchestrator_worker_builder.add_conditional_edges(
    "orchestrator", assign_workers, ["llm_call"]
)
orchestrator_worker_builder.add_edge("llm_call", "synthesizer")
orchestrator_worker_builder.add_edge("synthesizer", END)

# Compile the workflow
orchestrator_worker = orchestrator_worker_builder.compile()

# Show the workflow
mermaid_png = orchestrator_worker.get_graph().draw_mermaid_png()
with open("orchestrator_worker_graph.png", "wb") as f:
    f.write(mermaid_png)

# Stream execution step by step
print("🚀 Starting orchestrator-worker graph execution...")
print("=" * 60)

final_state = None
step_count = 0

for chunk in orchestrator_worker.stream({"topic": "Create a report on LLM scaling laws"}):
    step_count += 1
    print(f"\n📋 Step {step_count}:")
    print("-" * 40)
    
    for node_name, node_output in chunk.items():
        print(f"🔧 Node: {node_name}")
        
        if node_name == "orchestrator":
            sections = node_output.get("sections", [])
            print(f"   📝 Generated {len(sections)} report sections:")
            for i, section in enumerate(sections, 1):
                print(f"      {i}. {section.name}")
                print(f"         {section.description[:100]}...")
                
        elif node_name == "llm_call":
            completed_sections = node_output.get("completed_sections", [])
            if completed_sections:
                section_content = completed_sections[0]
                print(f"   ✍️  Generated section ({len(section_content)} chars)")
                print(f"      Preview: {section_content[:150]}...")
                
        elif node_name == "synthesizer":
            final_report = node_output.get("final_report", "")
            print(f"   🔄 Synthesized final report ({len(final_report)} chars)")
            print(f"      Preview: {final_report[:150]}...")
            
        # Store the final state
        if node_output:
            final_state = node_output

print("\n" + "=" * 60)
print("✅ Execution completed!")

# Write the final report to disk
if final_state and "final_report" in final_state:
    with open("llm_scaling_laws_report.md", "w", encoding="utf-8") as f:
        f.write(final_state["final_report"])
    
    print(f"📄 Report saved to 'llm_scaling_laws_report.md'")
    print(f"📊 Report length: {len(final_state['final_report'])} characters")
else:
    print("⚠️  No final report generated")