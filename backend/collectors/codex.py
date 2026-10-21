"""Codex CLI token usage collector.

Reads the session rollout files that Codex writes under
``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`` (one append-only JSONL per
session).  Two event shapes carry token usage depending on CLI version:

- ``token_usage_record`` (top-level type, newer CLIs): one record per model
  response with a ``usage`` object in OpenAI Responses semantics.
- ``event_msg`` with ``payload.type == "token_count"`` (older CLIs): the
  ``info.last_token_usage`` object holds the same usage shape for the most
  recent response.

Both shapes are never mixed within one file: whichever appears first wins and
the other is ignored, so a response is never counted twice.

Token mapping — Codex counts cached tokens inside ``input_tokens`` (OpenAI
Responses semantics), while this project's Claude-style accounting keeps them
separate, so ``cached_input_tokens`` becomes cache_read and only the remainder
stays input.  ``reasoning_output_tokens`` is a subset of output and is stored
in the reasoning column for display.

Session context (session id, cwd, model) comes from ``session_meta`` /
``turn_context`` lines and is cached per file in collector state, so an
incremental read that resumes mid-file still attributes records correctly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path

from backend.collectors.base import BaseCollector
from backend.db.models import TokenRecord, project_from_cwd
from backend.pricing.model_pricing import calculate_cost

logger = logging.getLogger(__name__)

# Default rollout directory for Codex CLI
_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# rollout-2026-10-22T01-35-44-01a15f88-800a-7ad1-8d7b-36323f9fb50a.jsonl
_FILENAME_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

# Cheap pre-parse filter: only lines mentioning these substrings can affect
# usage or context.  Matches both compact and spaced JSON separators.
_INTERESTING = ("token_usage_record", "token_count", "session_meta", "turn_context")


def _map_usage(usage: dict) -> tuple[int, int, int, int, int]:
    """Map a Codex usage dict to (input, output, cache_read, cache_write, reasoning)."""
    total_input = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cached_input_tokens") or 0)
    uncached = max(total_input - cached, 0)
    return (
        uncached,
        int(usage.get("output_tokens") or 0),
        cached,
        int(usage.get("cache_write_input_tokens") or 0),
        int(usage.get("reasoning_output_tokens") or 0),
    )


def _build_record(
    ts: str,
    usage: dict,
    model: str,
    session_id: str,
    cwd: str,
    agent_name: str,
    metadata: dict,
) -> TokenRecord | None:
    input_tokens, output_tokens, cache_read, cache_write, reasoning = _map_usage(usage)
    if input_tokens == 0 and output_tokens == 0 and cache_read == 0 and cache_write == 0:
        return None

    model = model.lower()
    cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)
    raw = json.dumps({"cwd": cwd, **metadata}, ensure_ascii=False)

    return TokenRecord(
        timestamp=ts,
        agent=agent_name,
        model=model,
        session_id=session_id,
        project=project_from_cwd(cwd),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
        cost_usd=cost,
        raw_data=raw,
    )


def _session_id_from_filename(name: str) -> str:
    m = _FILENAME_UUID_RE.search(name)
    return m.group(0) if m else ""


def scan_codex_directory(
    sessions_dir: Path,
    agent_name: str,
    file_positions: dict[str, int],
    file_context: dict[str, dict],
) -> tuple[list[TokenRecord], dict[str, int], dict[str, dict]]:
    """Scan Codex rollout files for new token records.

    Blocking — call via ``asyncio.to_thread``.  Returns
    ``(records, new_positions, new_context)``; both watermark maps carry
    untouched entries forward so consumed files are never re-read.
    """
    records: list[TokenRecord] = []
    new_positions: dict[str, int] = dict(file_positions)
    new_context: dict[str, dict] = {k: dict(v) for k, v in file_context.items()}

    jsonl_files = sorted(sessions_dir.rglob("*.jsonl"))
    logger.debug("Codex: scanning %d jsonl files", len(jsonl_files))

    for fpath in jsonl_files:
        rel_key = str(fpath.relative_to(sessions_dir))

        try:
            file_size = fpath.stat().st_size
        except OSError:
            continue

        start_pos = file_positions.get(rel_key, 0)
        ctx = dict(new_context.get(rel_key, {}))
        if start_pos > file_size:
            # File was truncated or replaced — reset position and context.
            start_pos = 0
            ctx = {}
        if not ctx.get("session_id"):
            ctx["session_id"] = _session_id_from_filename(fpath.name)

        try:
            # Binary mode keeps tell() a plain byte offset (see jsonl_utils).
            with open(fpath, "rb") as f:
                if start_pos > 0:
                    f.seek(start_pos)

                while True:
                    raw_line = f.readline()
                    if not raw_line:
                        break
                    if not raw_line.endswith(b"\n"):
                        # Writer is mid-append; pick the tail up next cycle.
                        break
                    new_positions[rel_key] = f.tell()

                    line = raw_line.decode("utf-8", errors="replace")
                    if not any(s in line for s in _INTERESTING):
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = data.get("type")
                    payload = data.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue

                    if etype == "session_meta":
                        sid = payload.get("session_id") or payload.get("id")
                        if sid:
                            ctx["session_id"] = sid
                        if payload.get("cwd"):
                            ctx["cwd"] = payload["cwd"]
                        if payload.get("cli_version"):
                            ctx["cli_version"] = payload["cli_version"]
                        provenance = payload.get("provenance") or {}
                        if isinstance(provenance, dict) and provenance.get("model"):
                            ctx.setdefault("model", provenance["model"])
                    elif etype == "turn_context":
                        if payload.get("model"):
                            ctx["model"] = payload["model"]
                        if payload.get("cwd"):
                            ctx["cwd"] = payload["cwd"]
                    elif etype == "token_usage_record":
                        ctx["has_records"] = True
                        record = _build_record(
                            ts=data.get("timestamp", ""),
                            usage=payload.get("usage") or {},
                            model=ctx.get("model", "unknown"),
                            session_id=payload.get("session_id") or ctx.get("session_id", ""),
                            cwd=ctx.get("cwd", ""),
                            agent_name=agent_name,
                            metadata={
                                "turn_id": payload.get("turn_id", ""),
                                "response_id": payload.get("response_id", ""),
                                "cli_version": ctx.get("cli_version", ""),
                            },
                        )
                        if record is not None:
                            records.append(record)
                    elif etype == "event_msg" and payload.get("type") == "token_count":
                        if ctx.get("has_records"):
                            continue
                        info = payload.get("info") or {}
                        record = _build_record(
                            ts=data.get("timestamp", ""),
                            usage=info.get("last_token_usage") or {},
                            model=ctx.get("model", "unknown"),
                            session_id=ctx.get("session_id", ""),
                            cwd=ctx.get("cwd", ""),
                            agent_name=agent_name,
                            metadata={"cli_version": ctx.get("cli_version", "")},
                        )
                        if record is not None:
                            records.append(record)
        except OSError as e:
            logger.warning("Codex: failed to read %s: %s", fpath, e)
            continue

        new_context[rel_key] = ctx

    return records, new_positions, new_context


class CodexCollector(BaseCollector):
    """Collect token usage from Codex CLI session rollout files."""

    @property
    def name(self) -> str:
        return "codex"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()

        sessions_dir = _CODEX_SESSIONS_DIR
        if not sessions_dir.exists():
            logger.debug("Codex: sessions dir not found at %s", sessions_dir)
            return []

        # Discover current files first so we can prune deleted-file state.
        existing_keys: set[str] = set()
        for fpath in sessions_dir.rglob("*.jsonl"):
            try:
                existing_keys.add(str(fpath.relative_to(sessions_dir)))
            except OSError:
                continue

        validated_positions: dict[str, int] = {}
        for key, pos in state.get("file_positions", {}).items():
            try:
                validated_positions[key] = int(pos)
            except (TypeError, ValueError):
                logger.debug("Codex: dropping bad file_position for %r", key)

        validated_context = {
            k: v for k, v in state.get("file_context", {}).items() if isinstance(v, dict)
        }

        records, new_positions, new_context = await asyncio.to_thread(
            scan_codex_directory,
            sessions_dir=sessions_dir,
            agent_name=self.name,
            file_positions=validated_positions,
            file_context=validated_context,
        )

        pruned_positions = {k: v for k, v in new_positions.items() if k in existing_keys}
        pruned_context = {k: v for k, v in new_context.items() if k in existing_keys}

        # Always persist watermarks even without new records: this preserves
        # truncation resets and prevents re-scanning already-consumed files.
        self._save_state(
            {
                "file_positions": pruned_positions,
                "file_context": pruned_context,
            }
        )

        logger.info("Codex: collected %d new records", len(records))
        return records
