"""
ARCANE Metrics & Observability
Step 9: In-memory metrics collection for monitoring.
"""
from __future__ import annotations
import time
from collections import defaultdict, deque
from shared.utils.logger import get_logger

logger = get_logger("api.metrics")

_request_counts: dict[str, int] = defaultdict(int)
_error_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_latency_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
_agent_metrics = {
    "total_started": 0,
    "total_completed": 0,
    "total_failed": 0,
    "total_cost_usd": 0.0,
    "total_tokens": 0,
}
_start_time = time.time()


def record_request(endpoint: str, method: str = "GET"):
    key = f"{method}:{endpoint}"
    _request_counts[key] += 1


def record_response(endpoint: str, method: str, status_code: int, duration_ms: float):
    key = f"{method}:{endpoint}"
    _latency_samples[key].append((time.time(), duration_ms))
    if status_code >= 400:
        _error_counts[key][str(status_code)] += 1


def record_agent_started(chat_id: str):
    _agent_metrics["total_started"] += 1


def record_agent_completed(chat_id: str, cost_usd: float = 0.0, tokens: int = 0):
    _agent_metrics["total_completed"] += 1
    _agent_metrics["total_cost_usd"] += cost_usd
    _agent_metrics["total_tokens"] += tokens


def record_agent_failed(chat_id: str):
    _agent_metrics["total_failed"] += 1


def _percentile(data: list, p: int) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return round(sorted_data[min(idx, len(sorted_data) - 1)], 1)


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    elif seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"
    else:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d}d {h}h"


def get_metrics_summary() -> dict:
    uptime_seconds = int(time.time() - _start_time)
    total_requests = sum(_request_counts.values())
    total_errors = sum(sum(codes.values()) for codes in _error_counts.values())

    top_endpoints = sorted(
        _request_counts.items(), key=lambda x: x[1], reverse=True
    )[:10]

    now = time.time()
    window = now - 300
    latency_stats = {}
    for endpoint, samples in _latency_samples.items():
        recent = [d for ts, d in samples if ts >= window]
        if recent:
            latency_stats[endpoint] = {
                "p50": _percentile(recent, 50),
                "p95": _percentile(recent, 95),
                "p99": _percentile(recent, 99),
                "count": len(recent),
            }

    return {
        "uptime_seconds": uptime_seconds,
        "uptime_human": _format_duration(uptime_seconds),
        "requests": {
            "total": total_requests,
            "errors": total_errors,
            "error_rate": round(total_errors / max(total_requests, 1) * 100, 2),
            "top_endpoints": [{"endpoint": k, "count": v} for k, v in top_endpoints],
        },
        "latency": latency_stats,
        "agents": {
            "total_started": _agent_metrics["total_started"],
            "total_completed": _agent_metrics["total_completed"],
            "total_failed": _agent_metrics["total_failed"],
            "success_rate": round(
                _agent_metrics["total_completed"] / max(_agent_metrics["total_started"], 1) * 100, 1
            ),
            "total_cost_usd": round(_agent_metrics["total_cost_usd"], 4),
            "total_tokens": _agent_metrics["total_tokens"],
        },
    }


def get_health_metrics() -> dict:
    uptime = int(time.time() - _start_time)
    total_req = sum(_request_counts.values())
    total_err = sum(sum(c.values()) for c in _error_counts.values())
    return {
        "uptime_seconds": uptime,
        "total_requests": total_req,
        "total_errors": total_err,
        "error_rate_pct": round(total_err / max(total_req, 1) * 100, 2),
        "agents_running": _agent_metrics["total_started"] - _agent_metrics["total_completed"] - _agent_metrics["total_failed"],
        "agents_completed": _agent_metrics["total_completed"],
        "agents_failed": _agent_metrics["total_failed"],
        "total_cost_usd": round(_agent_metrics["total_cost_usd"], 4),
    }
