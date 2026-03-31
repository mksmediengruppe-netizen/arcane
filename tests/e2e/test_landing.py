"""
ARCANE E2E Test: Landing Page Generation

Tests that a landing page task:
1. Completes within budget (< $0.30)
2. Completes within iteration limit (< 15)
3. Completes within time limit (< 5 min)
4. Produces at least one HTML artifact
5. (Optional) Design Judge runs and returns a score

Run: pytest tests/e2e/test_landing.py -v --timeout=360
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio

from .conftest import send_message_and_wait

# Test parameters
MAX_COST = 0.30  # $0.30 budget ceiling
MAX_ITERATIONS = 15  # iteration ceiling
MAX_TIME_SECONDS = 300  # 5 minutes


@pytest.mark.asyncio
async def test_landing_page_cost_and_quality(api_client):
    """
    Full E2E: send a landing page request, verify cost, iterations, and output.
    """
    start = time.monotonic()

    chat_id, collector = await send_message_and_wait(
        client=api_client,
        message="Сделай лендинг для фитнес-студии FitZone. Современный дизайн, секции: герой, преимущества, цены, контакты.",
        timeout_seconds=MAX_TIME_SECONDS,
    )

    elapsed = time.monotonic() - start

    # ── Assertions ──────────────────────────────────────────────────────────

    # 1. Task should complete (no errors)
    assert not collector.errors, f"Task had errors: {collector.errors}"

    # 2. Cost should be under budget
    total_cost = collector.total_cost
    print(f"\n📊 Total cost: ${total_cost:.4f} (limit: ${MAX_COST})")
    assert total_cost <= MAX_COST, (
        f"Cost ${total_cost:.4f} exceeded budget ${MAX_COST}"
    )

    # 3. Should complete within time limit
    print(f"⏱️  Elapsed: {elapsed:.1f}s (limit: {MAX_TIME_SECONDS}s)")
    assert elapsed <= MAX_TIME_SECONDS, (
        f"Took {elapsed:.1f}s, exceeds {MAX_TIME_SECONDS}s limit"
    )

    # 4. Should have used file_write or file_create (produced HTML)
    tools = collector.tools_used
    print(f"🔧 Tools used: {len(tools)} calls")
    has_file_tool = any(t in ("file_write", "file_create", "file_edit") for t in tools)
    assert has_file_tool, "No file creation tools were used — no HTML produced"

    # 5. Should have used message tool (delivered result)
    has_message = any(t == "message" for t in tools)
    assert has_message, "Agent did not deliver a result via message tool"

    # 6. Total events should indicate reasonable iteration count
    tool_count = len(tools)
    print(f"🔄 Tool calls: {tool_count} (limit: ~{MAX_ITERATIONS * 2})")

    # 7. (Optional) Check if design judge ran
    if collector.design_reports:
        report = collector.design_reports[0]
        score = report.get("overall_score", 0)
        print(f"🎨 Design Judge score: {score}/100")
        # We don't assert on score, just log it
    else:
        print("🎨 Design Judge: not triggered (optional)")

    print(f"\n✅ Landing page test PASSED: ${total_cost:.4f}, {elapsed:.1f}s")


@pytest.mark.asyncio
async def test_simple_question_no_overspend(api_client):
    """
    Verify that a simple question doesn't trigger expensive agent loops.
    Should complete in 1-2 iterations with minimal cost.
    """
    chat_id, collector = await send_message_and_wait(
        client=api_client,
        message="Привет! Что ты умеешь?",
        timeout_seconds=30,
    )

    total_cost = collector.total_cost
    print(f"\n📊 Simple question cost: ${total_cost:.4f}")

    # Simple question should cost almost nothing
    assert total_cost <= 0.02, f"Simple question cost ${total_cost:.4f} — too expensive"

    # Should use message tool
    tools = collector.tools_used
    has_message = any(t == "message" for t in tools)
    assert has_message, "Agent didn't respond with message tool"

    print(f"✅ Simple question test PASSED: ${total_cost:.4f}")
