#!/usr/bin/env python3
"""
tamara_graph_V1.py — Clean, runnable LangGraph agent for TAMARA

- Routes between RAG Q&A and PLC actions (Run / Clean / Pressure Test).
- Collects parameters, runs local sanity checks, sends to PLC, polls CRUNCH_VALID,
  then prompts for pre-run confirmation before starting.
- Supports 'pause', 'play' (resume), 'stop', and 'status' commands at any time.
- Keeps PLC IP protected: only whitelisted variables are read/written via plc_tool.py.

Run:
  $ python tamara_graph_V1.py            # REPL
  $ python tamara_graph_V1.py --draw     # also saves ./images/tamara_graph.png and previews if IPython is present
"""

from __future__ import annotations
import os
import time
import argparse
import logging
import logging.handlers
from typing import TypedDict, List, Literal, Optional, Any, Tuple
from dotenv import load_dotenv

# --- Optional display for graph image ------------------------------------------------
try:
    from IPython.display import Image, display  # noqa: F401
except Exception:
    Image = None  # type: ignore

# --- Minimal LangChain / LangGraph set ------------------------------------------------
try:
    from langchain_community.vectorstores import Chroma
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    from langchain_core.documents import Document
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain.chains import create_history_aware_retriever, create_retrieval_chain
    from langchain.chains.combine_documents import create_stuff_documents_chain
    from langgraph.graph import StateGraph, END
except Exception as e:
    raise SystemExit(
        "This script needs langgraph, langchain, langchain-openai, chromadb.\n"
        "Install: pip install 'langgraph>=0.2' 'langchain>=0.2' 'langchain-openai' 'chromadb'"
    ) from e

# --- Local PLC tool (locked-down interface) -------------------------------------------
from plc_tool import PLCInterface, InputPayload, ChipID, Manifold, Mode  # uses only the whitelisted DB9 fields
# (Your plc_tool.py already implements write_payload_to_plc, read_validation_bit, write_command_bit, read_command_bit, read_status)

# --- Env & logging -------------------------------------------------------------------
load_dotenv()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/tamara_graph_V1.log',
            maxBytes=1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        )
    ]
)
log = logging.getLogger("__name__")

# -------------------------------------------------------------------------------------
# RAG helpers
# -------------------------------------------------------------------------------------

def _persist_dir() -> str:
    # prefer explicit env; otherwise use a local db path
    candidates = [
        os.getenv("KB_CHROMA_DIR"),
        os.path.join(SCRIPT_DIR, "db/chroma_db_with_metadata_Knowledge_base"),
    ]
    for c in candidates:
        if c and os.path.isdir(c) and os.listdir(c):
            return c
    # default directory (created if missing)
    default_dir = os.path.join(SCRIPT_DIR, "db/chroma_db_with_metadata_Knowledge_base")
    os.makedirs(default_dir, exist_ok=True)
    return default_dir

def _txt_dir() -> str:
    return os.getenv("KB_TXT_DIR", os.path.join(SCRIPT_DIR, "Knowledge_base", "txt"))

def _open_or_seed_vectorstore() -> Optional[Chroma]:
    """
    Tries to open an existing Chroma persist dir; if none exists, seeds a tiny store.
    If OPENAI_API_KEY is missing, returns None and RAG will gracefully degrade.
    """
    if not os.getenv("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY not set — RAG will run in fallback mode.")
        return None

    persist = _persist_dir()
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # Open existing store if present
    if os.path.isdir(persist) and os.listdir(persist):
        return Chroma(persist_directory=persist, embedding_function=embeddings)

    # Otherwise, seed a tiny store from txt files or a single safety doc
    docs: List[Document] = []
    txt_dir = _txt_dir()
    if os.path.isdir(txt_dir):
        for root, _dirs, files in os.walk(txt_dir):
            for fn in files:
                if fn.lower().endswith((".txt", ".md")):
                    path = os.path.join(root, fn)
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            docs.append(Document(page_content=f.read(), metadata={"source": path}))
                    except Exception as e:
                        log.warning("Failed to read %s: %s", path, e)
    if not docs:
        docs = [Document(
            page_content=(
                "TAMARA is a microfluidic system with Run, Clean, and Pressure Test modes. "
                "Keep the lid closed; follow the pre-run checklist."
            ),
            metadata={"source": "seed"}
        )]

    vs = Chroma.from_documents(documents=docs, embedding=embeddings, persist_directory=persist)
    vs.persist()
    return vs

