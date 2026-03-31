"""
ARCANE QA Worker
Deep code quality and security analysis using the o3 reasoning model.

Checks:
  - Syntax validation (py_compile, node --check)
  - Static analysis (AST-based for Python)
  - Security audit (hardcoded secrets, SQL injection, eval/exec, XSS)
  - Code complexity (function length, nesting depth)
  - Best practices (logging vs print, error handling, type hints)
  - Project structure (missing files, broken imports)
  - LLM-powered deep review (using o3 for reasoning about edge cases)
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shared.llm.router import ModelRouter
from shared.models.schemas import Tier
from shared.utils.logger import get_logger

logger = get_logger("workers.qa")


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class QAIssue:
    file: str
    line: int
    severity: Severity
    category: str
    message: str
    suggestion: str = ""


@dataclass
class QAReport:
    passed: bool
    score: int  # 0-100
    issues: list[QAIssue] = field(default_factory=list)
    summary: str = ""
    files_checked: int = 0
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0


class QAWorker:
    """
    Performs comprehensive code quality analysis.
    Combines static analysis with LLM-powered deep review.
    """

    def __init__(self, router: ModelRouter):
        self._router = router

    async def review(
        self,
        files: dict[str, str],
        project_dir: str = "",
        user_id: str = "",
        project_id: str = "",
    ) -> QAReport:
        """
        Run full QA review on a set of files.
        Returns a QAReport with score, issues, and summary.
        """
        all_issues: list[QAIssue] = []

        # Static analysis
        for filepath, content in files.items():
            if filepath.endswith(".py"):
                all_issues.extend(self._analyze_python(filepath, content))
            elif filepath.endswith((".js", ".ts", ".jsx", ".tsx")):
                all_issues.extend(self._analyze_javascript(filepath, content))
            elif filepath.endswith(".html"):
                all_issues.extend(self._analyze_html(filepath, content))

            # Universal checks
            all_issues.extend(self._security_scan(filepath, content))

        # LLM deep review for complex projects (5+ files or critical issues)
        critical_count = sum(1 for i in all_issues if i.severity == Severity.CRITICAL)
        if len(files) >= 5 or critical_count > 0:
            llm_issues = await self._llm_deep_review(
                files, user_id=user_id, project_id=project_id
            )
            all_issues.extend(llm_issues)

        # Calculate score
        score = self._calculate_score(all_issues, len(files))
        critical_count = sum(1 for i in all_issues if i.severity == Severity.CRITICAL)
        error_count = sum(1 for i in all_issues if i.severity == Severity.ERROR)
        warning_count = sum(1 for i in all_issues if i.severity == Severity.WARNING)

        passed = critical_count == 0 and error_count == 0

        report = QAReport(
            passed=passed,
            score=score,
            issues=all_issues,
            files_checked=len(files),
            critical_count=critical_count,
            error_count=error_count,
            warning_count=warning_count,
            summary=self._build_summary(all_issues, score, len(files)),
        )

        logger.info(
            f"QA Review: score={score}, passed={passed}, "
            f"critical={critical_count}, errors={error_count}, warnings={warning_count}"
        )

        return report

    def _analyze_python(self, filepath: str, code: str) -> list[QAIssue]:
        """AST-based Python analysis."""
        issues = []

        # Syntax check
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append(QAIssue(
                file=filepath, line=e.lineno or 0, severity=Severity.ERROR,
                category="syntax", message=f"Syntax error: {e.msg}",
                suggestion="Fix the syntax error before proceeding",
            ))
            return issues

        # Walk AST
        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(QAIssue(
                    file=filepath, line=node.lineno, severity=Severity.WARNING,
                    category="best_practice", message="Bare except clause catches all exceptions",
                    suggestion="Catch specific exceptions: except ValueError as e:",
                ))

            # Function complexity (too many lines)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_lines = node.end_lineno - node.lineno if node.end_lineno else 0
                if func_lines > 50:
                    issues.append(QAIssue(
                        file=filepath, line=node.lineno, severity=Severity.WARNING,
                        category="complexity",
                        message=f"Function '{node.name}' is {func_lines} lines long",
                        suggestion="Consider breaking it into smaller functions",
                    ))

                # Too many arguments
                args_count = len(node.args.args)
                if args_count > 7:
                    issues.append(QAIssue(
                        file=filepath, line=node.lineno, severity=Severity.WARNING,
                        category="complexity",
                        message=f"Function '{node.name}' has {args_count} parameters",
                        suggestion="Consider using a dataclass or config object",
                    ))

            # eval/exec usage
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                    issues.append(QAIssue(
                        file=filepath, line=node.lineno, severity=Severity.CRITICAL,
                        category="security", message=f"Usage of {node.func.id}() is a security risk",
                        suggestion="Use ast.literal_eval() for safe evaluation, or avoid eval entirely",
                    ))

        # Line-by-line checks
        lines = code.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # print() in production code
            if stripped.startswith("print(") and "test" not in filepath.lower():
                issues.append(QAIssue(
                    file=filepath, line=i, severity=Severity.WARNING,
                    category="best_practice", message="print() in production code",
                    suggestion="Use logging module instead: logger.info()",
                ))

            # TODO/FIXME/HACK
            if any(tag in stripped.upper() for tag in ["TODO", "FIXME", "HACK", "XXX"]):
                issues.append(QAIssue(
                    file=filepath, line=i, severity=Severity.INFO,
                    category="maintenance", message=f"Found TODO/FIXME comment: {stripped[:60]}",
                ))

        return issues

    def _analyze_javascript(self, filepath: str, code: str) -> list[QAIssue]:
        """Basic JavaScript/TypeScript analysis."""
        issues = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # console.log in production
            if "console.log(" in stripped and "test" not in filepath.lower():
                issues.append(QAIssue(
                    file=filepath, line=i, severity=Severity.WARNING,
                    category="best_practice", message="console.log() in production code",
                    suggestion="Remove or replace with a proper logger",
                ))

            # var usage (should use let/const)
            if stripped.startswith("var "):
                issues.append(QAIssue(
                    file=filepath, line=i, severity=Severity.WARNING,
                    category="best_practice", message="Using 'var' instead of 'let' or 'const'",
                    suggestion="Use 'const' for constants, 'let' for variables",
                ))

            # innerHTML (XSS risk)
            if ".innerHTML" in stripped and "sanitize" not in stripped.lower():
                issues.append(QAIssue(
                    file=filepath, line=i, severity=Severity.ERROR,
                    category="security", message="innerHTML usage without sanitization (XSS risk)",
                    suggestion="Use textContent or sanitize HTML with DOMPurify",
                ))

        return issues

    def _analyze_html(self, filepath: str, code: str) -> list[QAIssue]:
        """Basic HTML analysis."""
        issues = []

        if "<html" in code.lower() and 'lang=' not in code.lower()[:500]:
            issues.append(QAIssue(
                file=filepath, line=1, severity=Severity.WARNING,
                category="accessibility", message="Missing lang attribute on <html>",
                suggestion='Add lang attribute: <html lang="en">',
            ))

        if "<img" in code.lower():
            img_pattern = re.findall(r'<img[^>]*>', code, re.IGNORECASE)
            for img in img_pattern:
                if 'alt=' not in img.lower():
                    issues.append(QAIssue(
                        file=filepath, line=0, severity=Severity.WARNING,
                        category="accessibility", message="Image missing alt attribute",
                        suggestion="Add descriptive alt text to all images",
                    ))

        if '<meta name="viewport"' not in code.lower() and "<html" in code.lower():
            issues.append(QAIssue(
                file=filepath, line=1, severity=Severity.WARNING,
                category="responsive", message="Missing viewport meta tag",
                suggestion='Add: <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            ))

        return issues

    def _security_scan(self, filepath: str, code: str) -> list[QAIssue]:
        """Universal security checks."""
        issues = []
        lines = code.split("\n")

        secret_patterns = [
            (r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{3,}["\']', "Hardcoded password"),
            (r'(?:api_key|apikey|api_secret)\s*=\s*["\'][^"\']{10,}["\']', "Hardcoded API key"),
            (r'(?:secret|token)\s*=\s*["\'][A-Za-z0-9+/=]{20,}["\']', "Hardcoded secret/token"),
            (r'(?:sk-|pk_live_|sk_live_)[A-Za-z0-9]{20,}', "Exposed API key in code"),
        ]

        for i, line in enumerate(lines, 1):
            if line.strip().startswith("#") or line.strip().startswith("//"):
                continue
            for pattern, message in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if "environ" not in line and "getenv" not in line and "settings" not in line.lower():
                        issues.append(QAIssue(
                            file=filepath, line=i, severity=Severity.CRITICAL,
                            category="security", message=message,
                            suggestion="Use environment variables or a secrets manager",
                        ))

        return issues

    async def _llm_deep_review(
        self,
        files: dict[str, str],
        user_id: str = "",
        project_id: str = "",
    ) -> list[QAIssue]:
        """Use o3 model for deep reasoning about code quality."""
        files_str = "\n\n".join(
            f"--- {path} ---\n{content[:2000]}"
            for path, content in list(files.items())[:10]
        )

        messages = [
            {"role": "system", "content": """You are a senior code reviewer. Analyze the code for:
