#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# ARCANE Smoke Test — run after EVERY deploy
# Usage: bash tests/smoke.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "=== ARCANE Smoke Test ==="
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

PASS=0
FAIL=0
BASE="${ARCANE_BASE_URL:-https://arcaneai.ru}"

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "ok" ]; then
        echo "✅ $name"
        ((PASS++))
    else
        echo "❌ $name — $result"
        ((FAIL++))
    fi
}

# 1. Health endpoint
HEALTH=$(curl -sf "$BASE/api/health" 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q "healthy"; then
    check "Health" "ok"
else
    check "Health" "endpoint not responding"
fi

# 2. Models endpoint
MODELS=$(curl -sf "$BASE/api/models" 2>/dev/null || echo "")
if echo "$MODELS" | grep -q "gpt"; then
    check "Models" "ok"
else
    check "Models" "no models returned"
fi

# 3. Auth — login
TOKEN=$(curl -sf "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"login":"admin_bitrix","password":"BitrixAdmin2024!"}' 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")

if [ -n "$TOKEN" ] && [ "$TOKEN" != "None" ]; then
    check "Auth (login)" "ok"
else
    check "Auth (login)" "no token returned"
fi

# 4. Chat creation
if [ -n "$TOKEN" ] && [ "$TOKEN" != "None" ]; then
    CHAT=$(curl -sf "$BASE/api/chats" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"title":"Smoke test '$(date +%s)'"}' 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

    if [ -n "$CHAT" ] && [ "$CHAT" != "None" ]; then
        check "Chat creation" "ok"
    else
        check "Chat creation" "no chat_id returned"
    fi
else
    check "Chat creation" "skipped (no auth token)"
fi

# 5. OpenRouter — GPT-5 Mini
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
    GPT5=$(curl -sf "https://openrouter.ai/api/v1/chat/completions" \
        -H "Authorization: Bearer $OPENROUTER_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"model":"openai/gpt-5-mini","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5,"provider":{"ignore":["Azure"]}}' 2>/dev/null || echo "")

    if echo "$GPT5" | grep -qi "ok"; then
        check "GPT-5 Mini (OpenRouter)" "ok"
    else
        check "GPT-5 Mini (OpenRouter)" "no response or error"
    fi
else
    check "GPT-5 Mini (OpenRouter)" "skipped (no OPENROUTER_API_KEY)"
fi

# 6. OpenRouter — Gemini
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
    GEMINI=$(curl -sf "https://openrouter.ai/api/v1/chat/completions" \
        -H "Authorization: Bearer $OPENROUTER_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"model":"google/gemini-2.5-flash","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}' 2>/dev/null || echo "")

    if echo "$GEMINI" | grep -qi "ok"; then
        check "Gemini 2.5 Flash (OpenRouter)" "ok"
    else
        check "Gemini 2.5 Flash (OpenRouter)" "no response or error"
    fi
else
    check "Gemini 2.5 Flash (OpenRouter)" "skipped (no OPENROUTER_API_KEY)"
fi

# 7. Static files (frontend)
FRONTEND=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE/" 2>/dev/null || echo "000")
if [ "$FRONTEND" = "200" ]; then
    check "Frontend (static)" "ok"
else
    check "Frontend (static)" "HTTP $FRONTEND"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "Result: $PASS passed, $FAIL failed"
if [ $FAIL -eq 0 ]; then
    echo "🟢 ALL CLEAR — deploy is healthy"
else
    echo "🔴 ISSUES DETECTED — review failures above"
fi
echo "═══════════════════════════════════════════"

exit $FAIL
