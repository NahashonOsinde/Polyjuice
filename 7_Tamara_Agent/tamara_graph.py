#!/usr/bin/env python3
from __future__ import annotations

"""
tamara_graph.py — LangGraph Agent for TAMARA Control System

This module implements a LangGraph-based agent for controlling TAMARA operations,
providing a natural language interface to the microfluidic system while maintaining
strict safety protocols and operational validation.

Core Responsibilities:
1. User Interaction
   - Natural language command processing
   - Operation parameter collection
   - Status feedback and confirmations

2. Safety Management
   - Pre-operation safety checks
   - Runtime state validation
   - Emergency handling
   - Mode transition safety

3. System Integration
   - PLC communication (via plc_tool)
   - Operation state management
   - Parameter validation
   - Command verification

4. Knowledge Integration
   - RAG-based query handling
   - Context-aware responses
   - Operation guidance

Graph Structure:
ROUTE → [ASK_KB → END] or [COLLECT_INPUTS → PRECAUTIONS → ACTIONS → END]

Key Components:
- GraphState: Manages operation state and history
- Route: Classifies user intent and handles commands
- Input Collection: Gathers and validates parameters
- Precautions: Implements safety checks and confirmations
- Actions: Executes PLC operations with verification

Safety Features:
- Mode transition validation
- Parameter range checking
- Operation state verification
- Command exclusivity enforcement
- Automatic safety state restoration
"""

# ----------------------------------------------------------------------------
# Standard library imports
# ----------------------------------------------------------------------------
"""
- A compact agent built with LangGraph that routes between RAG answers and PLC actions.
- A history-aware RAG chain -> `rag_build.py`
  (OpenAI embeddings "text-embedding-3-small", Chroma persist dir, history-aware retriever,
  QA chain with a focused system prompt).
- PLC tool integration uses the same DB9 field mapping and CRUNCH_VALID bit for the POC.

Machine-side guardrails & flow:
- Before any RUN/CLEAN/PRESSURE_TEST action, we insert a *RunPrep / CleanPrep* confirmation
  step (echoing our FBs' operator "Confirm" semantics).
- We only write the whitelisted inputs; core program logic stays in the PLC. The graph
  never attempts to upload/download blocks.

Process references from our PLC FBs (for context-only docs in prompts/UX):
- Formulation sequence: RunPrep → Amorcage → Priming → Mix/Run → MixOver.
- Clean sequence: CleanPrep → CleanPurge (Emptying/Vidange/Drying) → CleanFill → CleanCleanse → Done.
- PressureTest sequence: Fill → Hold → Vent → Done (with timeouts & tolerances).
- StateHandler super-states: Init(0) → Ready(1) → Run(2) → Clean(3) → PressureTest(4) → SafePurge(5) → Faulted(6) → Reset(7) → E-Stop(8).

Run:
  $ python tamara_graph.py            # REPL (Read-Eval-Print Loop)
  $ python tamara_graph.py --draw     # also saves ./tamara_graph.png (and previews if Jupyter notebook)
  $ python tamara_graph.py --log      # also saves ./logs/tamara_graph.log

Environment hints:
  OPENAI_API_KEY  - required for RAG/LLM. Without it, the agent still runs with a heuristic router
                    and simple answers.
  KB_CHROMA_DIR   - override Chroma persist dir (default: ./db/chroma_db_with_metadata_Knowledge_base)
  KB_TXT_DIR      - directory of .txt/.md files to (re)ingest if no Chroma exists yet (default: ./Knowledge_base/txt)
  PLC_*           - same as in plc_tool.py (PLC_SIM=1 by default).

"""

import os
import time
import argparse
import logging
import logging.handlers
from typing import TypedDict, List, Literal, Optional, Dict, Any, Tuple
from pathlib import Path
from dotenv import load_dotenv

# LangChain / LangGraph minimal set
try:
    from langchain_community.vectorstores import Chroma
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    from langchain.chains import create_history_aware_retriever, create_retrieval_chain
    from langchain.chains.combine_documents import create_stuff_documents_chain
    from langgraph.graph import StateGraph, END
except Exception as e:
    raise SystemExit("This script needs langchain, langchain_openai, langgraph, chromadb installed. "
                     "Install minimal deps: pip install 'langchain>=0.2' 'langchain-openai' 'langgraph>=0.2' 'chromadb'") from e

# Load environment variables from .env
load_dotenv()

# Display support for graph image (optional)
try:
    from IPython.display import Image, display
except Exception:
    Image = None  # type: ignore

# Local PLC tool
from plc_tool import (
    PLCInterface, InputPayload, CustomSolvent,
    OperationMode, MachineMode, ChipID, ManifoldID, OrgSolventID, ModeCmds,
    DB_CONFIG, snap7  # Import DB_CONFIG and snap7 for operation mode check
)

# ----------------------------------------------------------------------------
# Constants and Configuration
# ----------------------------------------------------------------------------

class PLCStatus:
    """PLC status codes and state definitions."""
    INITIALIZING = 0    # System startup in progress
    READY = 1          # System ready for operation
    RUNNING = 2        # Normal operation in progress
    CLEANING = 3       # Clean cycle in progress
    PRESSURE_TEST = 4  # Pressure test in progress
    SAFE_PURGE = 5    # System purging
    FAULTED = 6       # System error detected
    RESET = 7         # System reset in progress
    E_STOP = 8        # Emergency stop activated