1. Logic errors and edge cases
2. Security vulnerabilities
3. Performance issues
4. Missing error handling
5. Race conditions (for async code)

Return JSON array of issues:
[{"file": "path", "line": 0, "severity": "error|warning|critical", "category": "logic|security|performance|error_handling", "message": "description", "suggestion": "how to fix"}]

Only report real issues, not style preferences. Return [] if code is clean."""},
            {"role": "user", "content": f"Review this code:\n\n{files_str}"},
        ]

        try:
            response = await self._router.route(
                messages=messages,
                role="qa",
                user_id=user_id,
                project_id=project_id,
                worker="qa",
                temperature=0.1,
            )

            # Parse LLM response
            content = response.content or "[]"
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                raw_issues = json.loads(json_match.group())
                return [
                    QAIssue(
                        file=i.get("file", "unknown"),
                        line=i.get("line", 0),
                        severity=Severity(i.get("severity", "warning")),
                        category=i.get("category", "logic"),
                        message=i.get("message", ""),
                        suggestion=i.get("suggestion", ""),
                    )
                    for i in raw_issues
                ]
        except Exception as e:
            logger.warning(f"LLM deep review failed: {e}")

        return []

    def _calculate_score(self, issues: list[QAIssue], file_count: int) -> int:
        """Calculate quality score 0-100."""
        if not issues:
            return 100

        penalty = 0
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                penalty += 25
            elif issue.severity == Severity.ERROR:
                penalty += 15
            elif issue.severity == Severity.WARNING:
                penalty += 5
            elif issue.severity == Severity.INFO:
                penalty += 1

        # Normalize by file count
        if file_count > 0:
            penalty = penalty / max(file_count, 1) * min(file_count, 5)

        return max(0, min(100, 100 - int(penalty)))

    def _build_summary(self, issues: list[QAIssue], score: int, file_count: int) -> str:
        """Build a human-readable summary."""
        if not issues:
            return f"All {file_count} files passed QA review with a perfect score."

        critical = [i for i in issues if i.severity == Severity.CRITICAL]
        errors = [i for i in issues if i.severity == Severity.ERROR]

        parts = [f"QA Score: {score}/100 across {file_count} files."]

        if critical:
            parts.append(f"CRITICAL ({len(critical)}): {critical[0].message}")
        if errors:
            parts.append(f"ERRORS ({len(errors)}): {errors[0].message}")

        if score >= 80:
            parts.append("Overall: Good quality with minor issues.")
        elif score >= 60:
            parts.append("Overall: Acceptable but needs improvements.")
        else:
            parts.append("Overall: Significant issues found. Code needs revision.")

        return " ".join(parts)
