"""OpenAPI spec loading, endpoint indexing, and bounded $ref resolution.

The Buildium spec is ~2.7MB: 298 paths, 462 operations, 519 schemas. Generating
one MCP tool per operation would swamp the model's context before it did any
work, so instead we index the spec and expose search/describe/call. Schemas are
resolved lazily and depth-capped — describe_endpoint returns something a model
can actually read, not a 40-level inlined object graph.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# Depth at which we stop inlining nested schemas and emit a pointer instead.
MAX_SCHEMA_DEPTH = 6

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split into lowercase tokens, also breaking camelCase and snake_case."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    return _TOKEN_RE.findall(spaced.lower())


def _flatten_all_of(node: dict[str, Any]) -> dict[str, Any]:
    """Collapse `allOf` composition into the object it describes.

    Every request body in this spec is wrapped as
    `{"allOf": [{"$ref": "...PostMessage"}]}`. Left alone, `describe_endpoint`
    hands a model a schema whose top level has no `properties` and no
    `required` — the fields it needs are one level down, inside a single-member
    list. Models read that as "no required fields" and send empty bodies.

    Merging is only attempted when every member is a plain object schema.
    `oneOf` and `anyOf` are genuine alternatives and are never touched.
    """
    members = node.get("allOf")
    if not isinstance(members, list) or not members:
        return node
    if not all(isinstance(m, dict) for m in members):
        return node
    # A member carrying its own composition keyword is not safely mergeable.
    if any(k in m for m in members for k in ("oneOf", "anyOf", "not")):
        return node

    merged: dict[str, Any] = {k: v for k, v in node.items() if k != "allOf"}
    properties: dict[str, Any] = dict(merged.get("properties") or {})
    required: list[str] = list(merged.get("required") or [])

    for member in members:
        for key, value in member.items():
            if key == "properties" and isinstance(value, dict):
                properties.update(value)
            elif key == "required" and isinstance(value, list):
                required.extend(r for r in value if r not in required)
            elif key not in merged:
                merged[key] = value

    if properties:
        merged["properties"] = properties
        merged.setdefault("type", "object")
    if required:
        merged["required"] = required
    return merged


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    operation_id: str
    tags: tuple[str, ...]
    summary: str
    description: str
    deprecated: bool = False
    _search_tokens: frozenset[str] = field(repr=False, default=frozenset())

    @property
    def key(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def brief(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "method": self.method.upper(),
            "path": self.path,
            "operationId": self.operation_id,
            "tags": list(self.tags),
            "summary": self.summary,
        }
        if self.deprecated:
            # Surfaced structurally, not left buried in prose. 16 operations
            # are scheduled to start returning 410 Gone, and a caller picking
            # one out of search results needs to see that at the point of
            # choosing rather than after building a call around it.
            out["deprecated"] = True
            out["deprecation_notice"] = self.deprecation_notice()
        return out

    def deprecation_notice(self) -> str:
        """The replacement and retirement date, lifted out of the description."""
        match = re.search(
            r"deprecated and will start returning \*\*(\d+ Gone)\*\* on ([0-9-]+)\."
            r"\s*Use `([^`]+)` instead",
            self.description,
        )
        if match:
            return (
                f"Starts returning {match.group(1)} on {match.group(2)}; "
                f"replacement is {match.group(3)}. Until then this endpoint is "
                "still live, and existing records are not necessarily migrated "
                "— if the replacement comes back empty, this one is still where "
                "the data is. Do not abandon it on the strength of this notice "
                "alone."
            )
        return "Deprecated; see the endpoint description."


class SpecIndex:
    """Searchable index over the Buildium OpenAPI document."""

    def __init__(self, spec_path: Path):
        self.spec_path = spec_path
        with spec_path.open("r", encoding="utf-8") as fh:
            self.spec: dict[str, Any] = json.load(fh)
        self._schemas: dict[str, Any] = self.spec.get("components", {}).get("schemas", {})
        self.endpoints: list[Endpoint] = []
        self._by_key: dict[str, Endpoint] = {}
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        for path, path_item in self.spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for method in HTTP_METHODS:
                op = path_item.get(method)
                if not isinstance(op, dict):
                    continue
                tags = tuple(op.get("tags") or ())
                summary = (op.get("summary") or "").strip()
                description = (op.get("description") or "").strip()
                operation_id = op.get("operationId") or ""
                deprecated = bool(op.get("deprecated"))
                tokens = frozenset(
                    _tokenize(path)
                    + _tokenize(summary)
                    + _tokenize(operation_id)
                    + [t for tag in tags for t in _tokenize(tag)]
                    + [method]
                )
                ep = Endpoint(
                    method=method,
                    path=path,
                    operation_id=operation_id,
                    tags=tags,
                    summary=summary,
                    description=description,
                    deprecated=deprecated,
                    _search_tokens=tokens,
                )
                self.endpoints.append(ep)
                self._by_key[ep.key] = ep

    # -- lookup ------------------------------------------------------------

    @property
    def tags(self) -> list[str]:
        seen: dict[str, int] = {}
        for ep in self.endpoints:
            for tag in ep.tags:
                seen[tag] = seen.get(tag, 0) + 1
        return [f"{name} ({count})" for name, count in sorted(seen.items())]

    def get(self, method: str, path: str) -> Endpoint | None:
        return self._by_key.get(f"{method.upper()} {path}")

    def _match_template(self, method: str, concrete: str) -> Endpoint | None:
        """Match a concrete path against a templated spec path.

        '/v1/vendors/categories/2474' matches '/v1/vendors/categories/{categoryId}'.
        Without this, any call naming a specific record would look unknown.
        """
        segments = [s for s in concrete.strip("/").split("/") if s]
        want = method.lower()
        for ep in self.endpoints:
            if ep.method != want:
                continue
            template = [s for s in ep.path.strip("/").split("/") if s]
            if len(template) != len(segments):
                continue
            if all(
                t.startswith("{") or t.lower() == s.lower()
                for t, s in zip(template, segments)
            ):
                return ep
        return None

    def resolve_path(self, method: str, path: str) -> tuple[Endpoint, str] | None:
        """Resolve a caller-supplied path to (spec endpoint, concrete request path).

        The endpoint is the templated spec entry used for validation and schema
        lookup; the second element is the actual path to send, with real IDs
        preserved. Tolerates a missing /v1 prefix and a trailing slash.
        """
        candidates = [path, path.rstrip("/")]
        if not path.startswith("/v1"):
            candidates += [f"/v1{path}", f"/v1/{path.lstrip('/')}"]

        seen: set[str] = set()
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            ep = self.get(method, cand)
            if ep:
                return ep, cand
        for cand in candidates:
            ep = self._match_template(method, cand)
            if ep:
                return ep, cand
        return None

    def search(self, query: str, limit: int = 25, method: str | None = None) -> list[Endpoint]:
        """Rank endpoints by token overlap with the query.

        Exact substring hits on the path are boosted, since callers usually know
        roughly what resource they want ("lease transactions", "work orders").
        """
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        q_lower = query.lower().strip()
        scored: list[tuple[float, Endpoint]] = []

        for ep in self.endpoints:
            if method and ep.method != method.lower():
                continue
            overlap = sum(1 for t in q_tokens if t in ep._search_tokens)
            if not overlap:
                continue
            score = overlap / len(q_tokens)
            if q_lower in ep.path.lower():
                score += 1.5
            if q_lower in ep.summary.lower():
                score += 0.75
            # Prefer shallower paths: /v1/leases beats /v1/leases/{id}/notes/{nid}
            score -= ep.path.count("/") * 0.02
            # A deprecated endpoint still ranks — it is often where the data
            # actually lives until Buildium migrates it — but never above an
            # equally good live one.
            if ep.deprecated:
                score -= 0.3
            scored.append((score, ep))

        scored.sort(key=lambda pair: (-pair[0], pair[1].path, pair[1].method))
        return [ep for _, ep in scored[:limit]]

    # -- schema resolution -------------------------------------------------

    def _deref(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            return {"unresolved$ref": ref}
        node: Any = self.spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                return {"unresolved$ref": ref}
            node = node[part]
        return node if isinstance(node, dict) else {"unresolved$ref": ref}

    def resolve(
        self,
        node: Any,
        depth: int = 0,
        seen: frozenset[str] = frozenset(),
    ) -> Any:
        """Inline $refs up to MAX_SCHEMA_DEPTH, breaking cycles."""
        if isinstance(node, list):
            return [self.resolve(item, depth, seen) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            name = ref.rsplit("/", 1)[-1]
            if ref in seen:
                return {"$ref": name, "note": "circular reference, not expanded"}
            if depth >= MAX_SCHEMA_DEPTH:
                return {"$ref": name, "note": "depth limit; call describe_schema for detail"}
            return self.resolve(self._deref(ref), depth + 1, seen | {ref})

        out: dict[str, Any] = {}
        for key, value in node.items():
            # Descriptions in this spec are long marketing prose; keep them short.
            if key == "description" and isinstance(value, str) and len(value) > 300:
                out[key] = value[:300] + "…"
            else:
                out[key] = self.resolve(value, depth, seen)
        return _flatten_all_of(out)

    def schema(self, name: str) -> dict[str, Any] | None:
        raw = self._schemas.get(name)
        if raw is None:
            return None
        return self.resolve(raw)

    def schema_names(self, query: str = "", limit: int = 50) -> list[str]:
        names = sorted(self._schemas)
        if query:
            q = query.lower()
            names = [n for n in names if q in n.lower()]
        return names[:limit]

    # -- describe ----------------------------------------------------------

    def describe(self, method: str, path: str) -> dict[str, Any] | None:
        resolved = self.resolve_path(method, path)
        if resolved is None:
            return None
        ep, _concrete = resolved

        path_item = self.spec["paths"][ep.path]
        op = path_item[ep.method]

        params: list[dict[str, Any]] = []
        # Path-level params apply to every operation on that path.
        for raw in list(path_item.get("parameters", [])) + list(op.get("parameters", [])):
            p = self.resolve(raw)
            params.append(
                {
                    "name": p.get("name"),
                    "in": p.get("in"),
                    "required": bool(p.get("required")),
                    "schema": p.get("schema"),
                    "description": p.get("description"),
                }
            )

        body = None
        rb = op.get("requestBody")
        if rb:
            rb = self.resolve(rb)
            content = rb.get("content", {})
            media = content.get("application/json") or next(iter(content.values()), {})
            body = {
                "required": bool(rb.get("required")),
                "schema": media.get("schema"),
            }

        responses: dict[str, Any] = {}
        for code, resp in (op.get("responses") or {}).items():
            if not str(code).startswith("2"):
                continue
            resp = self.resolve(resp)
            content = resp.get("content", {})
            media = content.get("application/json") or next(iter(content.values()), {})
            responses[str(code)] = {
                "description": resp.get("description"),
                "schema": media.get("schema"),
            }

        return {
            "method": ep.method.upper(),
            "path": ep.path,
            "operationId": ep.operation_id,
            "tags": list(ep.tags),
            "deprecated": ep.deprecated,
            **({"deprecation_notice": ep.deprecation_notice()} if ep.deprecated else {}),
            "summary": ep.summary,
            "description": ep.description[:1000] if ep.description else "",
            "parameters": params,
            "requestBody": body,
            "responses": responses,
        }


@lru_cache(maxsize=4)
def load_index(spec_path: Path) -> SpecIndex:
    return SpecIndex(spec_path)