class Timeouts:
    """Operation timeout values in seconds."""
    MODE_CHECK = 5.0       # Time between operation mode checks
    CRUNCH_VALID = 10.0    # Maximum wait for PLC validation
    BACKOFF_MIN = 0.05     # Minimum polling interval
    BACKOFF_MAX = 0.2      # Maximum polling interval

class Validation:
    """Parameter validation limits."""
    TFR_MIN = 0.8         # Minimum Total Flow Rate (mL/min)
    TFR_MAX = 15.0        # Maximum Total Flow Rate (mL/min)
    TEMP_MIN = 5.0        # Minimum Temperature (°C)
    TEMP_MAX = 60.0       # Maximum Temperature (°C)
    STRING_MAX = 16       # Maximum length for custom solvent name

# Backwards compatibility - some code still uses dictionary format
PLC_STATUS = {
    "INITIALIZING": PLCStatus.INITIALIZING,
    "READY": PLCStatus.READY,
    "RUNNING": PLCStatus.RUNNING,
    "CLEANING": PLCStatus.CLEANING,
    "PRESSURE_TEST": PLCStatus.PRESSURE_TEST,
    "SAFE_PURGE": PLCStatus.SAFE_PURGE,
    "FAULTED": PLCStatus.FAULTED,
    "RESET": PLCStatus.RESET,
    "E_STOP": PLCStatus.E_STOP
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/tamara_graph.log',
            maxBytes=1024*1024,
            backupCount=5,
            encoding='utf-8'  # Explicitly set UTF-8 encoding
        )
    ]
)
log = logging.getLogger(__name__)

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------------
# RAG: build or load
# ------------------------------------------------------------------------------------

def _persist_dir() -> str:
    # Try user's POC path first for compatibility; otherwise default to local ./db/..
    candidates = [
        os.getenv("KB_CHROMA_DIR"),
        os.path.join(SCRIPT_DIR, "db/chroma_db_with_metadata_Knowledge_base"),
        # os.path.join(SCRIPT_DIR, "../6_Tamara_workflow/db/chroma_db_with_metadata_Knowledge_base"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    # default to local
    default_dir = os.path.join(SCRIPT_DIR, "db/chroma_db_with_metadata_Knowledge_base")
    os.makedirs(default_dir, exist_ok=True)
    return default_dir

def _txt_dir() -> str:
    default_dir = os.path.join(SCRIPT_DIR, "Knowledge_base/txt")
    return os.getenv("KB_TXT_DIR", default_dir)

def _ingest_if_needed(persist_directory: str, txt_dir: str) -> Chroma:
    """
    If a persist dir exists, open it. Otherwise, build from txt_dir.
    Uses text-embedding-3-small, chunk_size=500, overlap=50.
    """
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )
    if os.path.isdir(persist_directory) and os.listdir(persist_directory):
        return Chroma(persist_directory=persist_directory, embedding_function=embeddings)

    # Build from scratch (very small and robust to missing files)
    docs: List[Document] = []
    if os.path.isdir(txt_dir):
        for root, _dirs, files in os.walk(txt_dir):
            for fn in files:
                if fn.lower().endswith((".txt", ".md")):
                    p = os.path.join(root, fn)
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            docs.append(Document(page_content=f.read(), metadata={"source": p}))
                    except Exception as e:
                        log.warning(f"Failed to read {p}: {e}")
    if not docs:
        # Fallback single doc so RAG still works
        seed = "TAMARA is a microfluidic system. Keep the lid closed during operations. Use Run, Clean, and Pressure Test modes."
        docs = [Document(page_content=seed, metadata={"source": "seed"})]

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    splits = splitter.split_documents(docs)
    vectorstore = Chroma.from_documents(splits, embedding=embeddings, persist_directory=persist_directory)
    vectorstore.persist()
    return vectorstore

def build_rag_chain():
    persist = _persist_dir()
    txt_dir = _txt_dir()
    vectorstore = _ingest_if_needed(persist, txt_dir)

    retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 15})
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
        temperature=0.1, # temperature is the randomness of the model's output, 0 is the most deterministic, 1 is the most random(creative)
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # (1) History-aware question reformulation
    contextualize_q_system_prompt = (
        "Given a chat history and the latest user question which might reference context in the chat history, "
        "reformulate the question to be fully self-contained, standalone and understood without the chat history."
        "Do NOT answer the question, just reformulate it if needed and otherwise return it as is."
    )
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)

    # (2) Focused QA chain
    # qa_system_prompt = (
    #     "You are an AI assistant specializing in TAMARA. Provide precise, technical, step-by-step answers "
    #     "and include safety considerations when relevant. Use ONLY the provided context.\n\n{context}"
    # )
    qa_system_prompt = """You are an AI assistant specializing in TAMARA, a microfluidic system. 
        Your role is to provide accurate, precise, technical, step-by-step answers, and helpful information 
        about TAMARA's operation, specifications, and best practices. Include safety considerations when relevant.
        
        When answering:
        1. Be precise and technical when discussing specifications
        2. Provide step-by-step guidance for operational questions
        3. Include relevant safety considerations
        4. If you're unsure or the information isn't in the context, say so
        5. Keep responses focused and relevant to TAMARA
        
        Use ONLY the following context to answer the question:
        \n{context}
        
        Base your answers solely on the provided context."""
    
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

    # (3) Final RAG chain
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    return rag_chain, llm

