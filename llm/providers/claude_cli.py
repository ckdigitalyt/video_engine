"""Claude CLI provider (DESIGN §2.3). Flags verified against claude 2.1.283.

The prompt goes on stdin; cwd is a fresh temp dir so the repo's AGENTS.md/CLAUDE.md are
not loaded into every call. Images are copied into that dir and read via the Read tool.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llm.types import RawRequest, RawResponse

DISALLOWED = ("Task Skill SendMessage CronCreate CronDelete CronList DesignSync EnterWorktree "
              "ExitWorktree ListAgents PushNotification RemoteTrigger ScheduleWakeup "
              "WebFetch WebSearch NotebookEdit")
SYSTEM = "You are a precise assistant inside an automated pipeline. Follow the output format exactly."
_QUOTA = re.compile(r"usage limit|session limit|rate limit|limit reached|hit your .*limit", re.I)
_AUTH = re.compile(r"not logged in|please run /login|invalid api key|authentication|unauthori[sz]ed|\b40[13]\b", re.I)
_RESET = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(?UTC\)?", re.I)


def parse_reset(text: str, now: datetime | None = None) -> datetime | None:
    """'resets 7:30pm (UTC)' -> next such UTC instant, else None."""
    m = _RESET.search(text or "")
    if not m:
        return None
    now = now or datetime.now(timezone.utc)
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    t = now.replace(hour=h, minute=int(m.group(2) or 0), second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def classify(text: str) -> tuple[str, datetime | None]:
    """Envelope/stderr error text -> (error_kind, retry_at)."""
    if _AUTH.search(text):
        return "auth", None
    if _QUOTA.search(text):
        return "quota", parse_reset(text)
    return "transport", None


class ClaudeCLI:
    def __init__(self, spec: dict):
        self.bin = spec.get("bin", "claude")
        self.fallback_model = spec.get("fallback_model")

    def build_args(self, req: RawRequest, sysfile: Path, tmp: Path) -> list[str]:
        args = [self.bin, "-p", "--output-format", "json", "--model", req.model,
                "--effort", req.effort, "--no-session-persistence", "--strict-mcp-config",
                "--tools", "Read" if req.images else "",
                "--disallowedTools", DISALLOWED, "--system-prompt-file", str(sysfile)]
        if req.schema:
            args += ["--json-schema", json.dumps(req.schema)]
        if req.images:
            args += ["--add-dir", str(tmp)]
        if self.fallback_model and self.fallback_model != req.model:
            args += ["--fallback-model", self.fallback_model]
        return args

    def complete(self, req: RawRequest) -> RawResponse:
        tmp = Path(tempfile.mkdtemp(prefix="llm_claude_"))
        try:
            prompt = req.prompt
            if req.images:
                paths = []
                for i, src in enumerate(req.images):
                    dst = tmp / f"image_{i + 1}{Path(src).suffix or '.png'}"
                    shutil.copyfile(src, dst)
                    paths.append(str(dst))
                prompt += ("\n\nView each image with the Read tool before answering:\n"
                           + "\n".join(f"- {p}" for p in paths))
            sysfile = tmp / "system.md"
            sysfile.write_text(SYSTEM)
            try:
                proc = subprocess.run(self.build_args(req, sysfile, tmp), input=prompt,
                                      capture_output=True, text=True, cwd=tmp,
                                      timeout=req.timeout_s)
            except subprocess.TimeoutExpired:
                return RawResponse(error_kind="transport", error=f"timeout after {req.timeout_s:g}s")
            except OSError as e:
                return RawResponse(error_kind="transport", error=f"cannot run {self.bin}: {e}")
            return self.parse_output(proc.stdout, proc.stderr, proc.returncode)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def parse_output(stdout: str, stderr: str, returncode: int) -> RawResponse:
        try:
            env = json.loads(stdout)
        except Exception:
            env = None
        if not isinstance(env, dict):
            kind, retry_at = classify(f"{stderr}\n{stdout}")
            return RawResponse(error_kind=kind, retry_at=retry_at,
                               error=(stderr or stdout or f"exit {returncode}").strip()[:300])
        usage = dict(env.get("usage") or {})
        usage["cost_usd"] = env.get("total_cost_usd")
        text = env.get("result") or ""
        if env.get("is_error"):
            kind, retry_at = classify(f"{text}\n{stderr}")
            return RawResponse(text=text, usage=usage, error_kind=kind, retry_at=retry_at,
                               error=text.strip()[:300])
        return RawResponse(text=text, data=env.get("structured_output"), usage=usage)
