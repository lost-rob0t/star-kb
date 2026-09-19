from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .projection import prolog_term


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    predicate: str


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: tuple[Tool, ...] = (
    Tool("kb_document", "Get document metadata and selected canonical JSON paths.", _object({"id": {"type": "string"}}, ["id"]), "tool_document"),
    Tool("kb_neighbors", "Traverse direct semantic relations and StarIntel references around an entity.", _object({"id": {"type": "string"}, "direction": {"type": "string", "enum": ["out", "in", "both"]}}, ["id"]), "tool_neighbors"),
    Tool("kb_path", "Find a bounded evidence-bearing graph path between two StarIntel IDs.", _object({"source": {"type": "string"}, "target": {"type": "string"}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 12}}, ["source", "target"]), "tool_path"),
    Tool("kb_explain", "Explain a relation using its relation document, evidence, sources, qualifiers, and provenance.", _object({"relation_id": {"type": "string"}}, ["relation_id"]), "tool_explain_relation"),
    Tool("kb_timeline", "Return temporal observations connected to an entity or document.", _object({"id": {"type": "string"}}, ["id"]), "tool_timeline"),
    Tool("kb_contradictions", "Find explicit positive/negated relation conflicts and evidence contradiction links.", _object({"id": {"type": "string"}}, ["id"]), "tool_contradictions"),
    Tool("kb_compare", "Compare two entities by outgoing predicates, references, and canonical scalar values.", _object({"left": {"type": "string"}, "right": {"type": "string"}}, ["left", "right"]), "tool_compare"),
    Tool("kb_sources", "List provenance and source records supporting a document.", _object({"id": {"type": "string"}}, ["id"]), "tool_sources"),
    Tool("kb_why_not", "Explain which bounded conditions for a requested direct relation are missing or contradicted.", _object({"subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"}}, ["subject", "predicate", "object"]), "tool_why_not"),
    Tool("kb_values", "Read arbitrary canonical JSON scalar paths from the lossless projection, including additive fields unknown to semantic indexes.", _object({"id": {"type": "string"}, "path_prefix": {"type": "string"}}, ["id", "path_prefix"]), "tool_values"),
    Tool("kb_referrers", "Find documents and JSON paths that reference a StarIntel ID.", _object({"target": {"type": "string"}}, ["target"]), "tool_referrers"),
    Tool("kb_packet", "Build a compact reasoning packet for an entity: document identity, neighbors, timeline, sources/provenance, and contradictions.", _object({"id": {"type": "string"}, "max_items": {"type": "integer", "minimum": 1, "maximum": 100}}, ["id"]), "tool_packet"),
    Tool("kb_route_reasoning", "Choose a StarIntel reasoning capability route without exposing engine-specific syntax.", _object({"task": {"type": "string"}, "needs_uncertainty": {"type": "boolean"}, "needs_recursion": {"type": "boolean"}, "needs_explanation": {"type": "boolean"}, "bulk_graph": {"type": "boolean"}}, ["task"]), "tool_route_reasoning"),
)


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
        for tool in TOOLS
    ]


def compile_tool_call(name: str, arguments: dict[str, Any]) -> str:
    tool = next((item for item in TOOLS if item.name == name), None)
    if tool is None:
        raise KeyError(f"unknown tool: {name}")
    required = tool.parameters.get("required", [])
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"missing required arguments for {name}: {', '.join(missing)}")
    unknown = set(arguments) - set(tool.parameters["properties"])
    if unknown:
        raise ValueError(f"unknown arguments for {name}: {', '.join(sorted(unknown))}")

    if name == "kb_document":
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['id'])}, Result)"
    if name == "kb_neighbors":
        direction = arguments.get("direction", "both")
        if direction not in {"out", "in", "both"}:
            raise ValueError("direction must be out, in, or both")
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['id'])}, {prolog_term(direction)}, Result)"
    if name == "kb_path":
        depth = int(arguments.get("max_depth", 4))
        if not 1 <= depth <= 12:
            raise ValueError("max_depth must be between 1 and 12")
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['source'])}, {prolog_term(arguments['target'])}, {depth}, Result)"
    if name == "kb_explain":
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['relation_id'])}, Result)"
    if name in {"kb_timeline", "kb_contradictions", "kb_sources"}:
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['id'])}, Result)"
    if name == "kb_values":
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['id'])}, {prolog_term(arguments['path_prefix'])}, Result)"
    if name == "kb_referrers":
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['target'])}, Result)"
    if name == "kb_packet":
        max_items = int(arguments.get("max_items", 25))
        if not 1 <= max_items <= 100:
            raise ValueError("max_items must be between 1 and 100")
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['id'])}, {max_items}, Result)"
    if name == "kb_compare":
        return f"star_reasoning:{tool.predicate}({prolog_term(arguments['left'])}, {prolog_term(arguments['right'])}, Result)"
    if name == "kb_why_not":
        return (
            f"star_reasoning:{tool.predicate}({prolog_term(arguments['subject'])}, "
            f"{prolog_term(arguments['predicate'])}, {prolog_term(arguments['object'])}, Result)"
        )
    if name == "kb_route_reasoning":
        flags = [
            arguments.get("needs_uncertainty", False),
            arguments.get("needs_recursion", False),
            arguments.get("needs_explanation", False),
            arguments.get("bulk_graph", False),
        ]
        return (
            f"star_reasoning:{tool.predicate}({prolog_term(arguments['task'])}, "
            + ", ".join(prolog_term(flag) for flag in flags)
            + ", Result)"
        )
    raise AssertionError(name)