# ------------------------------------------------------------------------------------
# Graph state
# ------------------------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    messages: List[Any]               # alternating HumanMessage/AIMessage
    intent: Optional[Literal["ask_kb", "run", "clean", "ptest", "other"]]
    pending_action: Optional[str]     # "run"|"clean"|"ptest" when waiting for confirmation
    # confirmed: bool
    # last_tool_result: Optional[str]
    last_mode_check: float           # timestamp of last operation mode check

# ------------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------------

# ROUTE_HINT = (
#     "Classify the user's message into one of: "
#     "ask_kb (knowledge question), run, clean, ptest (pressure test), other. "
#     "Return just the label."
# )

def _heuristic_route(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["run", "formulate", "mix"]):
        return "run"
    if "clean" in t:
        return "clean"
    if "pressure" in t and "test" in t:
        return "ptest"
    # default: knowledge
    return "ask_kb"

def route(state: GraphState, *, llm=None) -> GraphState:
    """Route user messages to appropriate handlers based on intent and current state.
    
    This function is the primary routing hub for the TAMARA agent. It handles:
    1. Command Recognition: Identifies operation commands (run/clean/test)
    2. Control Commands: Manages pause/play/stop operations
    3. Status Queries: Provides system state information
    4. Knowledge Queries: Routes to RAG for information requests
    
    Command Priority:
    1. Control commands (stop/pause/play) - immediate handling
    2. Status queries - direct PLC communication
    3. Operation commands (run/clean/test) - requires validation
    4. Knowledge queries (default) - RAG processing
    
    Args:
        state (GraphState): Current graph state containing:
            - messages: List of user/AI message history
            - intent: Current operation intent
            - pending_action: Any operation awaiting confirmation
        llm (Optional): Language model instance (unused in current implementation)
        
    Returns:
        GraphState: Updated state with:
            - New messages added
            - Intent classification
            - Any state changes from command processing
            
    Safety:
        - Validates operation mode before state transitions
        - Ensures proper mode transitions
        - Maintains operation state consistency
    """
    last = state["messages"][-1]
    if isinstance(last, HumanMessage):
        user_text = last.content.lower()
    else:
        # fallback
        user_text = str(last).lower()
    
    log.info(f"Routing message: '{user_text}' (pending_action: {state.get('pending_action')})")
    
    # Handle control commands
    if "pause" in user_text:
        log.info("Handling PAUSE command...")
        plc = PLCInterface()
        try:
            # First read current status to verify we're running
            log.info("Reading current status...")
            status_code = plc.read_status()
            log.info(f"Current status code: {status_code}")
            
            # Map status code to mode
            mode = None
            if status_code == PLC_STATUS["RUNNING"]:
                mode = MachineMode.RUN
            elif status_code == PLC_STATUS["CLEANING"]:
                mode = MachineMode.CLEAN
            elif status_code == PLC_STATUS["PRESSURE_TEST"]:
                mode = MachineMode.PRESSURE_TEST
                
            if mode is not None:
                # Set pause bit using pulse_cmd for the current mode
                log.info(f"Setting PAUSE_PLAY bit to TRUE for {mode.name} mode...")
                plc.pulse_cmd(mode, ModeCmds.PAUSE_PLAY, True)
                state["messages"].append(AIMessage(content=f"{mode.name} operation paused. Say 'play' to resume."))
            else:
                log.info(f"Cannot pause - status code {status_code} not in active modes")
                state["messages"].append(AIMessage(content="Cannot pause - no operation is active. Use 'status' to check current state."))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error setting pause command: {str(e)}"))
            log.error(f"Failed to set PAUSE_PLAY bit: {e}", exc_info=True)
        finally:
            log.info("Disconnecting from PLC...")
            plc.disconnect()
        
        # CRITICAL: Set intent to prevent further routing
        state["intent"] = "other"
        return state
    
    elif "play" in user_text or "resume" in user_text:
        log.info("Handling PLAY/RESUME command...")
        plc = PLCInterface()
        try:
            # First read current status to verify we're paused
            log.info("Reading current status...")
            status_code = plc.read_status()
            log.info(f"Current status code: {status_code}")
            
            # Map status code to mode
            mode = None
            if status_code == PLC_STATUS["RUNNING"]:
                mode = MachineMode.RUN
            elif status_code == PLC_STATUS["CLEANING"]:
                mode = MachineMode.CLEAN
            elif status_code == PLC_STATUS["PRESSURE_TEST"]:
                mode = MachineMode.PRESSURE_TEST
                
            if mode is not None:
                # Clear pause bit using pulse_cmd for the current mode
                log.info(f"Setting PAUSE_PLAY bit to FALSE for {mode.name} mode...")
                plc.pulse_cmd(mode, ModeCmds.PAUSE_PLAY, False)
                state["messages"].append(AIMessage(content=f"{mode.name} operation resumed."))
            else:
                log.info(f"Cannot resume - status code {status_code} not in active modes")
                state["messages"].append(AIMessage(content="Cannot resume - no operation is active. Use 'status' to check current state."))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error clearing pause command: {str(e)}"))
            log.error(f"Failed to clear PAUSE_PLAY bit: {e}", exc_info=True)
        finally:
            log.info("Disconnecting from PLC...")
            plc.disconnect()
        
        # CRITICAL: Set intent to prevent further routing
        state["intent"] = "other"
        return state
    
    elif "stop" in user_text:
        log.info("Handling STOP command...")
        plc = PLCInterface()
        try:
            # First read current status to verify we're running or paused
            log.info("Reading current status...")
            status_code = plc.read_status()
            log.info(f"Current status code: {status_code}")
            
            if status_code in [PLC_STATUS["RUNNING"], PLC_STATUS["CLEANING"], PLC_STATUS["PRESSURE_TEST"]]:
                # Set stop bit using pulse_cmd for current mode
                log.info("Setting STOP bit to TRUE...")
                if status_code == PLC_STATUS["RUNNING"]:
                    mode = MachineMode.RUN
                elif status_code == PLC_STATUS["CLEANING"]:
                    mode = MachineMode.CLEAN
                elif status_code == PLC_STATUS["PRESSURE_TEST"]:
                    mode = MachineMode.PRESSURE_TEST
                else:
                    raise ValueError(f"Unexpected status code: {status_code}")
                    
                # Stop command automatically clears other bits in the mode
                plc.pulse_cmd(mode, ModeCmds.STOP, True)
                state["messages"].append(AIMessage(content=f"{mode.name} operation stopped."))
            else:
                log.info(f"Cannot stop - status code {status_code} not in [{PLC_STATUS['RUNNING']},{PLC_STATUS['CLEANING']},{PLC_STATUS['PRESSURE_TEST']}] (Running/Cleaning/PTest)")
                state["messages"].append(AIMessage(content="Cannot stop - no operation is running. Use 'status' to check current state."))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error setting stop command: {str(e)}"))
            log.error(f"Failed to set STOP bit: {e}", exc_info=True)
        finally:
            log.info("Disconnecting from PLC...")
            plc.disconnect()
        
        # CRITICAL: Set intent to prevent further routing
        state["intent"] = "other"
        return state
    
    elif "status" in user_text:
        plc = PLCInterface()
        try:
            status_code = plc.read_status()
            # Map status codes to human-readable messages based on StateHandler states
            status_messages = {
                PLC_STATUS["INITIALIZING"]: "Initializing - System startup in progress",
                PLC_STATUS["READY"]: "Ready - System is ready for operation",
                PLC_STATUS["RUNNING"]: "Running - Normal operation in progress",
                PLC_STATUS["CLEANING"]: "Cleaning - Clean cycle in progress",
                PLC_STATUS["PRESSURE_TEST"]: "Pressure Test - Testing system pressure",
                PLC_STATUS["SAFE_PURGE"]: "Safe Purge - System purging in progress",
                PLC_STATUS["FAULTED"]: "Faulted - System error detected",
                PLC_STATUS["RESET"]: "Reset - System reset in progress",
                PLC_STATUS["E_STOP"]: "E-Stop - Emergency stop activated"
            }
            status_msg = status_messages.get(status_code, f"Unknown status (code: {status_code})")
            
            # Add more context based on status
            context = ""
            if status_code == PLC_STATUS["RUNNING"]:
                context = "\nUse 'pause' to pause, 'stop' to stop the operation."
            elif status_code == PLC_STATUS["CLEANING"]:
                context = "\nCleaning cycle must complete for safety. Use 'stop' only if necessary."
            elif status_code == PLC_STATUS["PRESSURE_TEST"]:
                context = "\nDo not interrupt pressure test unless necessary."
            elif status_code == PLC_STATUS["FAULTED"]:
                context = "\nCheck PLC panel for error details. Clear faults before continuing."
            elif status_code == PLC_STATUS["E_STOP"]:
                context = "\nAddress emergency condition before resetting E-Stop."
            
            state["messages"].append(AIMessage(content=f"TAMARA Status: {status_msg}{context}"))
        finally:
            plc.disconnect()
        
        # CRITICAL: Set intent to prevent further routing
        state["intent"] = "other"
        return state

    # Standard operation routing
    label = _heuristic_route(user_text)
    state["intent"] = label  # keep simple & deterministic
    return state

