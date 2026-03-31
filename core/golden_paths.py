"""
ARCANE Golden Paths — WOW Landing Page Templates & ZIP Archive Delivery

Provides pre-built, high-quality templates for common user requests:
1. Landing pages (SaaS, portfolio, product, restaurant, etc.)
2. Dashboards (analytics, admin, CRM)
3. Email templates (marketing, transactional)

Also handles packaging task results into downloadable ZIP archives
with proper structure, README, and deployment instructions.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import zipfile
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("core.golden_paths")


# ═══════════════════════════════════════════════════════════════════════════════
# GOLDEN PATH TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════════

LANDING_PAGE_TEMPLATES = {
    "dark_luxury": {
        "name": "Dark Luxury",
        "description": "Premium dark theme for barbershops, nightclubs, premium auto, jewelry",
        "file": "dark_luxury.html"
    },
    "warm_editorial": {
        "name": "Warm Editorial",
        "description": "Elegant warm theme for restaurants, cafes, bakeries, wine bars",
        "file": "warm_editorial.html"
    },
    "clean_tech": {
        "name": "Clean Tech",
        "description": "Modern clean theme for SaaS, fintech, AI startups, B2B",
        "file": "clean_tech.html"
    },
    "bold_energy": {
        "name": "Bold Energy",
        "description": "Aggressive bold theme for fitness, sports, events, extreme",
        "file": "bold_energy.html"
    },
    "soft_wellness": {
        "name": "Soft Wellness",
        "description": "Calm soft theme for medical, spa, beauty, education",
        "file": "soft_wellness.html"
    },
    "japandi_minimal": {
        "name": "Japandi Minimal",
        "description": "Ultra-minimal theme for architecture, interior design, portfolios",
        "file": "japandi_minimal.html"
    },
    "neobrutalist": {
        "name": "Neobrutalist",
        "description": "Edgy brutalist theme for creative agencies, web3, youth brands",
        "file": "neobrutalist.html"
    }
}


def get_template(template_type: str) -> Optional[dict]:
    """Get a golden path template by type."""
    return LANDING_PAGE_TEMPLATES.get(template_type)


def list_templates() -> list[dict]:
    """List all available golden path templates."""
    return [
        {"type": key, "name": val["name"], "description": val["description"]}
        for key, val in LANDING_PAGE_TEMPLATES.items()
    ]


def generate_template_prompt(template_type: str, user_details: dict) -> str:
    """
    Generate a detailed prompt for the LLM to create a landing page
    based on the golden path template and user's specific details.
    """
    template = get_template(template_type)
    if not template:
        return ""

    colors = template["color_scheme"]
    sections = template["sections"]

    prompt = f"""Create a stunning, production-ready landing page using the following template:

Template: {template['name']}
Style: {template['style']}

Color Scheme:
- Primary: {colors['primary']}
- Secondary: {colors['secondary']}
- Accent: {colors['accent']}
- Background: {colors['background']}
- Text: {colors['text']}

Required Sections (in order):
{chr(10).join(f'  {i+1}. {section.replace("_", " ").title()}' for i, section in enumerate(sections))}

User Details:
{json.dumps(user_details, indent=2, ensure_ascii=False)}

Technical Requirements:
- Single HTML file with embedded CSS (TailwindCSS via CDN)
- Responsive design (mobile-first with sm:, md:, lg:, xl: breakpoints)
- Smooth CSS animations: fade-in on scroll via IntersectionObserver, hover transitions (transition-all duration-300)
- Professional typography: Import 2 Google Fonts (one for headings, one for body)
- Semantic HTML5 with proper heading hierarchy (h1 > h2 > h3)
- Accessibility: ARIA labels, alt text on images, WCAG AA contrast ratios
- Performance: lazy-load images (loading="lazy"), minimal vanilla JS
- Include meta viewport, charset, title, description, Open Graph tags
- Use high-quality images from source.unsplash.com (800x600 for cards, 1920x1080 for hero)

