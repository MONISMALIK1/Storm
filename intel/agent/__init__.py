"""
intel.agent — LangGraph-powered Competitive Intelligence Agent for TOW.

Usage:
    from intel.agent.graph import build_graph

    graph = build_graph()
    result = graph.invoke({
        "task_input": "Generate today's executive brief",
        "task_type": "",
        "collected_data": {},
        "analysis": {},
        "alerts": [],
        "briefing": "",
        "recommendations": [],
        "metadata": {},
        "messages": [],
    })
    print(result["briefing"])

CLI:
    python -m intel.agent.cli
    python -m intel.agent.cli --task "What are the top 3 competitor threats this week?"
"""

from .graph import build_graph
from .state import CIAgentState

__all__ = ["build_graph", "CIAgentState"]
