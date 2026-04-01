"""
ARCANE Tool Registry — Manus-style Tool Descriptions
=====================================================
Every tool has three layers of description:
1. Description — what it does
2. <instructions> — how to use it correctly, what to avoid
3. <recommended_usage> — when exactly to call it

This is what makes LLM use tools precisely and confidently.
Total: 31 tools across 10 categories.
"""
from __future__ import annotations
from typing import Any

def _param(name: str, type_: str, description: str, required: bool = True) -> tuple:
    return (name, {"type": type_, "description": description}, required)

def _tool(name: str, description: str, params: list, handler_name: str = None) -> dict:
    properties = {}
    required = []
    for p in params:
        if isinstance(p, tuple) and len(p) == 3:
            pname, schema, is_required = p
            if isinstance(schema, dict):
                properties[pname] = schema
            else:
                properties[pname] = schema
            if is_required:
                required.append(pname)
        elif isinstance(p, tuple) and len(p) == 2:
            pname, schema = p
            properties[pname] = schema
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS — Manus-style descriptions with <instructions> and <recommended_usage>
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS: list[dict] = [

    # ══════════════════════════════════════════════════════════════════════════
    # 1. SHELL TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("shell_exec",
        "Execute a shell command in the local sandbox environment.\n\n"
        "<instructions>\n"
        "- Use for installing packages, running scripts, file operations, and system commands\n"
        "- ALWAYS save code to a file first using file_write, then execute via shell_exec — never run code inline\n"
        "- Chain multiple commands with && to reduce round-trips and handle errors cleanly\n"
        "- Use pipes (|) to simplify workflows by passing outputs between commands\n"
        "- Avoid commands that require confirmation; use flags like -y or -f for automatic execution\n"
        "- Avoid commands with excessive output; redirect to files when necessary (e.g., > /tmp/output.log)\n"
        "- Set a short timeout (5-10s) for commands that don't return (like starting web servers)\n"
        "- For long-running operations (apt install, compilation), set timeout to 120-300s\n"
        "- Use non-interactive bc for simple calculations, Python for complex math — NEVER calculate mentally\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to install packages or dependencies (apt, pip, npm)\n"
        "- Use to copy, move, or delete files\n"
        "- Use to run Python/Node scripts after saving them to files\n"
        "- Use to check system status, disk space, running processes\n"
        "- Use to create directories, set permissions, manage archives\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("command", "string", "The shell command to execute"),
        _param("timeout", "integer", "Timeout in seconds (default 30)", required=False),
        _param("working_dir", "string", "Working directory for the command", required=False),
    ]),

    _tool("shell_view",
        "View the current output of a running shell session.\n\n"
        "<instructions>\n"
        "- Use after shell_exec to check if a long-running command has completed\n"
        "- Ensure command has completed execution before using its output for decisions\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when checking shell session history and latest status\n"
        "- Use when waiting for completion of long-running commands\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("session", "string", "Session identifier", required=False),
    ]),

    _tool("ssh_exec",
        "Execute a command on a REMOTE server via SSH. Connects to external servers by IP/hostname.\n\n"
        "<instructions>\n"
        "- Use for ALL remote server operations: installing software, configuring services, checking status\n"
        "- ALWAYS save server credentials to scratchpad (update_scratchpad) after first successful connection\n"
        "- Chain multiple commands with && to reduce SSH round-trips\n"
        "- Set appropriate timeout: 60s for quick checks, 180s for installations, 300s for compilations\n"
        "- For service management (systemctl start), verify status in a SEPARATE call after starting\n"
        "- NEVER run destructive commands (rm -rf /, DROP DATABASE) without explicit user confirmation\n"
        "- If connection fails, check: correct IP, port 22 open, correct credentials, server is running\n"
        "- When installing software, ALWAYS use -y flag (apt install -y, yum install -y)\n"
        "- After installing a service, verify it works: curl localhost, systemctl status, etc.\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for installing CMS (WordPress, Bitrix, Joomla) on remote servers\n"
        "- Use for configuring Nginx, Apache, SSL certificates\n"
        "- Use for deploying code, managing Docker containers\n"
        "- Use for server diagnostics: disk space, memory, logs, processes\n"
        "- Use for database operations: creating DBs, users, importing dumps\n"
        "- Use for DNS and domain configuration\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("host", "string", "Remote server hostname or IP address"),
        _param("command", "string", "Shell command to execute on the remote server"),
        _param("username", "string", "SSH username (default: root)", required=False),
        _param("password", "string", "SSH password for authentication", required=False),
        _param("port", "integer", "SSH port (default: 22)", required=False),
        _param("timeout", "integer", "Command timeout in seconds (default: 60)", required=False),
        _param("key_path", "string", "Path to private key file for key-based auth", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 2. FILE TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("file_read",
        "Read the contents of a text file.\n\n"
        "<instructions>\n"
        "- Use start_line/end_line to read specific sections of large files — don't read entire 10000-line files\n"
        "- DO NOT read files that were just written by you — their content is already in context\n"
        "- For first read, omit start_line/end_line to see the full file; if truncated, use ranges\n"
        "- Prefer this over shell_exec cat to avoid escaping issues\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to read configuration files, source code, logs\n"
        "- Use to check file contents before editing\n"
        "- Use to re-read files after context compression\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("path", "string", "Absolute path to the file"),
        _param("start_line", "integer", "Start line number (1-indexed)", required=False),
        _param("end_line", "integer", "End line number (inclusive, -1 for end)", required=False),
    ]),

    _tool("file_write",
        "Create or overwrite a file with the given content.\n\n"
        "<instructions>\n"
        "- Use for creating new files: HTML, CSS, JS, Python, configs, etc.\n"
        "- ALWAYS write complete content — never write partial or truncated files\n"
        "- For code files, ALWAYS save to file first, then execute via shell_exec\n"
        "- Use descriptive filenames: 'neuropulse_landing.html', not 'index.html'\n"
        "- Ensure trailing newline for POSIX compliance\n"
        "- For HTML files: include all CSS/JS inline in a single file for easy delivery\n"
        "- DO NOT read files immediately after writing — content is already in your context\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to create landing pages, websites, scripts\n"
        "- Use to write configuration files (nginx.conf, docker-compose.yml)\n"
        "- Use to save code before execution\n"
        "- Use to create complete project files\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("path", "string", "Absolute path to the file"),
        _param("content", "string", "Full content to write to the file"),
    ]),

    _tool("file_edit",
        "Make targeted edits to a file. Find and replace specific text.\n\n"
        "<instructions>\n"
        "- Use for surgical edits to existing files — changing a few lines without rewriting everything\n"
        "- The 'find' string must be EXACT — copy it precisely from the file\n"
        "- Multiple edits are applied sequentially; all must succeed or none are applied\n"
        "- For extensive modifications to short files (<100 lines), use file_write to rewrite entirely\n"
        "- Set 'all': true to replace all occurrences, otherwise only the first match is replaced\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to fix bugs in code — change specific lines\n"
        "- Use to update configuration values\n"
        "- Use to patch files without rewriting them entirely\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("path", "string", "Absolute path to the file"),
        ("edits", {
            "type": "array",
            "description": "List of edit operations. Each edit has 'find' (exact text to find), 'replace' (replacement text), and optional 'all' (boolean, replace all occurrences).",
            "items": {
                "type": "object",
                "properties": {
                    "find": {"type": "string", "description": "Exact text string to find in the file"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "all": {"type": "boolean", "description": "Replace all occurrences (default false)"}
                },
                "required": ["find", "replace"]
            }
        }, True),
    ]),

    _tool("file_append",
        "Append content to the end of a file. Creates the file if it doesn't exist.\n\n"
        "<instructions>\n"
        "- Use to add content without overwriting existing data\n"
        "- Ensure necessary newlines between existing and new content\n"
        "- For writing long content in segments, use append after initial file_write\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to add entries to log files or configuration files\n"
        "- Use to build up long files in segments\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("path", "string", "Absolute path to the file"),
        _param("content", "string", "Content to append"),
    ]),

    _tool("file_view",
        "View a file visually using multimodal understanding. For images and PDFs.\n\n"
        "<instructions>\n"
        "- Use for files that need visual interpretation: images, PDFs, screenshots\n"
        "- For text files, prefer file_read instead — it's faster and more precise\n"
        "- After viewing, ALWAYS save key findings to text files to prevent loss of visual information\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to view generated screenshots and images\n"
        "- Use to examine PDF documents visually\n"
        "- Use to verify visual output of generated websites\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("path", "string", "Absolute path to the file"),
        _param("page", "integer", "Page number for PDFs", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 3. BROWSER TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("browser_navigate",
        "Navigate the browser to a URL.\n\n"
        "<instructions>\n"
        "- Returns visible interactive elements, extracted Markdown content, and annotated screenshot\n"
        "- Visible elements are returned as index[:]<tag>text</tag> — use index for subsequent actions\n"
        "- For informational visits, if Markdown extraction is complete, scrolling is not needed\n"
        "- ALWAYS include protocol prefix (https:// or file://)\n"
        "- Use file:// to preview locally generated HTML files\n"
        "- After navigating, save key information to files — subsequent operations may lose visual context\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to preview generated HTML files (file:///root/workspace/...)\n"
        "- Use to visit URLs from search results\n"
        "- Use to open web applications for interaction\n"
        "- Use to verify deployed websites are working\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("url", "string", "The URL to navigate to (include https:// or file://)"),
        _param("intent", "string", "Purpose: navigational, informational, or transactional", required=False),
        _param("focus", "string", "Specific topic to focus on when reading the page", required=False),
    ]),

    _tool("browser_view",
        "View the current browser page content and screenshot.\n\n"
        "<instructions>\n"
        "- Page content is automatically provided after browser_navigate — use this only to RE-CHECK\n"
        "- Use to check updated state after interactions (clicks, form submissions)\n"
        "- Can be used repeatedly to monitor completion of web operations\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when waiting for pages to fully load\n"
        "- Use when checking latest state after interactions\n"
        "- Use to take screenshots of pages in specific states\n"
        "</recommended_usage>",
    []),

    _tool("browser_click",
        "Click an element on the browser page.\n\n"
        "<instructions>\n"
        "- Provide either element index OR coordinates — prefer index when available\n"
        "- Element indices come from browser_navigate/browser_view results\n"
        "- Ensure target element is visible and clickable before clicking\n"
        "- For elements not marked in the screenshot, use coordinates\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to click buttons, links, and interactive elements\n"
        "- Use to trigger page interactions and form submissions\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("index", "integer", "Index number of the element to click", required=False),
        _param("coordinate_x", "number", "X coordinate to click", required=False),
        _param("coordinate_y", "number", "Y coordinate to click", required=False),
    ]),

    _tool("browser_input",
        "Clear and type text into an input field on the browser page.\n\n"
        "<instructions>\n"
        "- This tool FIRST CLEARS existing text, then inputs new text\n"
        "- Provide either element index OR coordinates — prefer index\n"
        "- Set press_enter=true to submit forms after typing\n"
        "- Ensure target element is editable before inputting\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to fill form fields, search boxes, login forms\n"
        "- Use to update existing input values\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("text", "string", "Text to input"),
        _param("index", "integer", "Index of the input element", required=False),
        _param("coordinate_x", "number", "X coordinate of the input", required=False),
        _param("coordinate_y", "number", "Y coordinate of the input", required=False),
        _param("press_enter", "boolean", "Whether to press Enter after input", required=False),
    ]),

    _tool("browser_scroll",
        "Scroll the browser page or a specific container element.\n\n"
        "<instructions>\n"
        "- direction refers to content viewing direction: 'down' scrolls to see content below\n"
        "- By default scrolls 1x viewport size; use to_end=true to jump to top/bottom\n"
        "- MUST save key information to files after every two scroll operations\n"
        "- Multiple scrolls may be needed for pages with dynamic loading\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to view off-screen content on long pages\n"
        "- Use when Markdown extraction is incomplete\n"
        "- Use for pages with rich visual elements that need scrolling\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("direction", "string", "Direction: up, down, left, right"),
        _param("target", "string", "Target: page or container", required=False),
        _param("to_end", "boolean", "Scroll to the very end", required=False),
    ]),

    _tool("browser_select",
        "Select an option from a dropdown menu.\n\n"
        "<instructions>\n"
        "- Ensure dropdown is interactive and visible before selecting\n"
        "- Use the dropdown element index and option index (0-based)\n"
        "</instructions>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("index", "integer", "Index of the dropdown element"),
        _param("option_index", "integer", "Index of the option to select (0-based)"),
    ]),

    _tool("browser_find",
        "Find text on the current browser page.\n\n"
        "<instructions>\n"
        "- Returns matching text with surrounding context\n"
        "- Consider partial matches and case sensitivity\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to search for specific text content on the page\n"
        "- Use to verify presence of certain keywords or elements\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("keyword", "string", "Text to search for"),
    ]),

    _tool("browser_save_image",
        "Save an image from the browser page to a local file.\n\n"
        "<instructions>\n"
        "- Coordinates should point to the center of the image element\n"
        "- Use semantic, human-readable base names: 'hero_background', not 'img1'\n"
        "- Extension is added automatically based on image format\n"
        "- Set save_dir to the project working directory to avoid extra file copying\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to download images from web pages for use in projects\n"
        "- Use to save design references and inspiration images\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("coordinate_x", "number", "X coordinate of the image"),
        _param("coordinate_y", "number", "Y coordinate of the image"),
        _param("save_dir", "string", "Directory to save the image"),
        _param("base_name", "string", "Base filename (without extension)"),
    ]),

    _tool("browser_press_key",
        "Press a key or key combination in the browser.\n\n"
        "<instructions>\n"
        "- Use standard key names: Enter, Tab, Escape, ArrowUp, ArrowDown\n"
        "- For combinations use + separator: Control+C, Shift+Tab, Control+Enter\n"
        "</instructions>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("key", "string", "Key name (e.g., Enter, Tab, Control+C)"),
    ]),

    _tool("browser_upload",
        "Upload a file to a file input element on the browser page.\n\n"
        "<instructions>\n"
        "- Ensure file path is valid and accessible\n"
        "- Target file input elements using their index numbers\n"
        "</instructions>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("index", "integer", "Index of the file input element"),
        _param("path", "string", "Absolute path to the file to upload"),
    ]),

    _tool("browser_console",
        "Execute JavaScript in the browser console.\n\n"
        "<instructions>\n"
        "- Ensure code is safe and controlled\n"
        "- The return value (if any) will be captured and returned\n"
        "- Use for DOM manipulation, data extraction, debugging\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to extract data from page elements\n"
        "- Use to debug page functionality\n"
        "- Use to manipulate DOM when other browser tools are insufficient\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("javascript", "string", "JavaScript code to execute"),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 4. SEARCH TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("web_search",
        "Search the web for information across various sources.\n\n"
        "<instructions>\n"
        "- MUST use this tool to access up-to-date or external information — DO NOT rely solely on internal knowledge\n"
        "- Each search may contain up to 3 query variants — these MUST be variants of the same intent, NOT different goals\n"
        "- For non-English queries, include at least one English query variant to expand coverage\n"
        "- DO NOT use advanced search syntax (quotes, filters, operators) — they are not supported\n"
        "- Search result snippets are often incomplete — follow up by visiting source URLs with browser_navigate\n"
        "- For complex research, break into step-by-step searches instead of one complex query\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use 'info' type for general web information, articles, factual answers\n"
        "- Use 'image' type for finding images relevant to a topic\n"
        "- Use 'api' type for finding callable APIs with documentation\n"
        "- Use 'news' type for time-sensitive current events\n"
        "- Use 'research' type for academic papers and whitepapers\n"
        "- Use 'data' type for datasets and structured data sources\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        ("queries", {
            "type": "array",
            "description": "Up to 3 search query variants (same intent, different wording)",
            "items": {"type": "string"}
        }, True),
        _param("type", "string", "Search type: info, image, api, news, tool, data, research"),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 5. MATCH TOOLS (File Search)
    # ══════════════════════════════════════════════════════════════════════════

    _tool("glob",
        "Find files by name pattern using glob-style matching.\n\n"
        "<instructions>\n"
        "- Use absolute paths in patterns: /root/workspace/**/*.html\n"
        "- Results are returned in descending order of modification time\n"
        "- Use ** for recursive directory matching\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to locate files by name, extension, or directory pattern\n"
        "- Use to find all HTML/CSS/JS files in a project\n"
        "- Use to discover project structure\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("pattern", "string", "Glob pattern (e.g., /root/workspace/**/*.py)"),
    ]),

    _tool("grep",
        "Search file contents using regex-based full-text matching.\n\n"
        "<instructions>\n"
        "- scope defines the glob pattern restricting which files to search\n"
        "- regex is case-sensitive by default\n"
        "- Use context_lines to see surrounding code for better understanding\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to find specific text, function names, or patterns across files\n"
        "- Use to locate configuration values or error messages in logs\n"
        "- Use to understand code structure by searching for class/function definitions\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("pattern", "string", "Regex pattern to search for"),
        _param("scope", "string", "Glob pattern defining which files to search"),
        _param("context_lines", "integer", "Lines of context around matches", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 6. COMMUNICATION TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("message",
        "Send a message to the user.\n\n"
        "<instructions>\n"
        "- MUST use this tool for ALL communication with users — never respond with plain text\n"
        "- type='info': Progress updates, acknowledgments. User does NOT need to respond. Use freely.\n"
        "- type='ask': Questions that BLOCK until user responds. Use ONLY when you genuinely cannot proceed without user input. This is RARE.\n"
        "- type='result': Final delivery of completed work. Ends the task. Include all relevant file attachments.\n"
        "- Write naturally in the user's language. No robotic templates like 'Задача выполнена. Результат:'\n"
        "- Keep info messages brief — one or two sentences about what you're doing\n"
        "- For result messages, include preview/download links and attach all deliverable files\n"
        "- DO NOT send multiple consecutive messages without user reply — if you need a response, use 'ask'\n"
        "- DO NOT use 'ask' when you can figure out the answer from context or make a reasonable decision yourself\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use 'info' to acknowledge task start and report progress checkpoints\n"
        "- Use 'ask' ONLY for truly missing critical information (server IP not in history, ambiguous requirements)\n"
        "- Use 'result' to deliver final work with files, links, and summary\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("text", "string", "Message text"),
        _param("type", "string", "Message type: info (progress), ask (blocking question), result (final delivery)"),
        ("attachments", {
            "type": "array",
            "description": "List of file paths to attach with the message",
            "items": {"type": "string"}
        }, False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 7. PLAN TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("plan",
        "Create, update, or advance the structured task plan.\n\n"
        "<instructions>\n"
        "- Use 'update' action to create a new plan or revise an existing one\n"
        "- Use 'advance' action to move to the next phase when current phase is complete\n"
        "- Phase count scales with complexity: simple tasks (2-3), typical (4-6), complex (8+)\n"
        "- Phases should be high-level units of work, not implementation details\n"
        "- Make delivering results to the user a separate final phase\n"
        "- Update the plan when significant new information emerges or requirements change\n"
        "- For simple tasks (single command, quick answer), a plan is optional\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use at the start of complex multi-step tasks\n"
        "- Use when user changes requirements mid-task\n"
        "- Use to track progress on long-running operations\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("action", "string", "Action: update (create/revise plan) or advance (move to next phase)"),
        _param("goal", "string", "Overall goal of the task", required=False),
        ("phases", {
            "type": "array",
            "description": "List of phases with id, title, description",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Phase ID"},
                    "title": {"type": "string", "description": "Phase title"},
                    "description": {"type": "string", "description": "Phase description"}
                },
                "required": ["id", "title"]
            }
        }, False),
        _param("current_phase_id", "integer", "Current phase ID"),
        _param("next_phase_id", "integer", "Next phase ID (for advance action)", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 8. DEPLOY TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("deploy_to_vps",
        "Deploy files to a VPS server via SSH. Configures Nginx and SSL.\n\n"
        "<instructions>\n"
        "- Use for automated deployment of static sites, Node.js apps, or Python apps\n"
        "- Ensure source_dir contains all necessary files before deploying\n"
        "- For static sites, Nginx is configured automatically\n"
        "- For Node.js apps, PM2 is used as process manager\n"
        "- For Python apps, Gunicorn is configured\n"
        "- If this tool fails, fall back to manual deployment via ssh_exec\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to deploy completed landing pages to production servers\n"
        "- Use to set up Nginx virtual hosts with SSL\n"
        "- Use when user provides a domain and server for deployment\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("source_dir", "string", "Local directory with files to deploy"),
        _param("domain", "string", "Domain name for the site"),
        _param("server_host", "string", "VPS IP or hostname", required=False),
        _param("server_user", "string", "SSH user (default: root)", required=False),
        _param("deploy_type", "string", "Type: static (Nginx), nodejs (PM2), python (Gunicorn)", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 9. SCHEDULE TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("schedule_task",
        "Schedule a task to run at a specific time or interval.\n\n"
        "<instructions>\n"
        "- Use 'cron' type with 6-field format: seconds minutes hours day-of-month month day-of-week\n"
        "- Use 'interval' type for simple recurring tasks (minimum 300 seconds for repeating)\n"
        "- The prompt field describes WHAT to do at execution time — don't restate scheduling details\n"
        "- Only one scheduled task can exist at a time\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when user requests a task to run at a specific future time\n"
        "- Use for periodic monitoring or maintenance tasks\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("name", "string", "Task name"),
        _param("prompt", "string", "What to do at execution time"),
        _param("type", "string", "Schedule type: cron or interval"),
        _param("repeat", "boolean", "Whether to repeat"),
        _param("cron", "string", "Cron expression (6-field format)", required=False),
        _param("interval", "integer", "Interval in seconds", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 10. MEMORY & DELIVERY TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("update_scratchpad",
        "Save critical facts to the agent's persistent scratchpad.\n\n"
        "<instructions>\n"
        "- The scratchpad NEVER gets compressed during context compaction — facts survive indefinitely\n"
        "- ALWAYS save immediately after discovering: server IPs, SSH passwords, file paths, database credentials, API keys, domain names, port numbers\n"
        "- Use descriptive keys: 'server_ip', 'ssh_password', 'wordpress_admin_url', 'db_name'\n"
        "- Update existing keys when values change (e.g., after password reset)\n"
        "- This is your long-term memory — use it aggressively\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use IMMEDIATELY when user provides server credentials\n"
        "- Use after creating files to remember their paths\n"
        "- Use after installing services to remember URLs and passwords\n"
        "- Use to save any fact you'll need in future messages\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("key", "string", "Short descriptive key (e.g., 'server_ip', 'db_password', 'nginx_config_path')"),
        _param("value", "string", "The value to remember"),
    ]),

    _tool("create_archive",
        "Package project files into a downloadable ZIP archive.\n\n"
        "<instructions>\n"
        "- Use after completing a project to deliver all files to the user\n"
        "- Creates a ZIP with all project files, optional README, and deploy instructions\n"
        "- Use descriptive project_name: 'arcane_premium_landing', not 'project'\n"
        "- After creating, send the download link via message(type='result')\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to package completed landing pages for delivery\n"
        "- Use to bundle multi-file projects (HTML + CSS + JS + images)\n"
        "- Use as the final step before sending result to user\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("project_dir", "string", "Absolute path to the project directory to archive"),
        _param("project_name", "string", "Human-readable project name for the archive filename"),
        _param("include_readme", "boolean", "Include auto-generated README.md (default: true)", required=False),
        _param("include_deploy_guide", "boolean", "Include deployment instructions (default: true)", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 11. DESIGN & CREATIVE TOOLS
    # ══════════════════════════════════════════════════════════════════════════

    _tool("pexels_search",
        "Search for high-quality, royalty-free stock photos using Pexels API.\n\n"
        "<instructions>\n"
        "- ALWAYS use this for real photos in landing pages — NEVER use placeholder images or gray boxes\n"
        "- Use specific, descriptive queries: 'luxury barbershop interior dark moody' not just 'barbershop'\n"
        "- Request 5-10 results to have options to choose from\n"
        "- Photos are free for commercial use, no attribution required\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when creating landing pages that need real photography\n"
        "- Use for hero backgrounds, team photos, product imagery\n"
        "- Use before writing HTML — have photo URLs ready\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("query", "string", "Search query (e.g., 'luxury barbershop interior', 'gourmet plating')"),
        _param("per_page", "integer", "Number of results to return (default 5)", required=False),
    ]),

    _tool("image_generate",
        "Generate images using AI (GPT-5 Image / GPT Image 1.5 / Nano Banana). Returns file paths.\n\n"
        "<instructions>\n"
        "- Use detailed, specific prompts for best results\n"
        "- Specify style explicitly: photorealistic, illustration, cinematic, 3d, editorial, hero\n"
        "- For landing pages: ALWAYS use this for hero sections, banners, and key visuals. Use pexels_search ONLY for secondary images — use this for custom illustrations/graphics\n"
        "- Generated images are saved locally and can be embedded in HTML\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for ALL hero sections, banners, and above-the-fold visuals\n"
        "- Use for custom illustrations, product shots, and lifestyle imagery\n"
        "- Use for logos, mascots, unique visual elements. Generate 3-5 images at project start\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("prompt", "string", "Detailed description of the image to generate"),
        _param("style", "string", "Style: photorealistic, illustration, cinematic, 3d, editorial, hero, minimal", required=False),
        _param("size", "string", "Size: 1024x1024, 1792x1024, 1024x1792", required=False),
        _param("quality", "string", "Quality: standard or hd", required=False),
        _param("n", "integer", "Number of images (1-4)", required=False),
        _param("save_dir", "string", "Directory to save generated images", required=False),
    ]),

    _tool("design_judge",
        "Evaluate a generated website using Vision AI. Takes real screenshots and scores the design.\n\n"
        "<instructions>\n"
        "- Provide html_path — the tool automatically takes desktop (1440px) and mobile (390px) screenshots\n"
        "- Returns scores, identified issues, and specific CSS/HTML fix instructions\n"
        "- If score < 8.0, fix the issues and re-evaluate\n"
        "- Use context parameter to explain what was requested for better evaluation\n"
        "- ALWAYS run this after generating a landing page, before delivering to user\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use after creating any landing page or website\n"
        "- Use to identify visual issues before delivery\n"
        "- Use iteratively: generate → judge → fix → judge again\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("screenshot_path", "string", "Path to screenshot image", required=False),
        _param("html_path", "string", "Path to HTML file to evaluate", required=False),
        _param("context", "string", "Context about what was requested", required=False),
        _param("model", "string", "Vision model (default: google/gemini-2.5-flash)", required=False),
        _param("include_mobile", "boolean", "Also evaluate mobile viewport 390px (default: true)", required=False),
    ]),

    _tool("get_template",
        "Get a premium blueprint HTML scaffold for landing page generation.\n\n"
        "<instructions>\n"
        "- Use BEFORE writing HTML — get a proven layout structure first\n"
        "- Available types: dark_luxury, warm_editorial, clean_tech, bold_energy, soft_wellness, japandi_minimal, neobrutalist\n"
        "- Pass 'list' to see all available templates with descriptions\n"
        "- The template provides structure — you still need to customize content, colors, and images\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use at the start of any landing page project\n"
        "- Use to get a proven layout that scores well with design_judge\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("template_type", "string", "Blueprint type: dark_luxury, warm_editorial, clean_tech, bold_energy, soft_wellness, japandi_minimal, neobrutalist, or 'list' to see all"),
    ]),

    _tool("search_design_inspiration",
        "Search the curated design reference database (1000+ premium websites) for inspiration.\n\n"
        "<instructions>\n"
        "- MUST be called BEFORE generating any landing page — this is Phase 0 of web design\n"
        "- Returns screenshot URLs, color palettes, typography choices, layout patterns\n"
        "- Study the returned references carefully — they define the quality standard\n"
        "- Save key insights to scratchpad with update_scratchpad(key='design_references', value='...')\n"
        "- Sources include Awwwards, Land-book, Godly, SiteInspire — the best of the web\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use as the FIRST step when creating any landing page or website\n"
        "- Use to find color palettes, typography, and layout patterns\n"
        "- Use to understand current design trends for the target industry\n"
        "</recommended_usage>",
    [
        _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
        _param("query", "string", "Natural language description of the desired design (e.g., 'dark luxury hotel landing page')"),
        _param("style", "string", "Filter by style: luxury, editorial, tech-modern, bold, wellness, minimal, brutalist, fashion, cinematic, hospitality", required=False),
        _param("mood", "string", "Filter by mood: elegant, bold, calm, energetic, sophisticated, playful, professional", required=False),
        _param("industry", "string", "Filter by industry: hospitality, saas, fashion, fitness, food, beauty, architecture, medical, ecommerce", required=False),
        _param("min_tier", "string", "Minimum quality tier: S (best), A (great), B (good). Default: A", required=False),
        _param("limit", "integer", "Number of references to return (default 8)", required=False),
    ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 11. DOCUMENT TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    _tool("md_to_pdf",
        "Convert a Markdown file to a professionally styled PDF document.\n\n"
        "<instructions>\n"
        "- Input must be a valid .md file with proper Markdown syntax\n"
        "- Output PDF includes styled headers, tables, code blocks, and blockquotes\n"
        "- If output_path is not specified, replaces .md extension with .pdf\n"
        "- Use for final deliverables: reports, proposals, documentation\n"
        "- Ensure Markdown content is complete and proofread BEFORE converting\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when user asks for a PDF report or document\n"
        "- Use after writing a Markdown report to create downloadable PDF\n"
        "- Use for creating professional proposals and documentation\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("input_path", "string", "Absolute path to the Markdown (.md) file to convert"),
            _param("output_path", "string", "Absolute path for the output PDF file", False),
        ]),

    _tool("create_excel",
        "Create a professionally formatted Excel spreadsheet with multiple sheets, headers, and data.\n\n"
        "<instructions>\n"
        "- Provide data as structured sheets array with name, headers, and rows\n"
        "- Headers are auto-styled with dark background and white text\n"
        "- Column widths auto-adjust to content\n"
        "- Each sheet can have different structure and data\n"
        "- Use proper data types: numbers as numbers, not strings\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when user needs a spreadsheet, table, or data export\n"
        "- Use for financial reports, price lists, inventory\n"
        "- Use for creating structured data that user can edit in Excel\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("output_path", "string", "Absolute path for the output .xlsx file"),
            ("sheets", {"type": "array", "description": "Array of sheet objects: {name, headers: [...], rows: [[...], ...]}", "items": {"type": "object"}}, True),
            _param("title", "string", "Workbook title for metadata", False),
        ]),

    _tool("read_document",
        "Read and extract text content from PDF, Word (.docx), Excel (.xlsx), and CSV files.\n\n"
        "<instructions>\n"
        "- Supports: .pdf, .docx, .xlsx, .csv, .tsv\n"
        "- PDF extraction includes both text and tables\n"
        "- Word extraction preserves headings and tables\n"
        "- Excel reads all sheets with cell values\n"
        "- Large documents are truncated at max_chars\n"
        "- Use this tool FIRST when user uploads or mentions a document\n"
        "- After reading, save key findings to scratchpad\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when user uploads a document and asks to analyze it\n"
        "- Use when you need to read a PDF, Word, or Excel file\n"
        "- Use before modifying or converting documents\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("file_path", "string", "Absolute path to the document file"),
            _param("max_chars", "integer", "Maximum characters to extract. Default: 50000", False),
        ]),

    _tool("create_presentation",
        "Create a PowerPoint (.pptx) presentation with styled slides.\n\n"
        "<instructions>\n"
        "- Provide slides as array of objects with type, title, body/bullets\n"
        "- Slide types: 'title' (title slide), 'content' (regular slide)\n"
        "- Use bullets array for bullet-point slides, body for paragraph text\n"
        "- Keep bullet points concise — max 6-8 per slide\n"
        "- Plan slide structure BEFORE creating\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use when user asks for a presentation or slide deck\n"
        "- Use for business proposals, project updates, pitches\n"
        "- Use for educational or training materials\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("output_path", "string", "Absolute path for the output .pptx file"),
            ("slides", {"type": "array", "description": "Array of slide objects: {type, title, body, bullets, image}", "items": {"type": "object"}}, True),
            _param("title", "string", "Presentation title", False),
            _param("theme_color", "string", "Theme hex color without #. Default: 1A1A2E", False),
        ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 12. MEDIA & VISUALIZATION TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    _tool("image_edit",
        "Edit images: resize, crop, rotate, watermark, compress, blur, grayscale, convert.\n\n"
        "<instructions>\n"
        "- Actions: resize, crop, rotate, watermark, convert, compress, blur, grayscale\n"
        "- resize: params.width, params.height, keep_aspect=true\n"
        "- crop: params.left, top, right, bottom in pixels\n"
        "- watermark: params.text, optional params.font_size\n"
        "- compress: params.quality (1-100)\n"
        "- If output_path not specified, overwrites input\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to resize, crop, or optimize images\n"
        "- Use before deploying websites to optimize image sizes\n"
        "- Use to add watermarks or convert formats\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("input_path", "string", "Absolute path to the input image"),
            _param("action", "string", "Action: resize, crop, rotate, watermark, convert, compress, blur, grayscale"),
            _param("output_path", "string", "Output path. If omitted, overwrites input", False),
            ("params", {"type": "object", "description": "Action-specific params"}, False),
        ]),

    _tool("render_diagram",
        "Render diagram source (Mermaid, PlantUML, D2) to PNG image.\n\n"
        "<instructions>\n"
        "- Supports Mermaid (.mmd), PlantUML (.puml), D2 (.d2)\n"
        "- Auto-detects format from extension\n"
        "- Can accept code directly via 'code' parameter\n"
        "- Output is PNG\n"
        "- Verify syntax before rendering\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for architecture diagrams, flowcharts, sequence diagrams\n"
        "- Use for database schemas and ER diagrams\n"
        "- Use for system design documentation\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("input_path", "string", "Path to diagram source file", False),
            _param("output_path", "string", "Output PNG path", False),
            _param("code", "string", "Diagram source code (if no input_path)", False),
            _param("type", "string", "Diagram type: mermaid, plantuml, d2", False),
        ]),

    _tool("generate_chart",
        "Generate data visualizations: bar, line, pie, scatter charts.\n\n"
        "<instructions>\n"
        "- chart_type: bar, line, pie, horizontal_bar, scatter\n"
        "- data: {labels: [...], values: [...], colors: [...] (optional)}\n"
        "- For scatter: also provide data.x\n"
        "- style: 'dark' (default) or 'light'\n"
        "- Output is high-resolution PNG (150 DPI)\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for charts, graphs, data visualization\n"
        "- Use for statistics, comparisons, trends\n"
        "- Use in reports and presentations\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("output_path", "string", "Output PNG path"),
            _param("chart_type", "string", "Chart type: bar, line, pie, horizontal_bar, scatter"),
            _param("title", "string", "Chart title"),
            ("data", {"type": "object", "description": "Chart data: {labels, values, colors (optional)}"}, True),
            _param("style", "string", "Visual style: dark or light", False),
        ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 13. ADVANCED SHELL TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    _tool("shell_send",
        "Send input to a running interactive process (stdin).\n\n"
        "<instructions>\n"
        "- Use ONLY when a process is waiting for input\n"
        "- Add newline at end to press Enter\n"
        "- Check with shell_view first\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for mysql_secure_installation prompts\n"
        "- Use for certbot interactive setup\n"
        "- Use for Y/N questions in installers\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("session", "string", "Shell session identifier"),
            _param("input", "string", "Text to send to stdin"),
        ]),

    _tool("shell_wait",
        "Wait for a running command to complete.\n\n"
        "<instructions>\n"
        "- Use after shell_exec when command needs more time\n"
        "- If timeout expires, process still running\n"
        "- DO NOT use for daemon processes\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use after apt install or pip install\n"
        "- Use after compilation or build processes\n"
        "- Use when shell_exec returns 'still running'\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("session", "string", "Shell session identifier"),
            _param("timeout", "integer", "Max seconds to wait. Default: 30", False),
        ]),

    _tool("shell_kill",
        "Terminate a running process in a shell session.\n\n"
        "<instructions>\n"
        "- Use when process is stuck or no longer needed\n"
        "- Try shell_wait first before killing\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use to stop background processes\n"
        "- Use to clean up dead processes\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("session", "string", "Shell session identifier"),
        ]),

    # ══════════════════════════════════════════════════════════════════════════
    # 14. ADVANCED BROWSER TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    _tool("browser_fill_form",
        "Fill out multiple form fields at once.\n\n"
        "<instructions>\n"
        "- Provide fields as array of {index, value} objects\n"
        "- Ensure fields are visible and interactive\n"
        "- More efficient than multiple browser_input calls\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for multi-field forms\n"
        "- Use for CMS setup wizards\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            ("fields", {"type": "array", "description": "Array of {index, value} objects", "items": {"type": "object"}}, True),
        ]),

    _tool("browser_move_mouse",
        "Move mouse cursor to a position on the page.\n\n"
        "<instructions>\n"
        "- Use coordinates relative to viewport\n"
        "- For clicking, use browser_click directly\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for triggering hover effects\n"
        "- Use for revealing dropdown menus\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("x", "integer", "Horizontal coordinate"),
            _param("y", "integer", "Vertical coordinate"),
        ]),

    _tool("browser_close",
        "Close the browser window and release resources.\n\n"
        "<instructions>\n"
        "- Use only when browser operations are completely finished\n"
        "- After closing, browser_navigate opens new session\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use after completing browser-based tasks\n"
        "- Use to free resources\n"
        "</recommended_usage>",
        []),

    # ══════════════════════════════════════════════════════════════════════════
    # 15. ADVANCED TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    _tool("expose_port",
        "Expose a local port for temporary public access via tunnel.\n\n"
        "<instructions>\n"
        "- Creates temporary public URL for a local port\n"
        "- Service must be running before exposing\n"
        "- DO NOT use for production\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for preview links\n"
        "- Use for webhook testing\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("port", "integer", "Local port number to expose"),
        ]),

    _tool("speech_to_text",
        "Transcribe audio/video files to text using AI.\n\n"
        "<instructions>\n"
        "- Supports: .mp3, .wav, .mp4, .webm, .m4a, .ogg\n"
        "- Uses OpenAI Whisper for transcription\n"
        "- Specify language for better accuracy\n"
        "- Save transcription to file for processing\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for audio/video transcription\n"
        "- Use for meeting recordings, interviews\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("file_path", "string", "Path to audio/video file"),
            _param("language", "string", "Language code (ru, en, etc.)", False),
        ]),

    _tool("text_to_speech",
        "Generate natural speech audio from text using AI.\n\n"
        "<instructions>\n"
        "- Output is MP3\n"
        "- Voices: alloy, echo, fable, onyx, nova, shimmer\n"
        "- Speed: 0.25 to 4.0 (1.0 normal)\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for generating voiceovers\n"
        "- Use for accessibility\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("text", "string", "Text to convert to speech"),
            _param("output_path", "string", "Output MP3 path"),
            _param("voice", "string", "Voice name. Default: alloy", False),
            _param("speed", "number", "Speed 0.25-4.0. Default: 1.0", False),
        ]),

    _tool("parallel_map",
        "Execute multiple similar subtasks in parallel.\n\n"
        "<instructions>\n"
        "- Provide items array and action tool name\n"
        "- max_concurrent controls parallelism (default: 5)\n"
        "- Results aggregated with status for each item\n"
        "- Use for homogeneous tasks only\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use for bulk file operations\n"
        "- Use for checking multiple URLs\n"
        "- Use when processing 5+ similar items\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            ("items", {"type": "array", "description": "Array of items to process", "items": {"type": "object"}}, True),
            _param("action", "string", "Tool name to execute for each item"),
            _param("max_concurrent", "integer", "Max parallel executions. Default: 5", False),
        ]),

    # ── Skills System ──────────────────────────────────────────────────────────
    _tool("read_skill",
        "Read a skill's SKILL.md file for best practices, workflows, and instructions.\n\n"
        "<instructions>\n"
        "- Skills are modular knowledge files that guide the agent on specific tasks\n"
        "- MUST read relevant skills BEFORE starting complex tasks\n"
        "- Use list_skills first to see what's available\n"
        "</instructions>\n\n"
        "<recommended_usage>\n"
        "- Use before creating landing pages, APIs, bots, or integrations\n"
        "- Use when encountering unfamiliar technology\n"
        "</recommended_usage>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("name", "string", "Name of the skill to read (e.g., 'landing-page', 'n8n', 'telegram-bot')"),
        ]),

    _tool("list_skills",
        "List all available skills with their descriptions.\n\n"
        "<recommended_usage>\n"
        "- Use at the start of complex tasks to check available knowledge\n"
        "- Use when unsure which skill applies\n"
        "</recommended_usage>",
        []),

    # ── WebDev Scaffolding ───────────────────────────────────────────────────────
    _tool("init_project",
        "Initialize a new web project with modern scaffolding.\n\n"
        "<instructions>\n"
        "- Creates project directory with Vite + React + TypeScript + TailwindCSS\n"
        "- Installs dependencies and sets up build pipeline\n"
        "- Use for any web application, not just landing pages\n"
        "</instructions>\n\n"
        "<scaffold_types>\n"
        "- react-vite: Vite + React + TypeScript + TailwindCSS\n"
        "- static: Plain HTML/CSS/JS with live reload\n"
        "- fastapi: FastAPI + SQLAlchemy + Alembic backend\n"
        "</scaffold_types>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("name", "string", "Project directory name (e.g., 'my-app')"),
            _param("scaffold", "string", "Scaffold type: react-vite, static, or fastapi"),
            _param("description", "string", "Brief project description", False),
        ]),

    # ── Enhanced Search ────────────────────────────────────────────────────────
    _tool("search",
        "Search for information across various sources with specialized types.\n\n"
        "<supported_types>\n"
        "- info: General web information, articles, factual answers\n"
        "- image: Images relevant to the topic (auto-downloaded)\n"
        "- api: API documentation and sample code\n"
        "- news: Time-sensitive news from trusted sources\n"
        "- data: Public datasets, tables, structured data\n"
        "- research: Academic papers, whitepapers, reports\n"
        "</supported_types>\n\n"
        "<instructions>\n"
        "- Each search may contain up to 3 query variants of the same intent\n"
        "- For non-English queries, include at least one English variant\n"
        "- Use specific type for better results\n"
        "</instructions>",
        [
            _param("brief", "string", "A one-sentence preamble describing the purpose of this operation"),
            _param("query", "string", "Search query (up to 3 keywords or phrases)"),
            _param("type", "string", "Search type: info, image, api, news, data, or research. Default: info", False),
        ]),

]


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class ToolRegistry:
    """
    Registry of all available tools.
    Provides schema for LLM function calling and dispatches execution.
    """

    def __init__(self):
        self._tools = {t["function"]["name"]: t for t in TOOLS}
        self._handlers: dict[str, Any] = {}

    def get_tools_schema(self) -> list[dict]:
        """Get all tool definitions in OpenAI function calling format."""
        return [
            {"type": t["type"], "function": t["function"]}
            for t in self._tools.values()
        ]

    def get_tool_names(self) -> list[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    def register_handler(self, tool_name: str, handler) -> None:
        """Register an execution handler for a tool."""
        self._handlers[tool_name] = handler

    def get_handler(self, tool_name: str):
        """Get the execution handler for a tool."""
        return self._handlers.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is registered."""
        return tool_name in self._tools