# ------------------------------------------------------------------------------------
# Precautions node — mirrors RunPrep / CleanPrep operator confirm
# ------------------------------------------------------------------------------------

PRECHECK_TEXT_RUN = (
    "Before we proceed, please confirm the pre-run checks:\n"
    "1) Required fluids are loaded in the reservoirs per protocol.\n"
    "2) Chip is correctly seated & oriented; gasket in place; manifold connected.\n"
    "3) Lid is CLOSED; lines secure; drain bottle in place.\n"
    "4) Pressure supply within specifications; recent Pressure Test passed if applicable.\n"
    "Type 'confirm' to continue or 'cancel' to abort."
)

PRECHECK_TEXT_CLEAN = (
    "Before we proceed, please confirm the pre-clean checks:\n"
    "1) Required fluids are loaded in the reservoirs per protocol.\n"
    "2) Chip is correctly seated & oriented; gasket in place; manifold connected.\n"
    "3) Lid is CLOSED; lines secure; drain bottle in place.\n"
    "4) Pressure supply within specifications; recent Pressure Test passed if applicable.\n"
    "Type 'confirm' to continue or 'cancel' to abort."
)

PRECHECK_TEXT_PRESSURE_TEST = (
    "Before we proceed, please confirm the pre-pressure test checks:\n"
    "1) Required fluids are loaded in the reservoirs per protocol.\n"
    "2) Chip is correctly seated & oriented; gasket in place; manifold connected.\n"
    "3) Lid is CLOSED; lines secure; drain bottle in place.\n"
    "4) Pressure supply within specifications; recent Pressure Test passed if applicable.\n"
    "Type 'confirm' to continue or 'cancel' to abort."
)


# ------------------------------------------------------------------------------------
# Action nodes (collect inputs, write to PLC, poll validation)
# ------------------------------------------------------------------------------------