def build_rag_chain():
    """
    Builds the history-aware retriever + QA chain. If anything fails, raises and the
    caller will fallback to heuristic responses.
    """
    vectorstore = _open_or_seed_vectorstore()
    if vectorstore is None:
        raise RuntimeError("RAG unavailable (missing OPENAI_API_KEY).")

    retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 15})
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # (1) History-aware question reformulation
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Given a chat history and the latest user question which might reference the history, "
         "reformulate the question to be fully self-contained. Do NOT answer; only rewrite if needed."),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)

    # (2) QA chain constrained to context
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a TAMARA assistant. Provide precise, technical, step-by-step answers and include safety "
         "considerations when relevant. Use ONLY the provided context.\n\n{context}"),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

    # (3) retrieval-augmented pipeline
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    return rag_chain, llm

class RAGManager:
    """Lazy initializer so we don't fail on import if OPENAI_API_KEY is missing."""
    def __init__(self):
        self._chain = None
        self._llm = None

    def ensure_initialized(self):
        if self._chain is None:
            self._chain, self._llm = build_rag_chain()
        return self._chain, self._llm

rag_manager = RAGManager()

# -------------------------------------------------------------------------------------
# Graph state + router
# -------------------------------------------------------------------------------------

class GraphState(TypedDict):
    messages: List[Any]               # alternating HumanMessage/AIMessage
    intent: Optional[Literal["ask_kb", "run", "clean", "ptest", "other"]]
    pending_action: Optional[str]     # "run"|"clean"|"ptest" when waiting for confirmation
    confirmed: bool
    last_tool_result: Optional[str]

ROUTE_HINT = (
    "Classify the user's message into: ask_kb, run, clean, ptest, or other. Return just the label."
)

def _heuristic_route(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["run", "formulate", "mix"]):
        return "run"
    if "clean" in t:
        return "clean"
    if "pressure" in t and "test" in t:
        return "ptest"
    return "ask_kb"

def route(state: GraphState, *, llm=None) -> GraphState:
    """Handles control commands immediately; otherwise sets intent for conditional edges."""
    last = state["messages"][-1]
    user_text = last.content.lower() if isinstance(last, HumanMessage) else str(last).lower()
    log.info("Routing: '%s' (pending_action=%s)", user_text, state.get("pending_action"))

    # Control commands (terminate the turn after executing)
    if "pause" in user_text:
        plc = PLCInterface()
        try:
            status_code = plc.read_status()
            if status_code == 2:  # Running
                plc.write_command_bit("COMMAND_PAUSE_PLAY", True)
                if plc.read_command_bit("COMMAND_PAUSE_PLAY"):
                    state["messages"].append(AIMessage(content="Operation paused. Say 'play' to resume."))
                else:
                    state["messages"].append(AIMessage(content="Warning: Failed to set pause. Try again."))
            else:
                state["messages"].append(AIMessage(content="Cannot pause — operation is not running. Try 'status'."))  # not running
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error pausing: {e}"))
        finally:
            plc.disconnect()
        state["intent"] = "other"
        return state

    if "play" in user_text or "resume" in user_text:
        plc = PLCInterface()
        try:
            status_code = plc.read_status()
            # We clear the pause bit irrespective, but this guard mirrors intended UX
            plc.write_command_bit("COMMAND_PAUSE_PLAY", False)
            if not plc.read_command_bit("COMMAND_PAUSE_PLAY"):
                state["messages"].append(AIMessage(content="Operation resumed."))
            else:
                state["messages"].append(AIMessage(content="Warning: Failed to resume. Try again."))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error resuming: {e}"))
        finally:
            plc.disconnect()
        state["intent"] = "other"
        return state

    if "stop" in user_text:
        plc = PLCInterface()
        try:
            plc.write_command_bit("COMMAND_STOP", True)
            if plc.read_command_bit("COMMAND_STOP"):
                state["messages"].append(AIMessage(content="Operation stopped."))
            else:
                state["messages"].append(AIMessage(content="Warning: Failed to stop. Try again."))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error stopping: {e}"))
        finally:
            plc.disconnect()
        state["intent"] = "other"
        return state

    if "status" in user_text:
        plc = PLCInterface()
        try:
            sc = plc.read_status()
            status_map = {
                0: "Initializing",
                1: "Ready",
                2: "Running",
                3: "Cleaning",
                4: "Pressure Test",
                5: "Safe Purge",
                6: "Faulted",
                7: "Reset",
                8: "E-Stop"
            }
            extra = ""
            if sc == 2: extra = " — use 'pause' to pause, 'stop' to stop."
            state["messages"].append(AIMessage(content=f"TAMARA Status: {status_map.get(sc, f'Unknown ({sc})')}{extra}"))
        except Exception as e:
            state["messages"].append(AIMessage(content=f"Error reading status: {e}"))
        finally:
            plc.disconnect()
        state["intent"] = "other"
        return state

    # Normal routing
    state["intent"] = _heuristic_route(user_text)
    return state