DESIGN STANDARDS (MANDATORY — this is what separates amateur from agency-level):
- Hero section: Full-viewport height (min-h-screen), gradient overlay on background image, large bold headline (text-5xl md:text-7xl), glowing CTA button
- Cards: rounded-2xl, shadow-xl, hover:shadow-2xl hover:-translate-y-2 transition-all duration-300, backdrop-blur-sm bg-white/5 border border-white/10
- Buttons: bg-gradient-to-r, rounded-xl px-8 py-4 text-lg font-semibold, hover:scale-105 transition-transform, add subtle box-shadow glow
- Sections: py-20 md:py-32 padding, max-w-7xl mx-auto container, alternating background tones
- Colors: Use a cohesive palette with primary gradient (e.g., from-indigo-600 to-purple-600), dark background (#0f172a or #111827), light text
- Spacing: Generous whitespace, gap-8 between grid items, mb-16 between section title and content
- Footer: Multi-column grid with links, contact info, social icons (SVG), copyright
- Mobile menu: Hamburger icon with JS toggle, slide-in or fade-in animation

The page MUST look like it was designed by Pentagram or Fantasy Interactive.
Every section should have real, compelling content based on the user's details.
NEVER use placeholder data — if data is missing, use visible [PLACEHOLDER] markers.
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# ZIP ARCHIVE DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

def create_delivery_archive(
    project_dir: str,
    project_name: str = "arcane-project",
    include_readme: bool = True,
    include_deploy_instructions: bool = True,
    exclude_patterns: Optional[list[str]] = None,
) -> str:
    """
    Package project files into a downloadable ZIP archive.

    Args:
        project_dir: Path to the project directory
        project_name: Name for the archive
        include_readme: Whether to generate a README.md
        include_deploy_instructions: Whether to include deployment guide
        exclude_patterns: File patterns to exclude (e.g., ['node_modules', '.git'])

    Returns:
        Path to the created ZIP file
    """
    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # Bug #12 fix: validate project_dir is within allowed paths
    real_dir = os.path.realpath(project_dir)
    allowed = ["/root/workspace", "/tmp", "/home/arcane_sandbox", "/root/workspace"]  # P4-FIX: unified path
    # FIX 3: Use commonpath instead of startswith to prevent path traversal
    path_valid = False
    for a in allowed:
        try:
            if os.path.commonpath([real_dir, a]) == a:
                path_valid = True
                break
        except ValueError:
            continue
    if not path_valid:
        raise PermissionError(f"Access denied: {project_dir} is outside allowed directories")

    exclude = set(exclude_patterns or [
        "node_modules",
        ".git",
        "__pycache__",
        ".env",
        ".DS_Store",
        "*.pyc",
        ".venv",
        "venv",
        ".deliveries",
    ])

    # FIX 5: Write archive to /root/workspace/{project_name}/.deliveries/  # P4-FIX
    # so that _resolve_file_path() in compat.py can find it via PROJECTS_DIR.
    # P4-FIX BUG-005: Canonical path is /root/workspace/{project_id}/
    # All files served via /workspace/ nginx location -> /root/workspace/
    delivery_base = os.path.join("/root/workspace", project_name, ".deliveries")  # P4-FIX: unified path
    os.makedirs(delivery_base, exist_ok=True)
    archive_name = f"{project_name}_{uuid.uuid4().hex[:6]}"
    archive_path = os.path.join(delivery_base, f"{archive_name}.zip")

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            # Filter excluded directories
            dirs[:] = [d for d in dirs if d not in exclude]

            for file in files:
                # Check file exclusion patterns
                if any(file.endswith(pat.lstrip("*")) for pat in exclude if pat.startswith("*")):
                    continue
                if file in exclude:
                    continue

                filepath = os.path.join(root, file)
                arcname = os.path.join(
                    project_name,
                    os.path.relpath(filepath, project_dir),
                )
                try:
                    zf.write(filepath, arcname)
                except Exception as e:
                    logger.warning(f"Skipping file {filepath}: {e}")

        # Add README
        if include_readme:
            readme = _generate_readme(project_name, project_dir)
            zf.writestr(f"{project_name}/README.md", readme)

        # Add deploy instructions
        if include_deploy_instructions:
            deploy_guide = _generate_deploy_guide(project_name, project_dir)
            zf.writestr(f"{project_name}/DEPLOY.md", deploy_guide)

    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    logger.info(f"Created delivery archive: {archive_path} ({size_mb:.1f} MB)")

    return archive_path


def _generate_readme(project_name: str, project_dir: str) -> str:
    """Generate a README.md for the project archive."""
    # Detect project type based on files
    files = os.listdir(project_dir) if os.path.isdir(project_dir) else []
    has_html = any(f.endswith(".html") for f in files)
    has_package_json = "package.json" in files
    has_requirements = "requirements.txt" in files
    has_docker = "Dockerfile" in files or "docker-compose.yml" in files

    readme = f"""# {project_name}

Generated by [ARCANE AI](https://arcaneai.ru) — Autonomous AI Agent System.

## Project Structure

"""
    # List top-level files
    for f in sorted(files)[:20]:
        if not f.startswith("."):
            readme += f"- `{f}`\n"

    readme += "\n## Quick Start\n\n"

    if has_html:
        readme += "Open `index.html` in your browser to view the project.\n\n"
    if has_package_json:
        readme += "```bash\nnpm install\nnpm run dev\n```\n\n"
    if has_requirements:
        readme += "```bash\npip install -r requirements.txt\npython app.py\n```\n\n"
    if has_docker:
        readme += "```bash\ndocker-compose up -d\n```\n\n"

    readme += """## License

This project was generated by ARCANE AI. You are free to use, modify,
and distribute it for any purpose.
"""
    return readme


def _generate_deploy_guide(project_name: str, project_dir: str) -> str:
    """Generate deployment instructions."""
    files = os.listdir(project_dir) if os.path.isdir(project_dir) else []
    has_html = any(f.endswith(".html") for f in files)
    has_package_json = "package.json" in files

    guide = f"""# Deployment Guide — {project_name}

## Option 1: Static Hosting (Simplest)

"""
    if has_html:
        guide += """Upload the files to any static hosting:
- **Vercel**: `npx vercel --prod`
- **Netlify**: Drag & drop the folder at netlify.com
- **GitHub Pages**: Push to a `gh-pages` branch
- **Nginx**: Copy files to `/var/www/html/`

"""

    if has_package_json:
        guide += """## Option 2: Node.js Hosting

```bash
npm install
npm run build
# Deploy the `dist/` or `build/` folder
```

"""

    guide += """## Option 3: VPS Deployment

```bash
# On your VPS:
scp -r ./* user@your-server:/var/www/your-domain/
sudo systemctl reload nginx
```

## Option 4: Docker

```bash
docker build -t your-project .
docker run -p 80:80 your-project
```
"""
    return guide