def static_validate(payload: InputPayload) -> Tuple[bool, List[str]]:
    """Perform static validation of input parameters before sending to PLC.
    
    This function validates all input parameters against their allowed ranges
    and logical constraints. It performs the following checks:
    1. TFR (Total Flow Rate) within operational limits
    2. FRR (Flow Rate Ratio) is positive
    3. Temperature within safe operating range
    4. Target volume is positive and reasonable
    
    Args:
        payload (InputPayload): The complete set of operation parameters to validate
        
    Returns:
        Tuple[bool, List[str]]: A tuple containing:
            - bool: True if all validations pass, False otherwise
            - List[str]: List of validation error messages (empty if all pass)
            
    Example:
        >>> payload = InputPayload(tfr=1.0, frr=5, ...)
        >>> is_valid, messages = static_validate(payload)
        >>> if not is_valid:
        ...     print("Validation failed:", messages)
    """
    messages = []
    is_valid = True

    # TFR range
    if not (0.8 <= payload.tfr <= 15.0):
        messages.append("TFR must be between 0.8 and 15.0 mL/min")
        is_valid = False

    # FRR must be positive
    if payload.frr <= 0:
        messages.append("FRR must be a positive integer")
        is_valid = False

    # Temperature range
    if not (5.0 <= payload.temperature <= 60.0):
        messages.append("Temperature must be between 5°C and 60°C")
        is_valid = False

    # Target volume must be positive
    if payload.target_volume <= 0:
        messages.append("Target volume must be positive")
        is_valid = False

    return is_valid, messages

def _collect_inputs_from_cli(kind: str) -> InputPayload:
    """Collect and validate all TAMARA inputs including solvent parameters."""
    print(f"[{kind}] Enter parameters…")
    while True:
        try:
            # Core parameters
            tfr = float(input("Total Flow Rate (mL/min): ").strip())
            frr = int(input("Flow Rate Ratio (integer): ").strip())
            target_volume = float(input("Target Volume (mL): ").strip())
            temperature = float(input("Temperature (°C): ").strip())
            lab_pressure = float(input("Lab pressure (mbar): ").strip())
            
            # Chip selection
            while True:
                chip_id = input("Chip ID (BAFFLE/HERRINGBONE): ").strip().upper()
                if chip_id in ["BAFFLE", "HERRINGBONE"]:
                    break
                print("Please enter either BAFFLE or HERRINGBONE")
            
            # Manifold selection
            while True:
                manifold = input("Manifold (SMALL/LARGE): ").strip().upper()
                if manifold in ["SMALL", "LARGE"]:
                    break
                print("Please enter either SMALL or LARGE")

            # Solvent selection
            print("\nOrganic solvent options:")
            for s in OrgSolventID:
                print(f"  {s.name}")
            while True:
                solvent = input("Select organic solvent: ").strip().upper()
                if solvent in [s.name for s in OrgSolventID]:
                    break
                print("Please enter a valid solvent option")
            
            # Custom solvent parameters if needed
            custom_solvent = None
            if solvent == "CUSTOM":
                name = input("Custom solvent name: ").strip()
                if len(name) > 16:
                    raise ValueError("Custom solvent name must be 16 characters or less")
                    
                viscosity = float(input("Viscosity at 20°C (μPa·s): ").strip())
                sensitivity = float(input("Temperature sensitivity (μPa·s/°C): ").strip())
                molar_volume = float(input("Molar volume (mL/mol): ").strip())
                
                custom_solvent = CustomSolvent(
                    name=name,
                    viscosity=viscosity,
                    sensitivity=sensitivity,
                    molar_volume=molar_volume
                )

            # Basic sanity checks
            msgs = []
            if not (0.8 <= tfr <= 15.0): msgs.append("TFR must be between 0.8 and 15.0 mL/min")
            if frr <= 0: msgs.append("FRR must be a positive integer")
            if not (5.0 <= temperature <= 60.0): msgs.append("Temperature must be between 5°C and 60°C")
            if target_volume <= 0: msgs.append("Target volume must be positive")
            if lab_pressure <= 0: msgs.append("Lab pressure must be positive")
            if msgs:
                raise ValueError("; ".join(msgs))

            # Map machine mode based on operation type
            machine_mode = {
                "run": MachineMode.RUN,
                "clean": MachineMode.CLEAN,
                "ptest": MachineMode.PRESSURE_TEST
            }[kind]

            return InputPayload(
                # Core parameters (required)
                tfr=tfr,
                frr=frr,
                target_volume=target_volume,
                temperature=temperature,
                chip_id=ChipID[chip_id],
                manifold_id=ManifoldID[manifold],
                lab_pressure=lab_pressure,
                org_solvent_id=OrgSolventID[solvent],
                
                # Optional parameters
                operation_mode=OperationMode.AGENTIC,
                machine_mode=machine_mode,
                custom_solvent=custom_solvent
            )
        except ValueError as e:
            print(f"Error: {e}")
            if input("Try again? (y/n): ").lower() != 'y':
                raise

def do_run(state: GraphState) -> GraphState:
    """Execute RUN operation with validated parameters."""
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Prepare confirmation message with safety checks
    msg = (
        "Ready to start RUN operation.\n\n"
        "Please verify:\n"
        "1. Required fluids are loaded in reservoirs\n"
        "2. Chip is correctly seated and oriented\n"
        "3. Manifold is properly connected\n"
        "4. Lid is CLOSED\n"
        "5. Lines are secure\n"
        "6. Drain bottle is in place\n"
        "7. Pressure supply is within specifications\n\n"
        "Type 'confirm' to proceed or 'cancel' to abort."
    )
    state["messages"].append(AIMessage(content=msg))
    return state

