"""Qoder (international) token usage collector.

Reads two local sources that the Qoder desktop client writes natively under
its data root ``~/.qoder`` (international build — the CN build lives in
``~/.qoder-cn`` and is *not* covered here).  Zero-intrusion: no hooks or
config needed.

1. **Run logs** ``~/.qoder/logs/runs/<run_id>/qodercli.log`` — every tool
   permission check dumps the request context (``[permission-check] ...
   context={"messages":[...]}``).  Those in-memory assistant events carry
   ``message.usage`` with the full per-request token accounting, so each
   model response can be recovered from the dump.  The same response is
   re-dumped on every later tool call, so records are deduplicated by the
   assistant event ``uuid`` (within a scan) and by the
   ``(timestamp, agent, session_id, model)`` unique index (across scans).

2. **Session transcripts** ``~/.qoder/projects/**/*.jsonl`` — Claude-Code
   style session files.  Persisted assistant events *strip* ``message.usage``
   (verified on Qoder 1.1.86), but compaction events (``type: "system"``,
   ``subtype: "compact_boundary"``) keep a full ``compactUsage`` object for
   the summarisation request, which is a real billable model call.  The
   transcripts are also the only place that maps ``sessionId → cwd``, which
   the per-request records are enriched from.

Token mapping — Qoder reports ``input_tokens`` as the *total* prompt size
(``compactUsage.context_usage_ratio == input_tokens / window``), i.e. cache
hits are included; ``cache_read_input_tokens`` / ``cache_creation_input_tokens``
are subsets.  This project's Claude-style accounting keeps them separate, so
both are split out of input and only the fresh remainder stays as input.

Known gaps (documented, deliberate):

- ``turn.finished`` / ``fork.agent.completed`` events carry token fields but
  they are always zero in current builds — not counted (and even when fixed
  they aggregate the requests already counted per-request above).
- Requests whose responses never appear in a permission-check dump (e.g. a
  pure-chat turn in ``bypassPermissions`` mode with no tool calls) have no
  plaintext usage anywhere local — the session state store encrypts its
  usage segment.  Compaction calls are still captured via source 2.
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

# Data roots of the Qoder international client (Windows native).
_QODER_RUNS_DIR = Path.home() / ".qoder" / "logs" / "runs"
_QODER_PROJECTS_DIR = Path.home() / ".qoder" / "projects"

# Cheap pre-parse filter for run logs: only lines mentioning both can
# contribute records.
_LOG_INTERESTING = ('"usage":', '"type":"assistant"')

# Head of a serialized in-memory assistant event inside a permission dump.
# Tolerates optional whitespace around JSON punctuation.
_ASSISTANT_HEAD_RE = re.compile(
    r'\{"type"\s*:\s*"assistant","uuid"\s*:\s*"([0-9a-fA-F-]{36})",'
    r'"timestamp"\s*:\s*"([^"]+)",'
    r'"message"\s*:\s*\{"id"\s*:\s*"[^"]*","type"\s*:\s*"message",'
    r'"role"\s*:\s*"assistant","model"\s*:\s*"([^"]*)"'
)
_USAGE_KEY_RE = re.compile(r'"usage"\s*:\s*\{')
# Structural tail of a dumped assistant event: the session id follows the
# request anchor.  Message *content* can quote arbitrary JSON, so a plain
# first-match on "sessionId" would let pasted paths/ids poison the field.
_SESSION_ID_RE = re.compile(
    r'"requestTokenAnchor"\s*:\s*\{[^{}]*\}\s*,\s*"sessionId"\s*:\s*"([^"]*)"'
)
_SESSION_ID_FALLBACK_RE = re.compile(r'"sessionId"\s*:\s*"([0-9a-fA-F-]{36})"')
# Structural pair on dumped user events (… ,"businessModelKey":X,"businessIdentity":{…).
_BUSINESS_MODEL_RE = re.compile(
    r'"businessModelKey"\s*:\s*"([^"]*)"\s*,\s*"businessIdentity"\s*:\s*\{'
)
_BUSINESS_MODEL_FALLBACK_RE = re.compile(r'"businessModelKey"\s*:\s*"([^"]*)"')

# Reasoning/thinking tokens, when the usage object exposes them.
_REASONING_KEYS = ("reasoning_output_tokens", "thinking_tokens", "thoughts_token_count")


def _map_usage(usage: dict) -> tuple[int, int, int, int, int]:
    """Map a Qoder usage dict to (input, output, cache_read, cache_write, reasoning).

    ``input_tokens`` is the cache-inclusive prompt total; cache hits are
    split out so ``input + cache_read + cache_write`` reconstructs the full
    prompt without double counting.
    """
    total_input = int(usage.get("input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    uncached = max(total_input - cache_read - cache_write, 0)
    reasoning = 0
    for key in _REASONING_KEYS:
        if usage.get(key):
            reasoning = int(usage[key])
            break
    return (
        uncached,
        int(usage.get("output_tokens") or 0),
        cache_read,
        cache_write,
        reasoning,
    )


def _resolve_model(message_model: str, fallback_model: str) -> str:
    """Pick the most meaningful model name.

    The API layer reports ``model: "auto"`` for routed models — in that case
    fall back to the session's selected model (``businessModelKey`` from the
    dump or the transcript's ``runtime-config`` event, e.g. ``kmodel_latest``).
    """
    model = (message_model or "").strip()
    if model and model.lower() not in ("auto", "unknown"):
        return model.lower()
    fallback = (fallback_model or "").strip()
    return fallback.lower() if fallback else "unknown"


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


def _parse_usage_at(line: str, start: int) -> dict | None:
    """Parse the JSON object whose ``{`` sits at ``start`` in ``line``."""
    try:
        obj, _ = json.JSONDecoder().raw_decode(line, start)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _extract_records_from_log_line(
    line: str,
    agent_name: str,
    session_cwd: dict[str, str],
    seen_uuids: set[str],
) -> list[TokenRecord]:
    """Mine one permission-check dump line for assistant events with usage.

    Deduplicates by assistant event uuid within the scan — the same response
    is re-dumped on every later tool permission check.  Dump events carry no
    ``cwd``; the project comes from the transcript-derived ``session_cwd``
    map.
    """
    session_m = _SESSION_ID_RE.search(line) or _SESSION_ID_FALLBACK_RE.search(line)
    session_id = session_m.group(1) if session_m else ""
    business_m = _BUSINESS_MODEL_RE.search(line) or _BUSINESS_MODEL_FALLBACK_RE.search(line)
    business_model = business_m.group(1) if business_m else ""
    cwd = session_cwd.get(session_id, "")

    records: list[TokenRecord] = []
    heads = list(_ASSISTANT_HEAD_RE.finditer(line))
    for idx, head in enumerate(heads):
        uuid, ts, message_model = head.group(1), head.group(2), head.group(3)
        if uuid in seen_uuids:
            continue
        seg_end = heads[idx + 1].start() if idx + 1 < len(heads) else len(line)
        usage_m = _USAGE_KEY_RE.search(line, head.end(), seg_end)
        if usage_m is None:
            continue
        brace_at = line.index("{", usage_m.start())
        usage = _parse_usage_at(line, brace_at)
        if usage is None:
            continue
        model = _resolve_model(message_model, business_model)
        record = _build_record(
            ts=ts,
            usage=usage,
            model=model,
            session_id=session_id,
            cwd=cwd,
            agent_name=agent_name,
            metadata={"uuid": uuid, "source": "log-context"},
        )
        if record is not None:
            records.append(record)
            seen_uuids.add(uuid)
    return records


def scan_qoder_logs(
    runs_dir: Path,
    agent_name: str,
    file_positions: dict[str, int],
    session_cwd: dict[str, str],
) -> tuple[list[TokenRecord], dict[str, int]]:
    """Scan ``qodercli.log`` run logs for new token records.

    Blocking — call via ``asyncio.to_thread``.  Returns ``(records,
    new_positions)``; the watermark map carries untouched entries forward so
    consumed files are never re-read.
    """
    records: list[TokenRecord] = []
    new_positions: dict[str, int] = dict(file_positions)
    seen_uuids: set[str] = set()

    log_files = sorted(runs_dir.rglob("qodercli.log"))
    logger.debug("Qoder: scanning %d run logs", len(log_files))

    for fpath in log_files:
        rel_key = str(fpath.relative_to(runs_dir))

        try:
            file_size = fpath.stat().st_size
        except OSError:
            continue

        start_pos = file_positions.get(rel_key, 0)
        if start_pos > file_size:
            # File was truncated or replaced — reset position.
            start_pos = 0

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
                    if not all(s in line for s in _LOG_INTERESTING):
                        continue
                    records.extend(
                        _extract_records_from_log_line(
                            line, agent_name, session_cwd, seen_uuids
                        )
                    )
        except OSError as e:
            logger.warning("Qoder: failed to read %s: %s", fpath, e)
            continue

    return records, new_positions


def scan_qoder_transcripts(
    projects_dir: Path,
    agent_name: str,
    file_positions: dict[str, int],
    file_context: dict[str, dict],
) -> tuple[list[TokenRecord], dict[str, int], dict[str, dict], dict[str, str]]:
    """Scan session transcripts for compaction usage and session→cwd mapping.

    Blocking — call via ``asyncio.to_thread``.  Returns ``(records,
    new_positions, new_context, session_cwd)``; the context map learns each
    file's model from its ``runtime-config`` event so incremental reads that
    resume mid-file still attribute records correctly.  ``session_cwd`` is
    the accumulated ``sessionId → cwd`` map across all scanned files.
    """
    records: list[TokenRecord] = []
    new_positions: dict[str, int] = dict(file_positions)
    new_context: dict[str, dict] = {k: dict(v) for k, v in file_context.items()}
    session_cwd: dict[str, str] = {}

    jsonl_files = sorted(projects_dir.rglob("*.jsonl"))
    logger.debug("Qoder: scanning %d transcripts", len(jsonl_files))

    for fpath in jsonl_files:
        rel_key = str(fpath.relative_to(projects_dir))

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

        try:
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
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Any event carrying both fields teaches the session→cwd
                    # map (parsed from event structure, not message content).
                    if data.get("sessionId") and data.get("cwd"):
                        session_cwd.setdefault(data["sessionId"], data["cwd"])

                    etype = data.get("type")
                    if etype == "runtime-config":
                        if data.get("model"):
                            ctx["model"] = data["model"]
                        continue
                    if etype != "system":
                        continue

                    usage = data.get("compactUsage")
                    if not isinstance(usage, dict):
                        continue
                    model = _resolve_model("", ctx.get("model", ""))
                    record = _build_record(
                        ts=data.get("timestamp", ""),
                        usage=usage,
                        model=model,
                        session_id=data.get("sessionId", ""),
                        cwd=data.get("cwd", ""),
                        agent_name=agent_name,
                        metadata={
                            "uuid": data.get("uuid", ""),
                            "source": "compact",
                            "credits": usage.get("credits"),
                            "modelRequestIds": data.get("modelRequestIds", []),
                        },
                    )
                    if record is not None:
                        records.append(record)
        except OSError as e:
            logger.warning("Qoder: failed to read %s: %s", fpath, e)
            continue

        new_context[rel_key] = ctx

    return records, new_positions, new_context, session_cwd


def _validated_positions(raw: object) -> dict[str, int]:
    positions: dict[str, int] = {}
    if not isinstance(raw, dict):
        return positions
    for key, pos in raw.items():
        try:
            positions[key] = int(pos)
        except (TypeError, ValueError):
            logger.debug("Qoder: dropping bad file_position for %r", key)
    return positions


class QoderCollector(BaseCollector):
    """Collect token usage from the Qoder international client's local data."""

    @property
    def name(self) -> str:
        return "qoder"

    async def collect(self) -> Sequence[TokenRecord]:
        state = self._load_state()

        log_positions = _validated_positions(state.get("log_positions"))
        transcript_positions = _validated_positions(state.get("transcript_positions"))
        transcript_context = {
            k: v for k, v in (state.get("transcript_context") or {}).items()
            if isinstance(v, dict)
        }
        session_cwd: dict[str, str] = {
            k: v for k, v in (state.get("session_cwd") or {}).items()
            if isinstance(v, str)
        }

        records: list[TokenRecord] = []
        # Transcripts first: they feed the sessionId → cwd map the log
        # records are enriched from.
        if _QODER_PROJECTS_DIR.exists():
            transcript_records, transcript_positions, transcript_context, learned_cwd = (
                await asyncio.to_thread(
                    scan_qoder_transcripts,
                    projects_dir=_QODER_PROJECTS_DIR,
                    agent_name=self.name,
                    file_positions=transcript_positions,
                    file_context=transcript_context,
                )
            )
            records.extend(transcript_records)
            session_cwd.update(learned_cwd)
        else:
            logger.debug("Qoder: projects dir not found at %s", _QODER_PROJECTS_DIR)

        if _QODER_RUNS_DIR.exists():
            log_records, log_positions = await asyncio.to_thread(
                scan_qoder_logs,
                runs_dir=_QODER_RUNS_DIR,
                agent_name=self.name,
                file_positions=log_positions,
                session_cwd=session_cwd,
            )
            records.extend(log_records)
        else:
            logger.debug("Qoder: run logs dir not found at %s", _QODER_RUNS_DIR)

        # Prune deleted-file state so it can't grow without bound.
        existing_logs = {
            str(p.relative_to(_QODER_RUNS_DIR))
            for p in _QODER_RUNS_DIR.rglob("qodercli.log")
        } if _QODER_RUNS_DIR.exists() else set()
        existing_transcripts = {
            str(p.relative_to(_QODER_PROJECTS_DIR))
            for p in _QODER_PROJECTS_DIR.rglob("*.jsonl")
        } if _QODER_PROJECTS_DIR.exists() else set()

        # Always persist watermarks even without new records: this preserves
        # truncation resets and prevents re-scanning already-consumed files.
        self._save_state(
            {
                "log_positions": {
                    k: v for k, v in log_positions.items() if k in existing_logs
                },
                "transcript_positions": {
                    k: v
                    for k, v in transcript_positions.items()
                    if k in existing_transcripts
                },
                "transcript_context": {
                    k: v
                    for k, v in transcript_context.items()
                    if k in existing_transcripts
                },
                "session_cwd": session_cwd,
            }
        )

        logger.info("Qoder: collected %d new records", len(records))
        return records