def _route_selector(state: GraphState) -> str:
    """Returns the next node key for add_conditional_edges."""
    label = state.get("intent")
    if label == "ask_kb":
        return "ask_kb"
    if label == "run":
        return "collect_run_inputs"
    if label == "clean":
        return "collect_clean_inputs"
    if label == "ptest":
        return "collect_ptest_inputs"
    return END  # includes 'other' (e.g., pause/play/stop/status)

# -------------------------------------------------------------------------------------
# Pre-check text & local validation
# -------------------------------------------------------------------------------------

PRECHECK_TEXT = (
    "Before we proceed, please confirm the pre‑run checks:\n"
    "1) Required fluids are loaded in the reservoirs per protocol.\n"
    "2) Chip is correctly seated & oriented; gasket in place; manifold connected.\n"
    "3) Lid is CLOSED; lines secure; drain bottle in place.\n"
    "4) Pressure supply within spec; a recent Pressure Test passed if applicable.\n"
    "Type 'confirm' to continue or 'cancel' to abort."
)

def static_validate(payload: InputPayload) -> Tuple[bool, List[str]]:
    msgs: List[str] = []
    ok = True
    if not (0.8 <= payload.tfr <= 15.0):
        msgs.append("TFR must be between 0.8 and 15.0 mL/min"); ok = False
    if payload.frr <= 0:
        msgs.append("FRR must be a positive integer"); ok = False
    if not (5.0 <= payload.temperature <= 60.0):
        msgs.append("Temperature must be between 5°C and 60°C"); ok = False
    if payload.target_volume <= 0:
        msgs.append("Target volume must be positive"); ok = False
    return ok, msgs

def _collect_inputs_from_cli(kind: str) -> InputPayload:
    print(f"[{kind}] Enter parameters…")
    while True:
        try:
            tfr = float(input("Total Flow Rate (mL/min): ").strip())
            frr = int(input("Flow Rate Ratio (integer): ").strip())
            target_volume = float(input("Target Volume (mL): ").strip())
            temperature = float(input("Temperature (°C): ").strip())

            chip_id = None
            while chip_id not in ("HERRINGBONE", "BAFFLE"):
                chip_id = input("Chip ID (HERRINGBONE/BAFFLE): ").strip().upper()

            manifold = None
            while manifold not in ("SMALL", "LARGE"):
                manifold = input("Manifold (SMALL/LARGE): ").strip().upper()

            mode = Mode.RUN if kind == "run" else (Mode.CLEAN if kind == "clean" else Mode.PRESSURE_TEST)
            payload = InputPayload(
                tfr=tfr, frr=frr, target_volume=target_volume, temperature=temperature,
                chip_id=ChipID(chip_id), manifold=Manifold(manifold), mode=mode
            )
            # local sanity check (early feedback)
            ok, msgs = static_validate(payload)
            if not ok:
                raise ValueError("; ".join(msgs))
            return payload
        except ValueError as e:
            print(f"Error: {e}")
            if input("Try again? (y/n): ").strip().lower() != "y":
                raise