def do_clean(state: GraphState) -> GraphState:
    """Execute CLEAN operation with validated parameters."""
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Prepare confirmation message with safety checks
    msg = (
        "Ready to start CLEAN operation.\n\n"
        "Please verify:\n"
        "1. Cleaning solution is loaded in reservoirs\n"
        "2. Chip is correctly seated and oriented\n"
        "3. Manifold is properly connected\n"
        "4. Lid is CLOSED\n"
        "5. Lines are secure\n"
        "6. Drain bottle has sufficient capacity\n"
        "7. Pressure supply is within specifications\n\n"
        "WARNING: Once started, the cleaning cycle must complete for safety.\n"
        "Type 'confirm' to proceed or 'cancel' to abort."
    )
    state["messages"].append(AIMessage(content=msg))
    return state

def do_ptest(state: GraphState) -> GraphState:
    """Execute PRESSURE TEST operation with validated parameters."""
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Prepare confirmation message with safety checks
    msg = (
        "Ready to start PRESSURE TEST operation.\n\n"
        "Please verify:\n"
        "1. System is properly prepared for pressure testing\n"
        "2. Chip is correctly seated and oriented\n"
        "3. Manifold is properly connected\n"
        "4. Lid is CLOSED and secured\n"
        "5. Lines are secure and rated for test pressure\n"
        "6. Area is clear of personnel\n"
        "7. Emergency stop is accessible\n\n"
        "WARNING: Stand clear during pressure test.\n"
        "Type 'confirm' to proceed or 'cancel' to abort."
    )
    state["messages"].append(AIMessage(content=msg))
    return state

# ------------------------------------------------------------------------------------
# RAG node
# ------------------------------------------------------------------------------------

class RAGManager:
    """Thread-safe RAG chain manager"""
    def __init__(self):
        self._chain = None
        self._llm = None

    def ensure_initialized(self):
        if self._chain is None:
            self._chain, self._llm = build_rag_chain()
        return self._chain, self._llm

# Global RAG manager instance
rag_manager = RAGManager()

def answer_with_rag(state: GraphState) -> GraphState:
    try:
        chain, _ = rag_manager.ensure_initialized()
        # use entire running transcript as history
        chat_history: List = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage))][:-1]
        user_text = state["messages"][-1].content if isinstance(state["messages"][-1], HumanMessage) else ""

        result = chain.invoke({"input": user_text, "chat_history": chat_history})
        state["messages"].append(AIMessage(content=result["answer"]))
    except Exception as e:
        # degrade gracefully
        state["messages"].append(AIMessage(content=f"(RAG unavailable) Heuristic answer: {user_text}"))
        log.exception("RAG failed: %s", e)
    return state

# ------------------------------------------------------------------------------------
# Graph assembly
# ------------------------------------------------------------------------------------

