'''
This is a minimal example of a subgraph runtime.
It demonstrates how to use a subgraph runtime to create a simple workflow.
also we can use time travel to resume an earlier state of the workflow by providing:

- checkpoint_id
- checkpoint_ns
- thread_id

if the three are not provided, it will start a new workflow.

'''
import operator
from typing import Literal
from dataclasses import dataclass
from typing import Annotated
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import StateGraph, END
from langgraph.runtime import Runtime
from typing_extensions import TypedDict
from langgraph.store.memory import InMemoryStore
from langgraph.utils.config import patch_configurable
from langgraph.checkpoint.memory import InMemorySaver

NAME_SPACE = ('subgraph', '1')
@dataclass
class Context:
    username: str

class State(TypedDict):
    foo: str
    subgraph_count: int

class SubState(TypedDict):
    bar: str
    subgraph_count: Annotated[int, operator.add] = 0


# Subgraph

def subgraph_node_1(state: SubState, runtime: Runtime[Context], config: RunnableConfig):
    assert runtime.store is not None, "Store is required"
    assert runtime.context is not None, "Context is required"
    print(f'subgraph_node_1->subgraph_count: {state["subgraph_count"]}')
    print(f'subgraph_node_1->thread_id: {config["configurable"].get("thread_id")}')
    item = runtime.store.get(NAME_SPACE, runtime.context.username)
    configurable = item.value if item else {}
    checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns")
    checkpoint_id = config.get("configurable", {}).get("checkpoint_id") # checkpoint_id is None inside the node
    configurable.update({'checkpoint_ns': checkpoint_ns})
    # runtime.store.put(NAME_SPACE, runtime.context.username, configurable)
    return {
        'bar': 'subgraph: nice to meet you ' + runtime.context.username,
        'subgraph_count': 1
    }

def subgraph_node_2(state: SubState, runtime: Runtime[Context], config: RunnableConfig):
    # does nothing
    print(f'subgraph_node_2->subgraph_count: {state["subgraph_count"]}')


subgraph_builder = StateGraph(SubState, context_schema=Context)
subgraph_builder.add_node(subgraph_node_1)
subgraph_builder.add_node(subgraph_node_2)
subgraph_builder.add_edge('subgraph_node_1', 'subgraph_node_2')
subgraph_builder.set_entry_point('subgraph_node_1')

# Parent graph

def main_node(state: State, runtime: Runtime[Context]):
    return {'foo': 'hello ' + runtime.context.username}

def invoke_subgraph(state: State, runtime: Runtime[Context], config: RunnableConfig):
    item = runtime.store.get(NAME_SPACE, runtime.context.username)
    if item:
        checkpoint_id = item.value['checkpoint_id']
        checkpoint_ns = item.value.get('checkpoint_ns')
        thread_id = item.value['thread_id']
        configurable = {'checkpoint_id': checkpoint_id, 'checkpoint_ns': checkpoint_ns, 'thread_id': thread_id}
        print(f'configurable found: {configurable}')
        new_config = patch_configurable(config, configurable)
        result = subgraph.invoke(
            input={},
            # input=Command(goto='subgraph_node_1'), 
            context=runtime.context,
            config=new_config,
            # durability='sync'
        )
    else:
        print('no config found, running with initial state')
        result = subgraph.invoke(input=state)

    print(f'subgraph invocation result: {result}')
    
    # get the checkpoint id
    snap = subgraph.get_state({'configurable': {'thread_id': runtime.context.username}})
    snaps = list(subgraph.get_state_history({'configurable': {'thread_id': runtime.context.username}}))
    cp_id = snap.config["configurable"].get("checkpoint_id")
    cp_ns = snap.config["configurable"].get("checkpoint_ns")
    thread_id = snap.config["configurable"].get("thread_id")
    # update the checkpoint id 
    item = runtime.store.get(NAME_SPACE, runtime.context.username)
    configurable = {'checkpoint_id': cp_id, 'thread_id': thread_id}
    if item:
        c = item.value
        c.update(configurable)
        runtime.store.put(NAME_SPACE, runtime.context.username, c)
    else:
        runtime.store.put(NAME_SPACE, runtime.context.username, configurable)

    return result


def router(state: State) -> Literal['invoke_subgraph', END]:
    if state.get('subgraph_count') < 3:
        return 'invoke_subgraph'
    else:
        return END

builder = StateGraph(State, context_schema=Context)
builder.add_node(main_node)
builder.add_node(invoke_subgraph)
builder.set_entry_point('main_node')
builder.add_edge('main_node', 'invoke_subgraph')
builder.add_conditional_edges('invoke_subgraph', router)


# running it as
checkpointer = InMemorySaver()
store = InMemoryStore()
if __name__ == "__main__":
    graph = builder.compile(store=store, checkpointer=checkpointer)
    subgraph = subgraph_builder.compile(checkpointer=checkpointer, store=store)
    username = 'Alice'
    for msg in graph.stream(
        input={'foo': 'world'}, 
        config={'configurable': {'thread_id': username}},
        context=Context(username=username), 
        subgraph=True, 
        stream_mode='updates',
    ):
        print(msg)
else:
    print(f'running from CLI...({__name__})')
    graph = builder.compile()
    subgraph = subgraph_builder.compile(checkpointer=checkpointer)