# -------------------------------------------------------------------------------------
# Graph nodes
# -------------------------------------------------------------------------------------

def answer_with_rag(state: GraphState) -> GraphState:
    # Prepare user text first to avoid UnboundLocal in exceptions
    last = state["messages"][-1]
    user_text = last.content if isinstance(last, HumanMessage) else str(last)
    try:
        chain, _ = rag_manager.ensure_initialized()
        result = chain.invoke({"input": user_text, "chat_history": [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage))][:-1]})
        state["messages"].append(AIMessage(content=result.get("answer", "")))
    except Exception as e:
        log.warning("RAG unavailable, falling back. Reason: %s", e)
        state["messages"].append(AIMessage(
            content=f"(RAG offline) I can still help with controls. "
                    f"Ask about run/clean/pressure test, or type 'status'.")
        )
    return state

def _collect_and_validate_with_plc(state: GraphState, kind: str) -> GraphState:
    try:
        # 1) collect inputs
        payload = _collect_inputs_from_cli(kind)

        # 2) static validation
        ok, msgs = static_validate(payload)
        if not ok:
            state["messages"].append(AIMessage(content="Input validation failed:\n- " + "\n- ".join(msgs)))
            return state

        # 3) send to PLC + poll CRUNCH_VALID
        plc = PLCInterface()
        try:
            plc.write_payload_to_plc(payload)
            t0 = time.time()
            accepted = False
            while time.time() - t0 < 3.0:
                if plc.read_validation_bit():
                    accepted = True
                    break
                time.sleep(0.1)
        finally:
            plc.disconnect()

        if accepted:
            state["messages"].append(AIMessage(content="Parameters accepted by PLC. Proceeding with safety checks..."))
            state["input_payload"] = payload  # stash for action nodes
            state["pending_action"] = kind
        else:
            state["messages"].append(AIMessage(
                content="Parameters rejected by PLC (or timeout). Please adjust to within PLC limits."
            ))
    except Exception as e:
        state["messages"].append(AIMessage(content=f"Error collecting/sending parameters: {e}"))
    return state

def collect_run_inputs(state: GraphState) -> GraphState:
    return _collect_and_validate_with_plc(state, "run")

def collect_clean_inputs(state: GraphState) -> GraphState:
    return _collect_and_validate_with_plc(state, "clean")

def collect_ptest_inputs(state: GraphState) -> GraphState:
    return _collect_and_validate_with_plc(state, "ptest")

def show_precautions(state: GraphState) -> GraphState:
    state["messages"].append(AIMessage(content=PRECHECK_TEXT))
    return state

def do_run(state: GraphState) -> GraphState:
    if "input_payload" not in state:
        state["messages"].append(AIMessage(content="Error: No validated input parameters found."))
        return state
    state["messages"].append(AIMessage(content="Ready to start RUN. Type 'confirm' to proceed or 'cancel' to abort."))
    return state

def do_clean(state: GraphState) -> GraphState:
    if "input_payload" not in state:
        state["messages"].append(AIMessage(content="Error: No validated input parameters found."))
        return state
    state["messages"].append(AIMessage(content="Ready to start CLEAN. Type 'confirm' to proceed or 'cancel' to abort."))
    return state

def do_ptest(state: GraphState) -> GraphState:
    if "input_payload" not in state:
        state["messages"].append(AIMessage(content="Error: No validated input parameters found."))
        return state
    state["messages"].append(AIMessage(content="Ready to start PRESSURE TEST. Type 'confirm' to proceed or 'cancel' to abort."))
    return state

# -------------------------------------------------------------------------------------
# Graph assembly
# -------------------------------------------------------------------------------------