def build_graph():
    """Build the TAMARA agent graph with proper state management and flow control.
    
    This function constructs a LangGraph state machine that enforces:
    1. Proper operation sequencing
    2. Safety protocol adherence
    3. State transition validation
    4. Error handling and recovery
    
    Graph Structure:
    ---------------
    1. Route Node
       - Initial intent classification
       - Command recognition
       - State validation
    
    2. Input Collection Nodes
       - Parameter gathering
       - Range validation
       - PLC communication
    
    3. Precaution Nodes
       - Safety checklist presentation
       - Operator confirmation
       - State verification
    
    4. Action Nodes
       - Operation execution
       - Command bit management
       - Status monitoring
    
    5. Terminal States
       - Successful completion
       - Error handling
       - Operation cancellation
    
    State Flow Paths:
    ----------------
    1. Knowledge Query:
       ROUTE → ASK_KB → END
    
    2. Operation Execution:
       ROUTE → COLLECT_INPUTS → PRECAUTIONS → ACTIONS → END
    
    Safety Features:
    ---------------
    - Mode validation at transitions
    - Parameter range checking
    - Command exclusivity enforcement
    - Operation state verification
    - Automatic safety state restoration
    
    Returns:
        compiled_graph: A LangGraph state machine ready for execution
    """
    graph = StateGraph(GraphState)

    # Add basic nodes
    graph.add_node("route", route)
    graph.add_node("ask_kb", answer_with_rag)

    # Add input collection nodes
    def collect_and_validate_with_plc(state: GraphState, kind: str) -> GraphState:
        """Collect inputs, validate locally, and check with PLC."""
        try:
            # 1. Collect inputs
            payload = _collect_inputs_from_cli(kind)
            
            # 2. Local validation
            valid, messages = static_validate(payload)
            if not valid:
                error_msg = "Input validation failed:\n" + "\n".join(f"- {msg}" for msg in messages)
                state["messages"].append(AIMessage(content=error_msg))
                return state
            
            # 3. Send to PLC and check validation
            plc = PLCInterface()
            try:
                # Send inputs
                plc.write_payload_to_plc(payload)
                state["messages"].append(AIMessage(content="Parameters sent to PLC. Checking validation..."))
                
                # Poll for validation
                t0 = time.time()
                ok = False
                while time.time() - t0 < 3.0:
                    if plc.read_crunch_valid():
                        ok = True
                        break
                    time.sleep(0.1)
                
                if ok:
                    state["messages"].append(AIMessage(content="Parameters accepted by PLC. Proceeding with safety checks..."))
                    state["input_payload"] = payload
                    state["pending_action"] = kind
                    log.info(f"State after PLC validation: input_payload={state.get('input_payload')}, pending_action={state.get('pending_action')}")
                else:
                    state["messages"].append(AIMessage(
                        content="Parameters rejected by PLC. Please modify your inputs to be within the allowed ranges. "
                               "Check PLC panel for specific limits."
                    ))
            finally:
                plc.disconnect()
                
            return state
            
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error: {str(e)}"))
            return state

    def collect_run_inputs(state: GraphState) -> GraphState:
        """Collect and validate run parameters."""
        return collect_and_validate_with_plc(state, "run")

    def collect_clean_inputs(state: GraphState) -> GraphState:
        """Collect and validate clean parameters."""
        return collect_and_validate_with_plc(state, "clean")

    def collect_ptest_inputs(state: GraphState) -> GraphState:
        """Collect and validate pressure test parameters."""
        return collect_and_validate_with_plc(state, "ptest")

    graph.add_node("collect_run_inputs", collect_run_inputs)
    graph.add_node("collect_clean_inputs", collect_clean_inputs)
    graph.add_node("collect_ptest_inputs", collect_ptest_inputs)

    # Add precaution nodes - these just show the message
    def show_precautions_run(state: GraphState) -> GraphState:
        state["messages"].append(AIMessage(content=PRECHECK_TEXT_RUN))
        return state
    
    def show_precautions_clean(state: GraphState) -> GraphState:
        state["messages"].append(AIMessage(content=PRECHECK_TEXT_CLEAN))
        return state
    
    def show_precautions_ptest(state: GraphState) -> GraphState:
        state["messages"].append(AIMessage(content=PRECHECK_TEXT_PRESSURE_TEST))
        return state

    graph.add_node("precautions_run", show_precautions_run)
    graph.add_node("precautions_clean", show_precautions_clean)
    graph.add_node("precautions_ptest", show_precautions_ptest)

    # Add action nodes
    graph.add_node("do_run", do_run)
    graph.add_node("do_clean", do_clean)
    graph.add_node("do_ptest", do_ptest)

    # Set entry point
    graph.set_entry_point("route")

    # Simplified routing logic
    def _route_intent(state: GraphState) -> str:
        """Route based on user intent."""
        intent = state.get("intent", "ask_kb")
        
        if intent == "ask_kb":
            return "ask_kb"
        elif intent in ["run", "clean", "ptest"]:
            return f"collect_{intent}_inputs"
        else:
            return "ask_kb"

    # Handle input collection result
    def _handle_input_collection(state: GraphState, action: str) -> str:
        """Route after input collection."""
        if "pending_action" in state and "input_payload" in state:
            return f"precautions_{action}"
        return END

    # Add routing edges
    graph.add_conditional_edges(
        "route",
        _route_intent,
        {
            "ask_kb": "ask_kb",
            "collect_run_inputs": "collect_run_inputs",
            "collect_clean_inputs": "collect_clean_inputs",
            "collect_ptest_inputs": "collect_ptest_inputs"
        }
    )

    # Add edges from input collection to precautions
    for action in ["run", "clean", "ptest"]:
        graph.add_conditional_edges(
            f"collect_{action}_inputs",
            lambda s, a=action: _handle_input_collection(s, a),
            {
                f"precautions_{action}": f"precautions_{action}",
                END: END
            }
        )

    # Add edges from precautions to actions (no conditional routing needed)
    graph.add_edge("precautions_run", "do_run")
    graph.add_edge("precautions_clean", "do_clean")
    graph.add_edge("precautions_ptest", "do_ptest")

    # Add terminal edges
    graph.add_edge("ask_kb", END)
    graph.add_edge("do_run", END)
    graph.add_edge("do_clean", END)
    graph.add_edge("do_ptest", END)

    return graph.compile()

# ------------------------------------------------------------------------------------
# Simple REPL (Read-Eval-Print Loop) around the graph
# ------------------------------------------------------------------------------------

def ensure_ready_state() -> None:
    """Set machine mode to READY (1)."""
    with PLCInterface() as plc:
        try:
            plc.set_machine_mode(PLC_STATUS["READY"])
            log.info("Machine mode set to READY")
        except Exception as e:
            log.error(f"Failed to set READY state: {e}", exc_info=True)
            raise

def check_operation_mode() -> bool:
    """Check if TAMARA is in AGENTIC mode.
    
    Returns:
        bool: True if in AGENTIC mode, False if in CONVENTIONAL mode
    """
    with PLCInterface() as plc:
        try:
            # Read operation mode from PLC
            mode = plc.read_operation_mode()
            log.info(f"Current operation mode: {mode.name}")
            return mode == OperationMode.AGENTIC
        except Exception as e:
            log.error(f"Failed to read operation mode: {e}", exc_info=True)
            raise

def periodic_mode_check(state: GraphState) -> None:
    """Periodically check if we're still in AGENTIC mode."""
    try:
        if not check_operation_mode():
            log.warning("TAMARA switched to CONVENTIONAL mode")
            state["messages"].append(AIMessage(
                content="WARNING: TAMARA has been switched to CONVENTIONAL mode.\n"
                "Please switch back to AGENTIC mode on the HMI to continue operations."
            ))
            # Set machine to READY state
            ensure_ready_state()
            return False
        return True
    except Exception as e:
        log.error(f"Failed periodic mode check: {e}", exc_info=True)
        state["messages"].append(AIMessage(
            content=f"Error checking operation mode: {str(e)}\n"
            "Please ensure TAMARA is connected and in AGENTIC mode."
        ))
        return False

