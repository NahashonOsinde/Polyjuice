Use typed dictionary whenever possible and appropriate
Use BaseMessage, ToolMessage, SystemMessage etc
Use Annotated, Sequnce from the typing library whenever possible and appropriate
For the tools that are used by the agent, implement them using decorators i.e., @tool
Use ToolNodes (Check how tools are implemented in LangGraph, and check whether it is necessary to implement them this way in our Agentic function)
Implement using exeptions wherever appropriate and necessary
RAG implementation to a knowledge base
Use docling to efficiently extract information if the knowledge base has pdf files in it
Use PYPDFLoader to load pdf files if they exist

===================================================================================================================
# TAMARA AI AGENT (LangGraph Specifications)

## Overview
This document outlines the coding standards, patterns, libraries, and architectural guidelines to be observed in developing AI agents based on LangGraph. These specifications should be used as context for building agent-based applications with RAG functionality, memory implementation, and tool integration.

## Core Libraries and Dependencies

### Primary Dependencies
```python
# Core LangGraph and LangChain
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# RAG and Vector Storage
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import 
from langchain_community.document_loaders import TextLoader
from langchain.docstore.document import Document
from langchain_chroma import Chroma

# Type Hints and Utilities
from typing import TypedDict, Annotated, Sequence, List, Union, Optional
from dotenv import load_dotenv
import os
```

### Environment Setup
- Always use `load_dotenv()` at the beginning of scripts
- Store API keys and sensitive data in `.env` files
- Use Python 3.12.6 with virtual environment management (I prefer conda)

## State Management Patterns

### AgentState Definition
```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # Additional fields as needed
    name: str
    age: str
    skills: Optional[List[str]]
    result: str
```

### Key Principles
1. **Always use TypedDict** for state definitions
2. **Use Annotated with add_messages** for message sequences to enable automatic state merging
3. **Include Optional types** for fields that may not always be present
4. **Keep state flat** - avoid nested dictionaries when possible

## Agent Architecture Patterns

### 1. Basic Agent Structure
```python
def agent_node(state: AgentState) -> AgentState:
    """Agent node that processes user input and generates responses"""
    system_prompt = SystemMessage(content="Your system instructions here")
    
    # Process messages
    response = llm.invoke([system_prompt] + state["messages"])
    
    return {"messages": [response]}
```

### 2. Tool-Enabled Agents
```python
@tool
def custom_tool(param: str) -> str:
    """Tool description for the LLM"""
    # Tool implementation
    return result

tools = [custom_tool]
llm = ChatOpenAI(model="gpt-4o").bind_tools(tools)

def should_continue(state: AgentState) -> str:
    """Determine if agent should continue or end"""
    last_message = state["messages"][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "continue"
    return "end"
```

### 3. Conditional Flow Control
```python
graph.add_conditional_edges(
    "agent_node",
    should_continue,
    {
        "continue": "tools_node",
        "end": END
    }
)
```

## RAG Implementation Patterns

### 1. Document Processing
```python
# Load documents
# .pdf
pdf_loader = PyPDFLoader(pdf_path)
pages = pdf_loader.load()
# .txt
txt_loader = TextLoader(str(txt_file))
txt_docs = loader.load()

# Chunk documents
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
)
pages_split = text_splitter.split_documents(pages)

# Create vector store
vectorstore = Chroma.from_documents(
    documents=pages_split,
    embedding=embeddings,
    persist_directory=persist_directory,
    collection_name=collection_name
)
```

### 2. Retrieval Tool
```python
@tool
def retriever_tool(query: str) -> str:
    """Tool for retrieving relevant documents"""
    docs = retriever.invoke(query)
    
    if not docs:
        return "No relevant information found."
    
    results = []
    for i, doc in enumerate(docs):
        results.append(f"Document {i+1}:\n{doc.page_content}")
    
    return "\n\n".join(results)
```

### 3. RAG Agent Integration
```python
def take_action(state: AgentState) -> AgentState:
    """Execute tool calls from LLM response"""
    tool_calls = state['messages'][-1].tool_calls
    results = []
    
    for t in tool_calls:
        if t['name'] in tools_dict:
            result = tools_dict[t['name']].invoke(t['args'].get('query', ''))
            results.append(ToolMessage(
                tool_call_id=t['id'], 
                name=t['name'], 
                content=str(result)
            ))
    
    return {'messages': results}
```

## Memory Implementation Patterns

### 1. Conversation History
```python
class AgentState(TypedDict):
    messages: List[Union[HumanMessage, AIMessage]]

def process(state: AgentState) -> AgentState:
    response = llm.invoke(state["messages"])
    state["messages"].append(AIMessage(content=response.content))
    return state
```

### 2. Persistent Memory
```python
# Save conversation to file
with open("logging.txt", "w") as file:
    file.write("Conversation Log:\n")
    for message in conversation_history:
        if isinstance(message, HumanMessage):
            file.write(f"You: {message.content}\n")
        elif isinstance(message, AIMessage):
            file.write(f"AI: {message.content}\n\n")
```

