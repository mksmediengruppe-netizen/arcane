"""
ARCANE Coding Worker
Generates, tests, and self-heals code in an isolated sandbox.

Self-Healing Loop:
  1. Generate code via LLM (claude-opus-4 for complex, gpt-4.1-mini for simple)
  2. Write files to sandbox directory
  3. Run tests / lint / type-check
  4. If tests fail → analyze error → generate fix → repeat (up to MAX_HEAL_ITERATIONS)
  5. If tests pass → return code + artifacts

Supports: Python, JavaScript/TypeScript, HTML/CSS, React, FastAPI, Node.js, etc.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Optional

from shared.llm.router import ModelRouter
from shared.models.schemas import Tier
from shared.utils.error_analyzer import ErrorReport, analyze_error
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("workers.coding")

MAX_HEAL_ITERATIONS = 5

CODING_SYSTEM_PROMPT = """You are ARCANE's Coding Worker — an expert software engineer.

<rules>
1. Write clean, production-ready code with proper error handling
2. Include type hints (Python) or TypeScript types
3. Never hardcode secrets — use environment variables
4. Always include proper imports
5. Follow the project's existing code style if context is provided
6. For web projects: responsive design, semantic HTML, accessibility
7. For APIs: proper validation, error responses, CORS headers
8. For scripts: argument parsing, logging, graceful error handling
</rules>

<output_format>
Return code wrapped in file blocks:

```filename:path/to/file.py
# file content here
```

If multiple files, use multiple blocks. Always specify the full relative path.
</output_format>"""

FIX_ERROR_PROMPT = """The code you generated has an error. Fix it.

Error output:
{error_output}

Error analysis:
- Category: {category}
- Root cause: {root_cause}
- Suggested fixes: {suggested_fixes}

Original code:
{original_code}