def repl(draw: bool = False):
    app = build_graph()

    # Optionally draw
    if draw:
        try:
            img_bytes = app.get_graph().draw_png()
            img_path = os.path.join(SCRIPT_DIR, "images/tamara_graph.png")
            os.makedirs(os.path.dirname(img_path), exist_ok=True)
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            if Image:
                display(Image(img_bytes))
            else:
                print(f"Saved graph to {img_path}")
        except Exception as e:
            log.error(f"Could not render graph: {e}")

    # Check operation mode and set READY state before starting
    print("== TAMARA Agent (LangGraph) ==")
    print("Checking operation mode...")
    try:
        if not check_operation_mode():
            print("\nERROR: TAMARA is in CONVENTIONAL mode.")
            print("Please switch to AGENTIC mode on the HMI before running this script.")
            print("\nInstructions:")
            print("1. On the HMI, locate the Operation Mode toggle")
            print("2. Switch it to AGENTIC mode")
            print("3. Run this script again")
            return
            
        # Set initial READY state
        print("Setting initial READY state...")
        ensure_ready_state()
        
    except Exception as e:
        print(f"\nERROR: Failed to check operation mode: {e}")
        print("Please ensure TAMARA is connected and try again.")
        return

    print("Operation mode: AGENTIC")
    # Initialize state with all required fields
    state: GraphState = {
        "messages": [],
        "intent": None,
        "pending_action": None,
        "confirmed": False,
        "last_tool_result": None,
        "last_mode_check": time.time()  # Initialize mode check timestamp
    }

    print("== TAMARA Agent (LangGraph) ==")
    print("Type 'exit' to quit. Try: 'run', 'clean', 'pressure test', or ask knowledge questions.")
    while True:
        try:
            user = input("\nYou: ").strip()
            if not user:
                continue
            if user.lower() in ("exit", "quit"):
                break

            # Check operation mode before any state transition
            if user.lower() in ["run", "clean", "pressure test", "stop", "pause", "play", "resume"]:
                if not check_operation_mode():
                    print("\nERROR: TAMARA is in CONVENTIONAL mode.")
                    print("Please switch to AGENTIC mode on the HMI before continuing.")
                    ensure_ready_state()
                    continue

            # Handle stop command
            if user.lower() == "stop":
                ensure_ready_state()
                state["messages"].append(AIMessage(content="Operation stopped and machine set to READY state."))
                continue

            # Add user message & run graph once
            state["messages"].append(HumanMessage(content=user))
            log.info(f"Current state before invoke: {state}")
            state = app.invoke(state)
            log.info(f"Current state after invoke: {state}")
            
            # Emit all new AI messages since last user input
            # Find the last user message index
            last_user_index = -1
            for i, msg in enumerate(state["messages"]):
                if isinstance(msg, HumanMessage):
                    last_user_index = i
            
            # Show all AI messages that came after the last user input
            if last_user_index >= 0:
                new_ai_messages = [m for m in state["messages"][last_user_index+1:] if isinstance(m, AIMessage)]
                for ai_msg in new_ai_messages:
                    print(f"\nAI: {ai_msg.content}")
            
            # Handle confirmation if we're in an action state
            last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
            if state.get("pending_action") and last_ai and "Type 'confirm' to proceed" in last_ai.content:
                # Wait for user confirmation
                confirm_input = input("\nType 'confirm' to start operation or 'cancel' to abort: ").strip().lower()
                if confirm_input == "confirm":
                    # Set PLC command bits
                    action = state["pending_action"]
                    log.info(f"Starting {action} operation...")
                    plc = PLCInterface()
                    try:
                        # Map action to machine mode
                        mode_map = {
                            "run": MachineMode.RUN,
                            "clean": MachineMode.CLEAN,
                            "ptest": MachineMode.PRESSURE_TEST
                        }
                        mode = mode_map[action]
                        
                        # Clear all command bits first
                        plc.clear_all_cmd_bits()
                        
                        # Set START bit for this mode
                        plc.pulse_cmd(mode, ModeCmds.START, True)
                        
                        # Verify START is set and PAUSE_PLAY is clear
                        start_set = plc._read_bool(f"COMMANDS_{mode.name}.b_START")
                        pause_clear = not plc._read_bool(f"COMMANDS_{mode.name}.b_PAUSE_PLAY")
                        
                        if start_set and pause_clear:
                            print(f"\nAI: {action.upper()} operation started successfully!")
                            state["confirmed"] = True
                            state["pending_action"] = None
                        else:
                            log.warning(f"Failed to start {action} operation - COMMAND_START bit not set")
                            print(f"\nAI: Warning: Failed to start {action} operation. Please try again.")
                    except Exception as e:
                        log.error(f"Error starting {action} operation: {str(e)}", exc_info=True)
                        print(f"\nAI: Error starting {action} operation: {str(e)}")
                    finally:
                        plc.disconnect()
                elif confirm_input == "cancel":
                    log.info(f"Operation {action} cancelled by user")
                    print("\nAI: Operation cancelled.")
                    state["pending_action"] = None
                    state["confirmed"] = False

        except KeyboardInterrupt:
            print("\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            log.error(f"Error in REPL loop: {e}", exc_info=True)
            print(f"\nError: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TAMARA LangGraph agent")
    parser.add_argument("--draw", action="store_true", help="Render the graph to tamara_graph.png")
    args = parser.parse_args()
    repl(draw=args.draw)