### 3. Global State Management
```python
# Global variable for document content
document_content = ""

@tool
def update(content: str) -> str:
    """Update global document state"""
    global document_content
    document_content = content
    return f"Document updated: {document_content}"
```

## Tool Development Guidelines

### 1. Tool Definition Standards
```python
@tool
def tool_name(param1: type, param2: type) -> return_type:
    """
    Clear description of what the tool does.
    
    Args:
        param1: Description of parameter
        param2: Description of parameter
    
    Returns:
        Description of return value
    """
    # Implementation
    return result
```

### 2. Tool Integration
```python
tools = [tool1, tool2, tool3]
tools_dict = {tool.name: tool for tool in tools}
llm = ChatOpenAI(model="gpt-4o").bind_tools(tools)

# Use ToolNode for automatic tool execution
tool_node = ToolNode(tools=tools)
graph.add_node("tools", tool_node)
```

## Graph Construction Patterns

### 1. Basic Graph Setup
```python
graph = StateGraph(AgentState)
graph.add_node("node_name", node_function)
graph.set_entry_point("node_name")
graph.set_finish_point("node_name")
app = graph.compile()
```

### 2. Sequential Processing
```python
graph.add_node("first_node", first_function)
graph.add_node("second_node", second_function)
graph.set_entry_point("first_node")
graph.add_edge("first_node", "second_node")
graph.set_finish_point("second_node")
```

### 3. Conditional Routing
```python
def router_function(state: AgentState) -> str:
    """Route based on state conditions"""
    if condition:
        return "path_a"
    else:
        return "path_b"

graph.add_conditional_edges(
    "source_node",
    router_function,
    {
        "path_a": "node_a",
        "path_b": "node_b"
    }
)
```

### 4. Looping Patterns
```python
def should_continue(state: AgentState) -> str:
    """Control loop continuation"""
    if state["counter"] < max_iterations:
        return "loop"
    else:
        return "exit"

graph.add_conditional_edges(
    "loop_node",
    should_continue,
    {
        "loop": "loop_node",
        "exit": END
    }
)
```

## Error Handling and Validation

### 1. File Operations
```python
if not os.path.exists(file_path):
    raise FileNotFoundError(f"File not found: {file_path}")

try:
    # File operations
    with open(filename, 'w') as file:
        file.write(content)
except Exception as e:
    return f"Error: {str(e)}"
```

### 2. Tool Validation
```python
if not t['name'] in tools_dict:
    print(f"Tool: {t['name']} does not exist.")
    result = "Incorrect Tool Name, Please Retry."
else:
    result = tools_dict[t['name']].invoke(t['args'])
```

## Code Style Guidelines

### 1. Naming Conventions
- **Functions**: snake_case (`process_values`, `should_continue`)
- **Classes**: PascalCase (`AgentState`)
- **Variables**: snake_case (`user_input`, `conversation_history`)
- **Constants**: UPPER_CASE (`MAX_ITERATIONS`)

### 2. Documentation Standards
```python
def function_name(state: AgentState) -> AgentState:
    """
    Brief description of function purpose.
    
    Args:
        state: Current agent state
        
    Returns:
        Updated agent state
    """
    # Implementation
    return state
```

### 3. Import Organization
```python
# Standard library imports
import os
from typing import TypedDict, List

# Third-party imports
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage

# Local imports (if any)
```

## Interactive Patterns

### 1. User Input Loops
```python
def running_agent():
    print("\n=== AGENT STARTED ===")
    
    while True:
        user_input = input("\nEnter your question: ")
        if user_input.lower() in ['exit', 'quit']:
            break
            
        messages = [HumanMessage(content=user_input)]
        result = agent.invoke({"messages": messages})
        print(f"\nAI: {result['messages'][-1].content}")
```

### 2. Streaming Output
```python
def print_stream(stream):
    for s in stream:
        message = s["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()

# Usage
print_stream(app.stream(inputs, stream_mode="values"))
```

## Visualization Patterns

### 1. Graph Visualization
```python
from IPython.display import Image, display
display(Image(app.get_graph().draw_mermaid_png()))
```

### 2. Debug Output
```python
print(f"Calling Tool: {tool_name} with query: {query}")
print(f"Result length: {len(str(result))}")
print("Tools Execution Complete. Back to the model!")
```

### 3. Logs

#### Comprehensive Logging System

Implement a sophisticated multi-category logging system that provides detailed operational visibility while maintaining performance. The logging system is controlled via command-line arguments and supports both minimal and detailed logging modes.

##### Command Line Control
```bash
# Minimal logging (default) - only critical events
python tamara_graph.py

# Detailed logging - comprehensive operational visibility
python tamara_graph.py --log

# Custom log level without detailed mode
python tamara_graph.py --log-level INFO
```

##### Log Categories and Files

