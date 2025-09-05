#!/usr/bin/env python3
"""
tamara_graph.py — Minimal LangGraph agent harness for TAMARA

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
from __future__ import annotations
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
from plc_tool import PLCInterface, InputPayload, ChipID, Manifold, Mode

# PLC Status Constants
PLC_STATUS = {
    "INITIALIZING": 0,
    "READY": 1,
    "RUNNING": 2,
    "CLEANING": 3,
    "PRESSURE_TEST": 4,
    "SAFE_PURGE": 5,
    "FAULTED": 6,
    "RESET": 7,
    "E_STOP": 8
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
        temperature=0,
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

class GraphState(TypedDict):
    messages: List[Any]               # alternating HumanMessage/AIMessage
    intent: Optional[Literal["ask_kb", "run", "clean", "ptest", "other"]]
    pending_action: Optional[str]     # "run"|"clean"|"ptest" when waiting for confirmation
    confirmed: bool
    last_tool_result: Optional[str]

# ------------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------------

ROUTE_HINT = (
    "Classify the user's message into one of: "
    "ask_kb (knowledge question), run, clean, ptest (pressure test), other. "
    "Return just the label."
)

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
            
            if status_code == PLC_STATUS["RUNNING"]:
                # Set pause bit and verify
                log.info("Setting PAUSE_PLAY bit to TRUE...")
                plc.write_command_bit("COMMAND_PAUSE_PLAY", True)
                
                log.info("Verifying PAUSE_PLAY bit...")
                if plc.read_command_bit("COMMAND_PAUSE_PLAY"):
                    log.info("PAUSE_PLAY bit verified as TRUE")
                    state["messages"].append(AIMessage(content="Operation paused. Say 'play' to resume."))
                else:
                    log.warning("PAUSE_PLAY bit verification failed")
                    state["messages"].append(AIMessage(content="Warning: Failed to set pause command. Try again."))
                    log.warning("Failed to verify PAUSE_PLAY bit was set")
            else:
                log.info(f"Cannot pause - status code {status_code} is not Running({PLC_STATUS['RUNNING']})")
                state["messages"].append(AIMessage(content="Cannot pause - operation is not running. Use 'status' to check current state."))
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
            
            if status_code == PLC_STATUS["RUNNING"]:
                # Clear pause bit and verify
                log.info("Setting PAUSE_PLAY bit to FALSE...")
                plc.write_command_bit("COMMAND_PAUSE_PLAY", False)
                
                log.info("Verifying PAUSE_PLAY bit...")
                if not plc.read_command_bit("COMMAND_PAUSE_PLAY"):
                    log.info("PAUSE_PLAY bit verified as FALSE")
                    state["messages"].append(AIMessage(content="Operation resumed."))
                else:
                    log.warning("PAUSE_PLAY bit verification failed")
                    state["messages"].append(AIMessage(content="Warning: Failed to clear pause command. Try again."))
                    log.warning("Failed to verify PAUSE_PLAY bit was cleared")
            else:
                log.info(f"Cannot resume - status code {status_code} is not Running({PLC_STATUS['RUNNING']})")
                state["messages"].append(AIMessage(content="Cannot resume - operation is not paused. Use 'status' to check current state."))
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
                # Set stop bit and verify
                log.info("Setting STOP bit to TRUE...")
                plc.write_command_bit("COMMAND_STOP", True)
                
                log.info("Verifying STOP bit...")
                if plc.read_command_bit("COMMAND_STOP"):
                    log.info("STOP bit verified as TRUE")
                    state["messages"].append(AIMessage(content="Operation stopped."))
                else:
                    log.warning("STOP bit verification failed")
                    state["messages"].append(AIMessage(content="Warning: Failed to set stop command. Try again."))
                    log.warning("Failed to verify STOP bit was set")
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
    
    Checks:
    - TFR range (0.8-15.0 mL/min)
    - FRR positive
    - Temperature range (5-60°C)
    - Target volume positive
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
    print(f"[{kind}] Enter parameters…")
    while True:
        try:
            tfr = float(input("Total Flow Rate (mL/min): ").strip())
            frr = int(input("Flow Rate Ratio (integer): ").strip())
            target_volume = float(input("Target Volume (mL): ").strip())
            temperature = float(input("Temperature (°C): ").strip())
            
            while True:
                chip_id = input("Chip ID (HERRINGBONE/BAFFLE): ").strip().upper()
                if chip_id in ["HERRINGBONE", "BAFFLE"]:
                    break
                print("Please enter either HERRINGBONE or BAFFLE")
            
            while True:
                manifold = input("Manifold (SMALL/LARGE): ").strip().upper()
                if manifold in ["SMALL", "LARGE"]:
                    break
                print("Please enter either SMALL or LARGE")

            # Basic sanity checks (same ranges as agent_poc)
            msgs = []
            if not (0.8 <= tfr <= 15.0): msgs.append("TFR must be between 0.8 and 15.0 mL/min")
            if frr <= 0: msgs.append("FRR must be a positive integer")
            if not (5.0 <= temperature <= 60.0): msgs.append("Temperature must be between 5°C and 60°C")
            if target_volume <= 0: msgs.append("Target volume must be positive")
            if msgs:
                raise ValueError("; ".join(msgs))

            return InputPayload(
                tfr=tfr, frr=frr, target_volume=target_volume, temperature=temperature,
                chip_id=ChipID(chip_id), manifold=Manifold(manifold),
                mode=Mode.RUN if kind=="run" else (Mode.CLEAN if kind=="clean" else Mode.PRESSURE_TEST)
            )
        except ValueError as e:
            print(f"Error: {e}")
            if input("Try again? (y/n): ").lower() != 'y':
                raise

def _do_plc_action(kind: str) -> str:
    plc = PLCInterface()
    try:
        payload = _collect_inputs_from_cli(kind)
        plc.write_payload_to_plc(payload)
        # Poll the validation bit for up to 3 seconds
        t0 = time.time()
        ok = False
        while time.time() - t0 < 3.0:
            if plc.read_validation_bit():
                ok = True
                break
            time.sleep(0.1)
        return f"{kind.capitalize()} inputs accepted by PLC." if ok else f"{kind.capitalize()} inputs were not accepted (or timeout)."
    except Exception as e:
        return f"Error during {kind}: {str(e)}"
    finally:
        plc.disconnect()

def do_run(state: GraphState) -> GraphState:
    """Execute RUN operation with validated parameters."""
    # Check if we have the pending action (this means parameters were collected)
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Check if user confirmed (this will be handled in the REPL loop)
    state["messages"].append(AIMessage(content="Ready to start RUN operation. Type 'confirm' to proceed or 'cancel' to abort."))
    return state

def do_clean(state: GraphState) -> GraphState:
    """Execute CLEAN operation with validated parameters."""
    # Check if we have the pending action (this means parameters were collected)
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Check if user confirmed (this will be handled in the REPL loop)
    state["messages"].append(AIMessage(content="Ready to start CLEAN operation. Type 'confirm' to proceed or 'cancel' to abort."))
    return state

def do_ptest(state: GraphState) -> GraphState:
    """Execute PRESSURE TEST operation with validated parameters."""
    # Check if we have the pending action (this means parameters were collected)
    if not state.get("pending_action"):
        state["messages"].append(AIMessage(content="Error: No operation pending. Please start over."))
        return state
    
    # Check if user confirmed (this will be handled in the REPL loop)
    state["messages"].append(AIMessage(content="Ready to start PRESSURE TEST operation. Type 'confirm' to proceed or 'cancel' to abort."))
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
    
    Graph Structure:
    1. Route → Initial intent classification
    2. Input Collection → Get and validate parameters
    3. Precautions → Safety checks and confirmation
    4. Actions → Execute operations
    5. End → Terminal state
    
    State Flow:
    ROUTE → [ASK_KB → END] or [COLLECT_INPUTS → PRECAUTIONS → ACTIONS → END]
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
                    if plc.read_validation_bit():
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
# Simple REPL around the graph
# ------------------------------------------------------------------------------------

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

    state: GraphState = {"messages": [], "intent": None, "pending_action": None, "confirmed": False, "last_tool_result": None}

    print("== TAMARA Agent (LangGraph) ==")
    print("Type 'exit' to quit. Try: 'run', 'clean', 'pressure test', or ask knowledge questions.")
    while True:
        try:
            user = input("\nYou: ").strip()
            if not user:
                continue
            if user.lower() in ("exit", "quit"):
                break

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
                        # Reset command bits
                        plc.write_command_bit("COMMAND_PAUSE_PLAY", False)
                        plc.write_command_bit("COMMAND_STOP", False)
                        
                        # Set start bit
                        plc.write_command_bit("COMMAND_START", True)
                        
                        # Verify
                        start_set = plc.read_command_bit("COMMAND_START")
                        if start_set:
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