def build_graph():
    g = StateGraph(GraphState)

    # nodes
    g.add_node("route", route)
    g.add_node("ask_kb", answer_with_rag)
    g.add_node("collect_run_inputs", collect_run_inputs)
    g.add_node("collect_clean_inputs", collect_clean_inputs)
    g.add_node("collect_ptest_inputs", collect_ptest_inputs)
    g.add_node("precautions", show_precautions)
    g.add_node("do_run", do_run)
    g.add_node("do_clean", do_clean)
    g.add_node("do_ptest", do_ptest)

    # entry
    g.set_entry_point("route")

    # routing out of 'route'
    g.add_conditional_edges(
        "route",
        _route_selector,
        {
            "ask_kb": "ask_kb",
            "collect_run_inputs": "collect_run_inputs",
            "collect_clean_inputs": "collect_clean_inputs",
            "collect_ptest_inputs": "collect_ptest_inputs",
            END: END,
        },
    )

    # after input collection → show precautions iff we have a payload
    def _after_collect(state: GraphState) -> str:
        return "precautions" if "input_payload" in state else END

    for name in ("collect_run_inputs", "collect_clean_inputs", "collect_ptest_inputs"):
        g.add_conditional_edges(name, _after_collect, {"precautions": "precautions", END: END})

    # from precautions → action node based on pending_action
    def _which_action(state: GraphState) -> str:
        pa = state.get("pending_action")
        return {"run": "do_run", "clean": "do_clean", "ptest": "do_ptest"}.get(pa, END)

    g.add_conditional_edges("precautions", _which_action, {"do_run": "do_run", "do_clean": "do_clean", "do_ptest": "do_ptest", END: END})

    # terminal edges
    g.add_edge("ask_kb", END)
    g.add_edge("do_run", END)
    g.add_edge("do_clean", END)
    g.add_edge("do_ptest", END)

    return g.compile()

# -------------------------------------------------------------------------------------
# Simple REPL
# -------------------------------------------------------------------------------------

def repl(draw: bool = False):
    app = build_graph()

    if draw:
        try:
            img_bytes = app.get_graph().draw_png()
            img_path = os.path.join(SCRIPT_DIR, "images", "tamara_graph.png")
            os.makedirs(os.path.dirname(img_path), exist_ok=True)
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            if Image:
                display(Image(img_bytes))  # matches your "Image(graph.get_graph().draw_png())" requirement
            else:
                print(f"Saved graph to {img_path}")
        except Exception as e:
            log.error("Could not render graph: %s", e)

    state: GraphState = {"messages": [], "intent": None, "pending_action": None, "confirmed": False, "last_tool_result": None}

    print("== TAMARA Agent (LangGraph) ==")
    print("Type 'exit' to quit. Try: 'run', 'clean', 'pressure test', 'pause', 'play', 'stop', 'status', or ask knowledge questions.")

    while True:
        try:
            user = input("\nYou: ").strip()
            if not user:
                continue
            if user.lower() in ("exit", "quit"):
                break

            state["messages"].append(HumanMessage(content=user))
            state = app.invoke(state)

            # emit the latest AI turn (if any)
            last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
            if last_ai:
                print(f"\nAI: {last_ai.content}")

            # confirmation handshake for start
            if state.get("pending_action") and last_ai and "Type 'confirm' to proceed" in last_ai.content:
                confirm_input = input("\nType 'confirm' to start or 'cancel' to abort: ").strip().lower()
                if confirm_input == "confirm":
                    action = state["pending_action"]
                    plc = PLCInterface()
                    try:
                        # reset bits then start
                        plc.write_command_bit("COMMAND_PAUSE_PLAY", False)
                        plc.write_command_bit("COMMAND_STOP", False)
                        plc.write_command_bit("COMMAND_START", True)
                        if plc.read_command_bit("COMMAND_START"):
                            print(f"\nAI: {action.upper()} operation started.")
                            state["confirmed"] = True
                            state["pending_action"] = None
                        else:
                            print(f"\nAI: Failed to start {action}.")
                    except Exception as e:
                        print(f"\nAI: Error starting {action}: {e}")
                    finally:
                        plc.disconnect()
                else:
                    print("\nAI: Operation cancelled.")
                    state["pending_action"] = None
                    state["confirmed"] = False

        except KeyboardInterrupt:
            print("\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            log.exception("Error in REPL loop")
            print(f"\nError: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TAMARA LangGraph agent")
    parser.add_argument("--draw", action="store_true", help="Render the graph to images/tamara_graph.png")
    args = parser.parse_args()
    repl(draw=args.draw)
