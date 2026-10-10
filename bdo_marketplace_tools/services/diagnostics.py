"""Bounded, best-effort support reports. Never collect request headers or cookies."""

import hashlib
import json
import platform
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile

from bdo_marketplace_tools.version import APP_VERSION


DIAGNOSTIC_REPORT_LIMIT = 20
DIAGNOSTIC_BODY_LIMIT = 2 * 1024 * 1024
DIAGNOSTIC_TEXT_LIMIT = 16 * 1024
DIAGNOSTIC_MARKER = "Diagnostic file: "
_SECRET_KEY = re.compile(
    r"cookie|password|passwd|token|authorization|secret|session|otp|email|"
    r"account|userid|username|steamid|ticket|assertion|credential", re.I
)
_SAFE_HEADERS = {"content-type", "content-length", "retry-after", "date", "server", "x-request-id"}
_SAFE_PARAMETERS = {"keyType", "mainKey", "mainCategory", "subCategory", "buyMainKey",
                    "buySubKey", "buyPrice", "buyCount"}


def safe_url(value):
    try:
        parts = urlsplit(str(value))
        return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))
    except ValueError:
        return "[invalid URL]"


def redact_text(value):
    text = str(value)
    text = re.sub(r"https?://[^\s\"'<>]+", lambda match: safe_url(match[0]), text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", text)
    text = re.sub(r"(?im)\b(?:set-cookie|cookie|authorization)\s*:[^\r\n]*", "[redacted header]", text)
    text = re.sub(
        r"(?i)(\b[\w.-]*(?:cookie|authorization|password|passwd|token|secret|session|otp|ticket|assertion)[\w.-]*"
        r"\b[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;<>]+)",
        r"\1[redacted]", text,
    )
    # Public gateway HTML can contain challenge tokens; omit executable scripts and form values.
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "[script omitted]", text)
    text = re.sub(r"(?is)(\b(?:value|content)\s*=\s*)(\"[^\"]*\"|'[^']*')", r'\1"[redacted]"', text)
    return text


def safe_parameters(parameters):
    if not isinstance(parameters, dict):
        return {}
    return {key: redact_json(value) for key, value in parameters.items() if key in _SAFE_PARAMETERS}


def redact_json(value):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _SECRET_KEY.search(str(key).replace("_", ""))
                else redact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def exception_details(exception):
    """Capture every chained exception and stack frame, without locals or source text."""
    chain, seen = [], set()
    while exception is not None and id(exception) not in seen and len(chain) < 16:
        seen.add(id(exception))
        frames, trace = [], exception.__traceback__
        while trace is not None and len(frames) < 64:
            code = trace.tb_frame.f_code
            frames.append({"file": Path(code.co_filename).name, "line": trace.tb_lineno,
                           "function": code.co_name})
            trace = trace.tb_next
        chain.append({"type": type(exception).__name__, "message": redact_text(exception)[:DIAGNOSTIC_TEXT_LIMIT], "frames": frames})
        exception = exception.__cause__ or (None if exception.__suppress_context__ else exception.__context__)
    return chain