Return the COMPLETE fixed code (not just the changed parts)."""


class CodingWorker:
    """
    Generates code and self-heals errors through iterative testing.
    """

    def __init__(self, router: ModelRouter, workspace_dir: str = "/root/workspace"):
        self._router = router
        self._workspace = workspace_dir

    async def generate(
        self,
        task: str,
        context: str = "",
        language: str = "",
        framework: str = "",
        existing_files: dict[str, str] = None,
        user_id: str = "",
        project_id: str = "",
        tier: Optional[Tier] = None,
    ) -> dict:
        """
        Generate code for a task with self-healing.
        Returns dict with files, test_results, iterations, cost.
        """
        messages = [{"role": "system", "content": CODING_SYSTEM_PROMPT}]

        if context:
            messages.append({"role": "system", "content": f"Project context:\n{context}"})

        if existing_files:
            files_str = "\n\n".join(
                f"```{path}\n{content}\n```"
                for path, content in existing_files.items()
            )
            messages.append({"role": "system", "content": f"Existing project files:\n{files_str}"})

        task_prompt = f"Task: {task}"
        if language:
            task_prompt += f"\nLanguage: {language}"
        if framework:
            task_prompt += f"\nFramework: {framework}"

        messages.append({"role": "user", "content": task_prompt})

        # Generate initial code
        response = await self._router.route(
            messages=messages,
            role="coding",
            tier_override=tier,
            user_id=user_id,
            project_id=project_id,
            worker="coding",
            temperature=0.2,
        )

        files = self._parse_code_blocks(response.content)
        total_cost = response.cost_usd

        if not files:
            return {
                "success": False,
                "error": "No code generated",
                "files": {},
                "iterations": 0,
                "cost": total_cost,
            }

        # Write files to workspace
        project_dir = os.path.join(self._workspace, project_id or "default")
        self._write_files(project_dir, files)

        # Self-healing loop
        iteration = 0
        test_result = None

        while iteration < MAX_HEAL_ITERATIONS:
            iteration += 1

            # Run tests
            test_result = await self._run_tests(project_dir, files)

            if test_result["success"]:
                log_with_data(
                    logger, "INFO",
                    f"Code passed tests on iteration {iteration}",
                    iterations=iteration,
                    files=len(files),
                )
                return {
                    "success": True,
                    "files": files,
                    "test_output": test_result["output"],
                    "iterations": iteration,
                    "cost": total_cost,
                    "project_dir": project_dir,
                }

            # Analyze error
            error_report = analyze_error(test_result["output"])

            log_with_data(
                logger, "WARNING",
                f"Test failed (iteration {iteration}/{MAX_HEAL_ITERATIONS})",
                error_category=error_report.category.value,
                root_cause=error_report.root_cause[:100],
            )

            # Generate fix
            all_code = "\n\n".join(
                f"# {path}\n{content}" for path, content in files.items()
            )

            fix_prompt = FIX_ERROR_PROMPT.format(
                error_output=test_result["output"][:2000],
                category=error_report.category.value,
                root_cause=error_report.root_cause,
                suggested_fixes=", ".join(error_report.suggested_fixes),
                original_code=all_code[:4000],
            )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": fix_prompt})

            # Escalate tier on repeated failures
            escalated_tier = None
            if iteration >= 3:
                escalated_tier = Tier.GENIUS

            response = await self._router.route(
                messages=messages,
                role="coding",
                tier_override=escalated_tier,
                user_id=user_id,
                project_id=project_id,
                worker="coding",
                temperature=0.1,
            )

            total_cost += response.cost_usd
            new_files = self._parse_code_blocks(response.content)

            if new_files:
                files.update(new_files)
                self._write_files(project_dir, new_files)

        # Max iterations reached
        return {
            "success": False,
            "files": files,
            "error": f"Failed after {MAX_HEAL_ITERATIONS} iterations",
            "last_error": test_result["output"] if test_result else "Unknown",
            "iterations": iteration,
            "cost": total_cost,
            "project_dir": project_dir,
        }

    async def _run_tests(self, project_dir: str, files: dict[str, str]) -> dict:
        """Run tests/validation on generated code."""
        results = []
        success = True

        for filepath, content in files.items():
            full_path = os.path.join(project_dir, filepath)

            if filepath.endswith(".py"):
                # Python: syntax check + import check
                result = await self._run_command(
                    f"python3 -c \"import py_compile; py_compile.compile('{full_path}', doraise=True)\"",
                    cwd=project_dir,
                )
                if result["exit_code"] != 0:
                    success = False
                    results.append(f"Python syntax error in {filepath}: {result['stderr']}")

                # Check for common issues
                issues = self._static_analysis_python(content, filepath)
                if issues:
                    results.append(f"Static analysis warnings for {filepath}: {'; '.join(issues)}")

            elif filepath.endswith((".js", ".ts", ".jsx", ".tsx")):
                # JavaScript/TypeScript: basic syntax check with Node
                if filepath.endswith((".ts", ".tsx")):
                    pass  # TypeScript check requires tsc
                else:
                    result = await self._run_command(
                        f"node --check '{full_path}'",
                        cwd=project_dir,
                    )
                    if result["exit_code"] != 0:
                        success = False
                        results.append(f"JS syntax error in {filepath}: {result['stderr']}")

            elif filepath.endswith(".html"):
                # HTML: basic structure check
                if "<html" not in content.lower() and "<!doctype" not in content.lower():
                    if not any(content.strip().startswith(tag) for tag in ["<div", "<section", "<template", "<!"]):
                        results.append(f"Warning: {filepath} may not be valid HTML")

        # Run pytest if test files exist
        test_files = [f for f in files if "test" in f.lower() and f.endswith(".py")]
        if test_files:
            result = await self._run_command(
                "python3 -m pytest -v --tb=short 2>&1",
                cwd=project_dir,
            )
            if result["exit_code"] != 0 or "FAILED" in result["stdout"]:
                success = False
                results.append(f"Pytest failures:\n{result['stdout']}")

        # Run package.json scripts if exists
        if "package.json" in files:
            result = await self._run_command(
                "npm install 2>&1 && npm run build 2>&1",
                cwd=project_dir,
                timeout=60,
            )
            if result["exit_code"] != 0:
                success = False
                results.append(f"npm build failed:\n{result['stderr']}")

        output = "\n".join(results) if results else "All checks passed"
        return {"success": success, "output": output}

    def _static_analysis_python(self, code: str, filepath: str) -> list[str]:
        """Basic static analysis for Python code."""
        issues = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Check for hardcoded secrets
            if any(kw in stripped.lower() for kw in ["password =", "secret =", "api_key ="]):
                if "os.environ" not in stripped and "getenv" not in stripped and "settings." not in stripped:
                    if not stripped.startswith("#"):
                        issues.append(f"Line {i}: Possible hardcoded secret")

            # Check for bare except
            if stripped == "except:":
                issues.append(f"Line {i}: Bare except clause")

            # Check for print in non-test files
            if stripped.startswith("print(") and "test" not in filepath.lower():
                issues.append(f"Line {i}: print() in production code (use logging)")

            # Check for eval/exec
            if "eval(" in stripped or "exec(" in stripped:
                issues.append(f"Line {i}: eval/exec usage (security risk)")

        return issues

    async def _run_command(self, command: str, cwd: str, timeout: int = 30) -> dict:
        """Run a shell command and return result."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            return {"exit_code": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    def _write_files(self, project_dir: str, files: dict[str, str]) -> None:
        """Write files to the project directory."""
        for filepath, content in files.items():
            full_path = os.path.join(project_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

    def _parse_code_blocks(self, text: str) -> dict[str, str]:
        """Parse code blocks from LLM response into {filename: content} dict."""
        import re
        files = {}

        # Pattern: ```filename:path/to/file.ext
        pattern = r"```(?:filename:)?([^\n]+)\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)

        for filename, content in matches:
            filename = filename.strip()
            # Remove language hints like "python", "javascript"
            if filename in ("python", "javascript", "typescript", "html", "css", "json", "bash", "sh", "yaml", "toml"):
                continue
            # Clean up filename
            filename = filename.lstrip("/")
            if filename:
                files[filename] = content.strip() + "\n"

        return files
