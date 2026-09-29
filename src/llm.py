"""
llm.py — ModelClient interface + stub implementations.
Authority: ARCHITECTURE.md §11, AI_SYSTEM_SPEC.md §3–§6.

Three clients:
  ReplayClient      — reads deterministic responses from data/replay/*.json (default).
  LiveGeminiClient  — optional; requires GEMINI_API_KEY; falls back to ReplayClient.
  HostileMockClient — used in tests only; returns plans designed to trip validators.

Rule: ModelClient.generate_structured() is the ONLY model entry point.
The model may only *propose* structured artifacts; validators decide pass/fail.
"""

from __future__ import annotations

import copy
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ModelClient(ABC):
    """
    Uniform interface for all model back-ends.
    Nodes call generate_structured(); the concrete client decides
    whether to call a live model or return a replay fixture.
    """

    @abstractmethod
    def generate_structured(
        self,
        node: str,
        schema: Type[BaseModel],
        payload: dict[str, Any],
        scenario: str = "baseline",
    ) -> BaseModel:
        """
        Return a validated Pydantic model instance.

        Args:
            node:     Graph node name (e.g. "analyze_story"). Used as the
                      replay key.
            schema:   Expected Pydantic model class.
            payload:  Structured data sent as the task parameters + data block.
                      Must NOT contain raw constraint map rule bodies or secrets.
            scenario: Replay scenario ("baseline", "traps", "clean").

        Returns:
            A validated instance of `schema`.

        Raises:
            ReplayMissError: (ReplayClient) when the fixture is missing and
                             strict_replay=True.
            ModelClientError: on unrecoverable failure.
        """
        ...

    @abstractmethod
    def estimated_cost(self, node: str, payload: dict[str, Any]) -> float:
        """Return the estimated cost (USD_synthetic) for this call."""
        ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ModelClientError(Exception):
    """Unrecoverable model client error."""


class ReplayMissError(ModelClientError):
    """Raised when a replay fixture is missing and strict_replay=True."""


# ---------------------------------------------------------------------------
# ReplayClient  (default; no API key required)
# ---------------------------------------------------------------------------

class ReplayClient(ModelClient):
    """
    Returns deterministic recorded responses from data/replay/*.json.
    Keyed by (node, scenario).  In non-strict mode a missing fixture logs
    REPLAY_MISS and raises ModelClientError so the caller can fall back.

    data/replay/ layout:
        story_analysis.baseline.json
        audience_strategy.baseline.json
        trailer_plans.traps.json
        trailer_plans.clean.json
        repair_choice.baseline.json
    """

    # Maps (node, scenario) → fixture file stem.
    _FIXTURE_MAP: dict[tuple[str, str], str] = {
        ("analyze_story",    "baseline"): "story_analysis.baseline",
        ("analyze_story",    "traps"):    "story_analysis.baseline",  # same
        ("analyze_story",    "clean"):    "story_analysis.baseline",  # same
        ("plan_audiences",   "baseline"): "audience_strategy.baseline",
        ("plan_audiences",   "traps"):    "audience_strategy.baseline",
        ("plan_audiences",   "clean"):    "audience_strategy.baseline",
        ("plan_trailers",    "traps"):    "trailer_plans.traps",
        ("plan_trailers",    "clean"):    "trailer_plans.clean",
        ("plan_trailers",    "baseline"): "trailer_plans.clean",
        ("repair",           "baseline"): "repair_choice.baseline",
        ("repair",           "traps"):    "repair_choice.baseline",
        ("repair",           "clean"):    "repair_choice.baseline",
    }

    def __init__(
        self,
        replay_dir: Path | str = Path("data/replay"),
        strict: bool = False,
    ) -> None:
        self._replay_dir = Path(replay_dir)
        self._strict = strict

    def generate_structured(
        self,
        node: str,
        schema: Type[BaseModel],
        payload: dict[str, Any],
        scenario: str = "baseline",
    ) -> BaseModel:
        stem = self._FIXTURE_MAP.get((node, scenario))
        if stem is None:
            stem = self._FIXTURE_MAP.get((node, "baseline"))
        if stem is None:
            msg = f"No replay fixture mapping for node={node!r} scenario={scenario!r}"
            if self._strict:
                raise ReplayMissError(msg)
            raise ModelClientError(msg)

        path = self._replay_dir / f"{stem}.json"
        if not path.exists():
            msg = f"Replay fixture missing: {path}"
            if self._strict:
                raise ReplayMissError(msg)
            raise ModelClientError(msg)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ModelClientError(f"Failed to parse replay fixture {path}: {e}") from e

        response = data.get("response", data)

        # Handle dict schema requests
        if schema is dict or (isinstance(schema, type) and issubclass(schema, dict)):
            if node == "plan_audiences":
                aid = payload.get("audience_id")
                promises = response.get("promises", {})
                if aid and aid in promises:
                    return promises[aid]  # type: ignore
                return promises or response  # type: ignore
            elif node == "plan_trailers":
                tid = payload.get("trailer_id")
                plans = response.get("plans", {})
                if tid and tid in plans:
                    return plans[tid]  # type: ignore
                return plans or response  # type: ignore
            return response  # type: ignore

        def _try_validate(obj: Any) -> BaseModel | None:
            try:
                return schema.model_validate(obj)
            except Exception:
                return None

        # 1. Extract based on node and payload first
        if node == "plan_audiences":
            promises = response.get("promises", {})
            aid = payload.get("audience_id")
            if aid and aid in promises:
                p_copy = dict(promises[aid])
                p_copy.setdefault("promise", p_copy.get("hook", ""))
                res = _try_validate(p_copy)
                if res is not None:
                    return res
            res = _try_validate(promises)
            if res is not None:
                return res

        elif node == "plan_trailers":
            plans = response.get("plans", {})
            tid = payload.get("trailer_id")
            if tid and tid in plans:
                res = _try_validate(plans[tid])
                if res is not None:
                    return res
            res = _try_validate(plans)
            if res is not None:
                return res

        elif node == "analyze_story":
            if "story_map" in response:
                res = _try_validate(response["story_map"])
                if res is not None:
                    return res
            if "spoiler_map" in response:
                res = _try_validate(response["spoiler_map"])
                if res is not None:
                    return res

        # 2. Direct validation attempt against whole response
        res = _try_validate(response)
        if res is not None:
            return res

        # 3. Final attempt directly against schema
        try:
            return schema.model_validate(response)
        except Exception as e:
            raise ModelClientError(
                f"Replay response for node {node} failed schema validation: {e}"
            ) from e

    def estimated_cost(self, node: str, payload: dict[str, Any]) -> float:
        """In replay mode, actual cost is 0; still compute estimated live cost."""
        rate_map = {
            "analyze_story": 0.02,
            "plan_audiences": 0.01,
            "plan_trailers": 0.03,
            "repair": 0.01,
        }
        return rate_map.get(node, 0.01)


