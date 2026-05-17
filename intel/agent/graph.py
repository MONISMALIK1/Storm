"""
LangGraph StateGraph for the TOW Competitive Intelligence Agent.

Graph topology:

  START
    │
  supervisor                          ← classifies task_type (no tools, low effort)
    │
    ├── daily_brief / strategy ──→ data_collector → analyzer → alert_checker → briefing_generator → strategist → END
    ├── alert_scan              ──→ alert_checker → briefing_generator → END
    ├── ingest                  ──→ data_collector (runs ingest) → alert_checker → briefing_generator → END
    └── *_query / unknown       ──→ data_collector → briefing_generator → END

Checkpointing: in-memory by default; swap to SqliteSaver for persistence.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import CIAgentState
from .nodes import (
    supervisor_node,
    data_collector_node,
    analyzer_node,
    alert_checker_node,
    briefing_generator_node,
    strategist_node,
)


# ── Routing logic ──────────────────────────────────────────────────────────────

def route_after_supervisor(state: CIAgentState) -> str:
    """Decide the first substantive node after task classification."""
    task_type = state.get("task_type", "unknown")

    if task_type == "alert_scan":
        return "alert_checker"

    # All other tasks start by collecting data
    return "data_collector"


def route_after_data_collector(state: CIAgentState) -> str:
    """
    Decide whether to run deeper analysis or jump straight to briefing.
    Full pipeline (brief / strategy) → analyzer.
    Simple queries → briefing_generator directly.
    """
    task_type = state.get("task_type", "unknown")

    if task_type in ("daily_brief", "strategy"):
        return "analyzer"

    if task_type == "ingest":
        return "alert_checker"

    # Simple queries: competitor_query, pricing_query, review_query, news_query, unknown
    return "briefing_generator"


def route_after_analyzer(state: CIAgentState) -> str:
    """Always go to alert_checker after analysis for full-pipeline tasks."""
    return "alert_checker"


def route_after_alert_checker(state: CIAgentState) -> str:
    """Always generate the briefing after alert checks."""
    return "briefing_generator"


def route_after_briefing(state: CIAgentState) -> str:
    """
    Run the strategist for full-pipeline tasks; end for everything else.
    """
    task_type = state.get("task_type", "unknown")
    if task_type in ("daily_brief", "strategy"):
        return "strategist"
    return END


# ── Graph construction ─────────────────────────────────────────────────────────

def build_graph(*, use_persistence: bool = False):
    """
    Build and compile the CI agent graph.

    Args:
        use_persistence: If True, attach a MemorySaver checkpointer so graph
                         state survives between invocations (multi-turn support).

    Returns:
        A compiled LangGraph graph ready for .invoke() / .stream().
    """
    workflow = StateGraph(CIAgentState)

    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("data_collector", data_collector_node)
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("alert_checker", alert_checker_node)
    workflow.add_node("briefing_generator", briefing_generator_node)
    workflow.add_node("strategist", strategist_node)

    # Entry point
    workflow.add_edge(START, "supervisor")

    # Conditional routing out of supervisor
    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "data_collector": "data_collector",
            "alert_checker": "alert_checker",
        },
    )

    # Conditional routing out of data_collector
    workflow.add_conditional_edges(
        "data_collector",
        route_after_data_collector,
        {
            "analyzer": "analyzer",
            "alert_checker": "alert_checker",
            "briefing_generator": "briefing_generator",
        },
    )

    # analyzer → alert_checker
    workflow.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {"alert_checker": "alert_checker"},
    )

    # alert_checker → briefing_generator
    workflow.add_conditional_edges(
        "alert_checker",
        route_after_alert_checker,
        {"briefing_generator": "briefing_generator"},
    )

    # briefing_generator → strategist or END
    workflow.add_conditional_edges(
        "briefing_generator",
        route_after_briefing,
        {
            "strategist": "strategist",
            END: END,
        },
    )

    # strategist always ends
    workflow.add_edge("strategist", END)

    # Compile with optional checkpointer
    checkpointer = MemorySaver() if use_persistence else None
    return workflow.compile(checkpointer=checkpointer)


# ── Convenience: visual diagram ────────────────────────────────────────────────

def print_graph_diagram():
    """Print a Mermaid diagram of the graph (requires graphviz extras)."""
    graph = build_graph()
    try:
        print(graph.get_graph().draw_mermaid())
    except Exception as e:
        print(f"Could not render diagram: {e}")
        print("Install: pip install langgraph[draw]")


if __name__ == "__main__":
    print_graph_diagram()
