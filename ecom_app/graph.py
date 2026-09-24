"""Assembles the LangGraph state machine for the e-commerce photoshoot.

Flow (interrupt points marked *):

    parse_description -> load_inputs -> analyze_images -> build_profile -> clarify_loop* ->
    decide_model -+-> generate_persona -> persona_review* --(regenerate)--+
                  |        ^                                              |
                  |        +----------------------------------------------+
                  +-> plan_shots -> present_plan* -> prepare_payloads ->
                  generate_images -> review_results -> finalize -> END

(decide_model jumps straight to plan_shots when no model is needed or the
seller supplied their own model photo.)
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import make_nodes


class EcomState(TypedDict, total=False):
    # ── inputs (set by the driver) ──────────────────────────────────────
    image_paths: list[str]
    description: str                # one free-text seller description
    product_info: dict              # filled by parse_description (or passed directly)
    num_images: Optional[int]
    style: str
    target_platform: str
    model_policy: str               # "auto" | "ask"
    user_model_photo: Optional[str]
    auto_approve: bool
    dry_run: bool
    comfyui_url: str
    output_dir: str
    # ── derived along the way ───────────────────────────────────────────
    slug: str
    image_analyses: list[dict]
    product_profile: dict
    clarification_qa: list[dict]
    needs_model: bool
    model_source: str
    persona: Optional[dict]
    persona_feedback: str
    persona_attempts: int
    persona_approved: bool
    shot_plan: list[dict]
    plan_approved: bool
    upload_map: dict
    jobs: list[dict]
    results: list[dict]
    review_notes: list[dict]
    regen_attempts: int
    manifest_path: str


def _model_router(state: EcomState) -> str:
    if state.get("needs_model") and state.get("model_source") == "generate":
        return "generate_persona"
    return "plan_shots"


def _persona_router(state: EcomState) -> str:
    approved = state.get("persona_approved") or state.get("persona_attempts", 0) >= 3
    return "plan_shots" if approved else "generate_persona"


def _plan_router(state: EcomState) -> str:
    return "prepare_payloads" if state.get("plan_approved") else "finalize"


def build_graph(llm: Any, comfy: Any):
    """Compiles the graph with an in-memory checkpointer (needed for interrupts)."""
    nodes = make_nodes(llm, comfy)
    g = StateGraph(EcomState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "parse_description")
    g.add_edge("parse_description", "load_inputs")
    g.add_edge("load_inputs", "analyze_images")
    g.add_edge("analyze_images", "build_profile")
    g.add_edge("build_profile", "clarify_loop")
    g.add_edge("clarify_loop", "decide_model")
    g.add_conditional_edges(
        "decide_model",
        _model_router,
        {"generate_persona": "generate_persona", "plan_shots": "plan_shots"},
    )
    g.add_edge("generate_persona", "persona_review")
    g.add_conditional_edges(
        "persona_review",
        _persona_router,
        {"generate_persona": "generate_persona", "plan_shots": "plan_shots"},
    )
    g.add_edge("plan_shots", "present_plan")
    g.add_conditional_edges(
        "present_plan",
        _plan_router,
        {"prepare_payloads": "prepare_payloads", "finalize": "finalize"},
    )
    g.add_edge("prepare_payloads", "generate_images")
    g.add_edge("generate_images", "review_results")
    g.add_edge("review_results", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=MemorySaver())