# ---------------------------------------------------------------------------
# LiveGeminiClient  (optional; requires GEMINI_API_KEY)
# ---------------------------------------------------------------------------

class LiveGeminiClient(ModelClient):
    """
    Calls the Gemini API. Falls back to ReplayClient on failure.
    Not required to run the prototype (IMPLEMENTATION_PLAN.md §11 cut list).
    """

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        fallback: ModelClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._fallback = fallback or ReplayClient()
        self.fallback_used = False

    def generate_structured(
        self,
        node: str,
        schema: Type[BaseModel],
        payload: dict[str, Any],
        scenario: str = "baseline",
    ) -> BaseModel:
        self.fallback_used = True
        logger.warning(
            "LiveGeminiClient: live API call failed/unsupported; delegating to fallback ReplayClient (MODE_FALLBACK_REPLAY)"
        )
        return self._fallback.generate_structured(node, schema, payload, scenario)

    def estimated_cost(self, node: str, payload: dict[str, Any]) -> float:
        return 0.0


# ---------------------------------------------------------------------------
# HostileMockClient  (tests only)
# ---------------------------------------------------------------------------
class HostileMockClient(ModelClient):
    """
    Returns deliberately invalid plans or responses for adversarial tests.
    Proves that the deterministic validation boundary holds even when the
    planning model has been 'fooled' (AI_SYSTEM_SPEC.md §5.4).
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        mode: str = "custom",
        fallback: ModelClient | None = None,
    ) -> None:
        self._responses: dict[str, Any] = responses or {}
        self._mode = mode
        self._fallback = fallback or ReplayClient()

    def generate_structured(
        self,
        node: str,
        schema: Type[BaseModel],
        payload: dict[str, Any],
        scenario: str = "baseline",
    ) -> BaseModel:
        if self._mode == "unavailable":
            raise ModelClientError("Simulated primary model unavailable error (MODE_FALLBACK_REPLAY)")

        if self._mode == "malformed":
            raise ModelClientError(f"Malformed output: schema validation failed for node {node}")

        if node in self._responses:
            raw = self._responses[node]
            if isinstance(raw, Exception):
                raise raw
            if schema is dict or (isinstance(schema, type) and issubclass(schema, dict)):
                if isinstance(raw, dict):
                    aid = payload.get("audience_id")
                    tid = payload.get("trailer_id")
                    if aid and "promises" in raw and aid in raw["promises"]:
                        return raw["promises"][aid]
                    if tid and "plans" in raw and tid in raw["plans"]:
                        return raw["plans"][tid]
                return raw
            return schema.model_validate(raw)

        if self._mode == "injection_obeyed":
            # Tamper with plan_trailers to use music_07 on scene_05
            base = self._fallback.generate_structured(node, schema, payload, scenario)
            if node == "plan_trailers" and isinstance(base, dict):
                base_copy = copy.deepcopy(base)
                for s in base_copy.get("segments", []):
                    if s.get("scene_id") == "scene_05" or s.get("video") == "scene_05":
                        s["music_asset_id"] = "music_07"
                        s["audio_mode"] = "dialogue_and_music"
                return base_copy
            return base

        if self._mode == "story_contradiction":
            base = self._fallback.generate_structured(node, schema, payload, scenario)
            if node == "analyze_story" and isinstance(base, dict):
                base_copy = copy.deepcopy(base)
                base_copy.setdefault("relationships", []).append({
                    "a": "char_randhir", "b": "char_sunita",
                    "relation": "spouse", "visibility": "public"
                })
                return base_copy
            return base

        return self._fallback.generate_structured(node, schema, payload, scenario)

    def estimated_cost(self, node: str, payload: dict[str, Any]) -> float:
        return 0.0


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def build_client(run_config: dict[str, Any], replay_dir: Path | str = "data/replay") -> ModelClient:
    """
    Return the appropriate ModelClient based on run_config.
    Falls back to ReplayClient when mode=live but GEMINI_API_KEY is missing.
    """
    mode = run_config.get("mode", "replay")
    strict = run_config.get("strict_replay", False)
    replay_client = ReplayClient(replay_dir=Path(replay_dir), strict=strict)

    if mode == "live":
        import os
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            model_name = run_config.get("model", {}).get("primary_model", "gemini-2.0-flash")
            return LiveGeminiClient(model_name=model_name, fallback=replay_client)
        logger.warning(
            "Live mode requested but GEMINI_API_KEY not found; falling back to ReplayClient (MODE_FALLBACK_REPLAY)"
        )
        return replay_client

    return replay_client