The system creates separate log files for different operational aspects:

1. **Critical Events** (`tamara_graph_critical.log`)
   - Safety-critical events, errors, failures
   - System-level exceptions and crashes
   - Emergency state transitions
   - Always enabled regardless of logging mode

2. **Operations** (`tamara_graph_operations.log`)
   - Operation starts, stops, state changes
   - Mode transitions (RUN → CLEAN → PRESSURE_TEST)
   - Command execution results
   - Process lifecycle events

3. **Safety** (`tamara_graph_safety.log`)
   - Safety checks and validations
   - Mode change confirmations
   - Parameter validation results
   - Safety protocol enforcement

4. **PLC Communication** (`tamara_graph_plc.log`)
   - PLC read/write operations
   - Connection status and errors
   - Data validation and verification
   - Transaction rollback events

5. **User Interactions** (`tamara_graph_user.log`)
   - User commands and inputs
   - Confirmation prompts and responses
   - Parameter collection events
   - User guidance and feedback

6. **Debug Information** (`tamara_graph_debug.log`)
   - Detailed debugging information
   - Internal state transitions
   - Performance metrics
   - Development and troubleshooting data

7. **Combined Log** (`tamara_graph.log`)
   - Rotating file with all categories combined
   - Maximum 1MB per file, 5 backup files
   - UTF-8 encoding for international character support

##### Logging Configuration

```python
def setup_logging(enable_detailed: bool = False) -> None:
    """Configure TAMARA logging system with appropriate handlers and formatters.
    
    Files:
    - tamara_graph_critical.log: Safety-critical events, errors, failures
    - tamara_graph_operations.log: Operation starts, stops, state changes
    - tamara_graph_safety.log: Safety checks, validations, mode changes
    - tamara_graph_plc.log: PLC communication details
    - tamara_graph_user.log: User interactions and commands
    - tamara_graph_debug.log: Detailed debugging information
    - tamara_graph.log: Combined log (all categories)
    
    Args:
        enable_detailed: If True, enables verbose logging across all categories
    """
```

##### Log Levels by Mode

**Minimal Mode (Default):**
- Critical: CRITICAL only
- Operations: WARNING and above
- Safety: WARNING and above
- PLC: INFO and above
- User: WARNING and above
- Debug: ERROR and above
- Combined: INFO and above

**Detailed Mode (`--log` flag):**
- All categories: DEBUG level
- Comprehensive operational visibility
- Full debugging information
- Performance impact consideration

##### Formatters

**Basic Formatter (Minimal Mode):**
```
%(asctime)s - %(levelname)s - %(message)s
```

**Detailed Formatter (Detailed Mode):**
```
%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s
```

##### Usage Examples

```python
# Category-specific loggers
log_critical = logging.getLogger('tamara.critical')
log_operations = logging.getLogger('tamara.operations')
log_safety = logging.getLogger('tamara.safety')
log_plc = logging.getLogger('tamara.plc')
log_user = logging.getLogger('tamara.user')
log_debug = logging.getLogger('tamara.debug')

# Usage in code
log_critical.error("Safety violation detected")
log_operations.info("Starting RUN operation")
log_safety.warning("Parameter validation failed")
log_plc.debug("PLC write operation completed")
log_user.info("User confirmed operation")
log_debug.debug("Internal state transition")
```

##### Benefits

1. **Operational Visibility**: Clear separation of concerns across different operational aspects
2. **Performance Optimization**: Minimal logging by default, detailed when needed
3. **Troubleshooting**: Comprehensive debugging information available on demand
4. **Compliance**: Audit trail for safety-critical operations
5. **Maintenance**: Easy identification of issues by category
6. **Scalability**: Rotating logs prevent disk space issues

## Best Practices Summary

1. **Always use type hints** for better code maintainability
2. **Implement proper error handling** for file operations and tool calls
3. **Use environment variables** for sensitive configuration
4. **Follow consistent naming conventions** throughout the codebase
5. **Document functions and tools** with clear docstrings
6. **Implement proper state management** using TypedDict and Annotated types
7. **Use conditional edges** for dynamic flow control
8. **Implement proper tool validation** before execution
9. **Provide user-friendly interfaces** with clear prompts and feedback
10. **Use streaming** for better user experience with long-running operations

## Common Anti-Patterns to Avoid

1. **Don't hardcode API keys** - always use environment variables
2. **Don't skip error handling** - always validate inputs and handle exceptions
3. **Don't use mutable default arguments** - use None and initialize inside function
4. **Don't ignore type hints** - they improve code quality and IDE support
5. **Don't create overly complex state structures** - keep them flat and simple
6. **Don't forget to compile graphs** - always call `graph.compile()` before use
7. **Don't skip tool descriptions** - LLMs need clear tool documentation
8. **Don't ignore memory management** - implement proper conversation history handling

This specification document provides a comprehensive guide for building LangGraph-based applications following the best patterns and practices.