class DiagnosticRecorder:
    def __init__(self, directory, *, report_limit=DIAGNOSTIC_REPORT_LIMIT, body_limit=DIAGNOSTIC_BODY_LIMIT):
        self.directory = Path(directory)
        self.report_limit = max(1, report_limit)
        self.body_limit = max(1, body_limit)
        self._lock = threading.Lock()
        self._recent = {}
        self.last_failure = None

    def record(self, message, *, exception=None, response=None, method=None, url=None, parameters=None):
        """Return a ZIP path, or None on failure. Identical reports reuse a file."""
        try:
            with self._lock:
                return self._record(message, exception, response, method, url, parameters)
        except Exception as exc:
            # Logging must never change monitoring/purchase behavior or recurse into itself.
            self.last_failure = f"{type(exc).__name__}: {redact_text(exc)}"
            return None

    def _record(self, message, exception, response, method, url, parameters):
        timestamp = datetime.now(timezone.utc).isoformat()
        report = {"format_version": 1, "app_version": APP_VERSION, "python": platform.python_version(),
                  "platform": platform.system(), "first_seen_utc": timestamp, "last_seen_utc": timestamp,
                  "occurrences": 1, "message": redact_text(message)[:DIAGNOSTIC_TEXT_LIMIT], "exceptions": exception_details(exception)}
        body, member = None, None
        if response is not None:
            request = getattr(response, "_diagnostic_request", {})
            if not isinstance(request, dict):
                request = {}
            method = method or request.get("method")
            url = url or request.get("url") or getattr(response, "url", "")
            parameters = parameters or request.get("parameters")
            content = getattr(response, "content", b"")
            if not isinstance(content, bytes):
                content = b""
            headers = getattr(response, "headers", {})
            headers = headers if isinstance(headers, dict) else dict(headers)
            report["response"] = {
                "status_code": getattr(response, "status_code", None),
                "headers": {key: redact_text(value) for key, value in headers.items() if key.lower() in _SAFE_HEADERS},
                "body_bytes": len(content), "body_sha256": hashlib.sha256(content).hexdigest(),
                "truncated": len(content) > self.body_limit,
            }
            prefix = content[:self.body_limit]
            public_stock = urlsplit(str(url)).path == "/Trademarket/GetWorldMarketList"
            try:
                parsed = json.loads(prefix)
                json_body = True
            except (ValueError, UnicodeError):
                parsed = None
                json_body = False
            if json_body:
                body = json.dumps(redact_json(parsed), indent=2, ensure_ascii=True).encode("utf-8")
                member, policy = "response.json", "JSON with sensitive fields redacted"
            elif public_stock:
                try:
                    text_body = b"\x00" not in prefix and bool(prefix.decode("utf-8") or not prefix)
                except UnicodeDecodeError:
                    text_body = False
                if prefix.lstrip().startswith((b"<", b"{", b"[")) or text_body:
                    body = redact_text(prefix.decode("utf-8", errors="replace")).encode("utf-8")
                    member, policy = "response.txt", "text with sensitive values redacted"
                else:
                    body, member, policy = prefix, "response.bin", "exact public marketplace bytes"
            else:
                policy = "non-JSON authenticated body omitted to protect login/session data"
            if body is not None:
                # Redaction/JSON formatting can expand a body; keep the saved payload bounded too.
                if len(body) > self.body_limit:
                    body = body[:self.body_limit]
                    report["response"]["truncated"] = True
                report["response"]["saved_bytes"] = len(body)
            report["response"]["body_policy"] = policy
        report["request"] = {"method": method, "url": safe_url(url) if url else None,
                             "parameters": safe_parameters(parameters)}
        signature = hashlib.sha256(json.dumps(
            {key: report[key] for key in ("message", "exceptions", "request")}
            | {"response": report.get("response")}, sort_keys=True, default=str).encode()).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        previous = self._recent.get(signature)
        if previous and previous[0].exists():
            path, first_seen, count = previous
            report.update(first_seen_utc=first_seen, occurrences=count + 1)
        else:
            path = self.directory / f"error-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
        temporary = path.with_suffix(".tmp")
        try:
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=True, default=str))
                if body is not None:
                    archive.writestr(member, body)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self._recent[signature] = (path, report["first_seen_utc"], report["occurrences"])
        reports = sorted(self.directory.glob("error-*.zip"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        for old in reports[self.report_limit:]:
            old.unlink(missing_ok=True)
        self._recent = {key: value for key, value in self._recent.items() if value[0].exists()}
        self.last_failure = None
        return path

    def event_message(self, message, level, *, exception=None):
        """Add a discoverable path to handled errors, retaining UI repeat coalescing."""
        exception = exception or sys.exception()
        if DIAGNOSTIC_MARKER in message or (level != "error" and not (level == "warning" and exception)):
            return message
        path = getattr(exception, "diagnostic_path", None)
        if path is None:
            path = self.record(message, exception=exception)
        if path:
            return f"{message} · {DIAGNOSTIC_MARKER}{path}"
        return f"{message} · Diagnostic save failed: {self.last_failure}"
