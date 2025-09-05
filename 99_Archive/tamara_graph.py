# tamara_graph.py
from __future__ import annotations
from typing import TypedDict, Literal, Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, AIMessage
from IPython.display import Image  # for plotting only (per your instruction)

# Reuse the PLC wrapper & validations
from plc_tool import (
    PLCWriter, InputPayload, ChipID, Manifold, Mode, static_validate
)

# You already build a history-aware retriever + QA chain in agent_poc; we inject that here.  # :contentReference[oaicite:22]{index=22}

# ----------------------------- Agent state ------------------------------------

class AgentState(TypedDict, total=False):
    user_input: str
    intent: Literal["qa", "run", "clean", "pressure_test", "status"]
    params: Dict[str, Any]             # raw params from UI/chat (tfr, frr, temp, ...)
    payload: InputPayload              # normalized inputs for PLC
    operator_confirmed: bool           # pre-run checklist
    result: str                        # final text answer
    messages: List[Any]                # optional history for your RAG chain

# ----------------------------- Router -----------------------------------------

def route_intent(state: AgentState) -> Dict[str, Any]:
    text = (state.get("user_input") or "").lower()
    if any(k in text for k in ["clean", "flush"]):
        return {"intent": "clean"}
    if "pressure test" in text or "pressure-test" in text:
        return {"intent": "pressure_test"}
    if any(k in text for k in ["run", "formulate", "start batch"]):
        return {"intent": "run"}
    if any(k in text for k in ["status", "state"]):
        return {"intent": "status"}
    return {"intent": "qa"}

# ----------------------------- RAG QA Node ------------------------------------

def rag_qa_node(state: AgentState, rag_chain) -> Dict[str, Any]:
    """Use your existing history-aware retrieval + QA chain to answer."""
    question = state["user_input"]
    history = state.get("messages", [])
    out = rag_chain.invoke({"input": question, "chat_history": history})
    return {"result": out["answer"]}

# ----------------------------- Param Extraction -------------------------------

def extract_params(state: AgentState) -> Dict[str, Any]:
    """
    Normalize raw params (from chat or caller) into an InputPayload.
    In production, you’ll parse from NLU or structured UI form.
    """
    p = state.get("params", {})
    payload = InputPayload(
        tfr=float(p["tfr"]),
        frr=int(p["frr"]),
        target_volume=float(p["target_volume"]),
        temperature=float(p["temperature"]),
        chip_id=ChipID(p.get("chip_id", "HERRINGBONE").upper()),
        manifold=Manifold(p.get("manifold", "SMALL").upper()),
        mode=Mode(state["intent"].upper() if state["intent"] in ["run","clean","pressure_test"] else "RUN"),
    )
    return {"payload": payload}

# ----------------------------- Static Validation ------------------------------

def static_check(state: AgentState) -> Dict[str, Any]:
    ok, msgs = static_validate(state["payload"])
    if not ok:
        return {"result": "Validation errors: " + "; ".join(msgs)}
    return {}

# ----------------------------- Operator Checklist -----------------------------

PRECAUTIONS = (
    "Before proceeding, please confirm:\n"
    "1) Aqueous and solvent fluids are loaded in the reservoir.\n"
    "2) The gasket and chip are correctly seated.\n"
    "3) The lid is closed and latched.\n"
    "4) A collection vial is installed.\n"
    "Reply 'confirm' to continue or describe what’s missing."
)

def operator_checklist(state: AgentState) -> Dict[str, Any]:
    if state.get("operator_confirmed"):
        return {}
    # Ask once; the app should collect the next user message and set operator_confirmed=True.
    return {"result": PRECAUTIONS}

# ----------------------------- PLC Write & Validate ---------------------------

def plc_write(state: AgentState, plc: PLCWriter) -> Dict[str, Any]:
    plc.write_payload(state["payload"])
    return {}

def plc_validate(state: AgentState, plc: PLCWriter) -> Dict[str, Any]:
    if plc.poll_validation(timeout_s=3.0, interval_s=0.1):
        return {"result": "Inputs accepted by PLC."}
    return {"result": "Inputs rejected by PLC (validation failed). Check machine panel/logs."}

# ----------------------------- Graph Builder ----------------------------------

def build_tamara_graph(rag_chain, plc: PLCWriter):
    g = StateGraph(AgentState)

    # Nodes
    g.add_node("router", lambda s: route_intent(s))
    g.add_node("rag_qa", lambda s: rag_qa_node(s, rag_chain))
    g.add_node("extract_params", extract_params)
    g.add_node("static_check", static_check)
    g.add_node("operator_checklist", operator_checklist)
    g.add_node("plc_write", lambda s: plc_write(s, plc))
    g.add_node("plc_validate", lambda s: plc_validate(s, plc))

    # Edges
    g.add_edge(START, "router")

    # Branch from router
    def next_after_router(state: AgentState) -> str:
        m = state["intent"]
        return {"qa": "rag_qa",
                "run": "extract_params",
                "clean": "extract_params",
                "pressure_test": "extract_params",
                "status": "rag_qa"}.get(m, "rag_qa")

    g.add_conditional_edges("router", next_after_router, {
        "rag_qa": "rag_qa",
        "extract_params": "extract_params",
    })

    # Run/Clean/Pressure-test path
    g.add_edge("extract_params", "static_check")

    def ok_or_fail(state: AgentState) -> str:
        # if static_check put an error message into result, stop
        return "operator_checklist" if not state.get("result") else END

    g.add_conditional_edges("static_check", ok_or_fail, {
        "operator_checklist": "operator_checklist",
        END: END,
    })

    def confirmed_or_wait(state: AgentState) -> str:
        # If not confirmed yet, stop now (frontend should prompt user, then call again with operator_confirmed=True)
        return "plc_write" if state.get("operator_confirmed") else END

    g.add_conditional_edges("operator_checklist", confirmed_or_wait, {
        "plc_write": "plc_write",
        END: END,
    })

    g.add_edge("plc_write", "plc_validate")
    g.add_edge("rag_qa", END)
    g.add_edge("plc_validate", END)

    # Compile
    app = g.compile()
    return app

# ----------------------------- Example: render graph --------------------------

if __name__ == "__main__":
    # Dummy stubs you already have in agent_poc:
    rag_chain = None  # inject your create_retrieval_chain(...) here  # :contentReference[oaicite:23]{index=23}
    plc = PLCWriter(connect_on_init=False)  # or True in production

    graph = build_tamara_graph(rag_chain, plc)

    # Per your note: plot the graph as a PNG:
    Image(graph.get_graph().draw_png())

    with open("./7_Tamara_Agent/images/graph.png", "wb") as f:
        f.write(graph.get_graph().draw_png())
