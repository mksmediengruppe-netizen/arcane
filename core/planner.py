"""
ARCANE Planner
Decomposes user requests into structured task plans with phases.
Supports dynamic plan updates as new information emerges.

Plan structure:
  Goal: "Build a portfolio website and deploy to hosting"
  Phases:
    1. Research: Gather requirements and design references
    2. Code: Generate HTML/CSS/JS with responsive design
    3. QA: Test in browser, check Lighthouse score
    4. Deploy: Upload to VPS, configure Nginx + SSL
    5. Deliver: Send URL and summary to user
"""

from __future__ import annotations

import json
from typing import Optional

from shared.llm.router import ModelRouter
from shared.models.schemas import TaskPhase, Tier
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("core.planner")

PLANNER_SYSTEM_PROMPT = """You are the ARCANE Planner. Your job is to decompose user requests into structured task plans.

<rules>
1. Each plan has one clear goal and multiple phases
2. Phase count scales with complexity: simple tasks (2-3), typical (4-6), complex (8-12)
3. Each phase has: id, title, description, required_worker, estimated_complexity
4. Workers available: coding, browser, ssh, qa, search, planner
5. Complexity levels: trivial, simple, moderate, complex, expert
6. The final phase should always be "Deliver results to user"
7. Phases must be ordered logically — dependencies respected
8. Include QA/testing phases for any code generation task
9. Include deploy phases when user asks for hosting/deployment
10. Be specific — "Write React component for header" not "Write code"
</rules>

<output_format>
Return ONLY valid JSON with this structure:
{
  "goal": "One-sentence description of the overall goal",
  "phases": [
    {
      "id": 1,
      "title": "Short phase title",
      "description": "Detailed description of what to do",
      "required_worker": "coding|browser|ssh|qa|search|planner",
      "estimated_complexity": "trivial|simple|moderate|complex|expert",
      "depends_on": []
    }
  ]
}
</output_format>"""

REPLAN_SYSTEM_PROMPT = """You are the ARCANE Planner. A task plan needs to be updated based on new information.

Current plan:
{current_plan}

Completed phases: {completed_phases}
Current phase: {current_phase}
Issue: {issue}

Update the remaining phases (keep completed ones unchanged). Return the full updated plan as JSON."""


class Planner:
    """
    Decomposes user requests into executable task plans.
    Uses LLM to generate plans and can dynamically update them.
    """

    def __init__(self, router: ModelRouter):
        self._router = router

    async def create_plan(
        self,
        user_message: str,
        context: str = "",
        user_id: str = "",
        project_id: str = "",
    ) -> dict:
        """
        Create a new task plan from a user message.
        Returns a structured plan with goal and phases.
        """
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        ]

        if context:
            messages.append({
                "role": "system",
                "content": f"Additional context:\n{context}",
            })

        messages.append({
            "role": "user",
            "content": f"Create a task plan for: {user_message}",
        })

        response = await self._router.route(
            messages=messages,
            role="planner",
            user_id=user_id,
            project_id=project_id,
            worker="planner",
            temperature=0.1,
        )

        plan = self._parse_plan(response.content)

        log_with_data(
            logger, "INFO",
            f"Plan created: {plan.get('goal', 'unknown')}",
            phases=len(plan.get("phases", [])),
            cost=response.cost_usd,
        )

        return plan

    async def update_plan(
        self,
        current_plan: dict,
        completed_phase_ids: list[int],
        current_phase_id: int,
        issue: str,
        user_id: str = "",
        project_id: str = "",
    ) -> dict:
        """
        Update an existing plan based on new information or issues.
        Keeps completed phases unchanged, updates remaining ones.
        """
        prompt = REPLAN_SYSTEM_PROMPT.format(
            current_plan=json.dumps(current_plan, indent=2),
            completed_phases=completed_phase_ids,
            current_phase=current_phase_id,
            issue=issue,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Update the plan. Issue: {issue}"},
        ]

        response = await self._router.route(
            messages=messages,
            role="planner",
            user_id=user_id,
            project_id=project_id,
            worker="planner",
            temperature=0.1,
        )

        updated_plan = self._parse_plan(response.content)

        log_with_data(
            logger, "INFO",
            f"Plan updated",
            phases=len(updated_plan.get("phases", [])),
            issue=issue[:100],
        )

        return updated_plan

    async def classify_task(
        self,
        user_message: str,
        user_id: str = "",
        project_id: str = "",
    ) -> dict:
        """
        Quickly classify a user message to determine task type and complexity.
        Uses the cheapest model (NANO tier).
        """
        messages = [
            {"role": "system", "content": """Classify this user request. Return JSON:
{
  "task_type": "website|landing|webapp|api|integration|code|design|deploy|research|other",
  "complexity": "trivial|simple|moderate|complex|expert",
  "requires_deploy": true/false,
  "requires_browser": true/false,
  "requires_search": true/false,
  "estimated_phases": 2-12,
  "summary": "One sentence summary"
}"""},
            {"role": "user", "content": user_message},
        ]

        response = await self._router.route(
            messages=messages,
            role="classifier",
            tier_override=Tier.NANO,
            user_id=user_id,
            project_id=project_id,
            worker="planner",
            temperature=0.0,
        )

        try:
            return json.loads(self._extract_json(response.content))
        except (json.JSONDecodeError, TypeError):
            return {
                "task_type": "other",
                "complexity": "moderate",
                "requires_deploy": False,
                "requires_browser": False,
                "requires_search": False,
                "estimated_phases": 4,
                "summary": user_message[:100],
            }

    def _parse_plan(self, content: str) -> dict:
        """Parse LLM response into a structured plan dict."""
        try:
            json_str = self._extract_json(content)
            plan = json.loads(json_str)

            # Validate structure
            if "goal" not in plan or "phases" not in plan:
                raise ValueError("Plan missing 'goal' or 'phases'")

            # Ensure phases have required fields
            for i, phase in enumerate(plan["phases"]):
                phase.setdefault("id", i + 1)
                phase.setdefault("title", f"Phase {i + 1}")
                phase.setdefault("description", "")
                phase.setdefault("required_worker", "coding")
                phase.setdefault("estimated_complexity", "moderate")
                phase.setdefault("depends_on", [])
                phase.setdefault("status", "pending")

            return plan

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse plan: {e}")
            # Return a minimal fallback plan
            return {
                "goal": "Execute user request",
                "phases": [
                    {
                        "id": 1,
                        "title": "Execute task",
                        "description": content[:500] if content else "Execute the user's request",
                        "required_worker": "coding",
                        "estimated_complexity": "moderate",
                        "depends_on": [],
                        "status": "pending",
                    },
                    {
                        "id": 2,
                        "title": "Deliver results",
                        "description": "Send results to user",
                        "required_worker": "planner",
                        "estimated_complexity": "trivial",
                        "depends_on": [1],
                        "status": "pending",
                    },
                ],
            }

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text that may contain markdown code blocks."""
        if not text:
            return "{}"

        # Try to find JSON in code blocks
        import re
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        # Try to find raw JSON
        for start_char in ["{", "["]:
            idx = text.find(start_char)
            if idx >= 0:
                # Find matching closing bracket
                depth = 0
                end_char = "}" if start_char == "{" else "]"
                for i in range(idx, len(text)):
                    if text[i] == start_char:
                        depth += 1
                    elif text[i] == end_char:
                        depth -= 1
                        if depth == 0:
                            return text[idx : i + 1]

        return text.strip()
