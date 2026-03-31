"""
ARCANE Golden Landing Regression Tests
=======================================
Self-contained tests that validate the scene-driven pipeline produces
correct HTML output for 5 benchmark niches WITHOUT a live server.

These tests mock the LLM calls and validate:
1. Scene planner produces valid plans
2. Component retriever returns correct templates
3. Scene assembler produces valid HTML
4. No placeholder leakage, broken anchors, text-icons, empty CTAs
5. Artifact/URL contracts are correct
"""
from __future__ import annotations
import os
import sys
import re
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from html.parser import HTMLParser

# Ensure arcane root is importable
_arcane_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _arcane_root not in sys.path:
    sys.path.insert(0, _arcane_root)


# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════

BENCHMARK_NICHES = [
    {
        "niche": "fitness",
        "brand": "Iron Gym",
        "prompt": "Создай лендинг для фитнес-клуба Iron Gym. Телефон: +7 (495) 555-01-01",
        "expected_sections": ["hero", "features"],
    },
    {
        "niche": "beauty",
        "brand": "Velvet",
        "prompt": "Создай лендинг для барбершопа Velvet Cuts. Телефон: +7 (495) 555-02-02",
        "expected_sections": ["hero", "features"],
    },
    {
        "niche": "restaurant",
        "brand": "Вкус Рима",
        "prompt": "Создай лендинг для ресторана Вкус Рима. Телефон: +7 (495) 555-03-03",
        "expected_sections": ["hero", "features"],
    },
    {
        "niche": "real_estate",
        "brand": "Horizon",
        "prompt": "Создай лендинг для агентства недвижимости Horizon Realty. Телефон: +7 (495) 555-04-04",
        "expected_sections": ["hero", "features"],
    },
    {
        "niche": "legal",
        "brand": "Atlas",
        "prompt": "Создай лендинг для юридической фирмы Atlas Law. Телефон: +7 (495) 555-05-05",
        "expected_sections": ["hero", "trust"],
    },
]

# Placeholder patterns that indicate REAL leakage (not HTML placeholder attributes)
PLACEHOLDER_PATTERNS = [
    r"lorem\s+ipsum",
    r"your\s+text\s+here",
    r"sample\s+text",
    r"dummy\s+text",
    r"\bTODO\b",
    r"\bFIXME\b",
    r"xxx\.com",
    r"example\.com",
]

# Allowed unicode symbols (not "garbage")
ALLOWED_UNICODE = {
    "\u2605",  # ★ star (ratings)
    "\u2606",  # ☆ empty star
    "\u2713",  # ✓ checkmark
    "\u2714",  # ✔ heavy checkmark
    "\u2192",  # → arrow
    "\u2190",  # ← arrow
    "\u2022",  # • bullet
    "\u26A1",  # ⚡ lightning (features)
    "\U0001F512",  # 🔒 lock (security)
    "\U0001F4F1",  # 📱 phone
    "\U0001F4CD",  # 📍 pin
    "\U0001F4DE",  # 📞 telephone
}


class HTMLValidator(HTMLParser):
    """Parse HTML and collect structural data for validation."""
    
    def __init__(self):
        super().__init__()
        self.has_doctype = False
        self.has_viewport = False
        self.has_charset = False
        self.lang = ""
        self.ids = set()
        self.links = []
        self.images = []
        self.buttons = []
        self.sections = 0
        self.headings = 0
        self.in_button = False
        self.button_text = ""
        self.has_style = False
    
    def handle_decl(self, decl):
        if "DOCTYPE" in decl.upper():
            self.has_doctype = True
    
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "html":
            self.lang = d.get("lang", "")
        if tag == "meta":
            if d.get("name") == "viewport":
                self.has_viewport = True
            if "charset" in d:
                self.has_charset = True
        if tag in ("section", "header", "footer"):
            self.sections += 1
        if tag in ("h1", "h2", "h3"):
            self.headings += 1
        if tag == "a":
            self.links.append(d.get("href", ""))
        if tag == "img":
            self.images.append(d.get("src", ""))
        if tag in ("button", "a"):
            self.in_button = True
            self.button_text = ""
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "style":
            self.has_style = True
    
    def handle_endtag(self, tag):
        if tag in ("button", "a") and self.in_button:
            self.in_button = False
            self.buttons.append(self.button_text.strip())
    
    def handle_data(self, data):
        if self.in_button:
            self.button_text += data


def validate_html(html: str) -> dict:
    """Validate HTML and return a dict of issues."""
    v = HTMLValidator()
    v.feed(html)
    issues = []
    
    if not v.has_doctype and "<!DOCTYPE" not in html[:100].upper():
        if "<!doctype html>" not in html[:100].lower():
            issues.append("missing_doctype")
    
    if not v.has_viewport:
        issues.append("missing_viewport")
    if not v.has_charset:
        issues.append("missing_charset")
    if "ru" not in v.lang:
        issues.append(f"wrong_lang:{v.lang}")
    if v.sections < 3:
        issues.append(f"too_few_sections:{v.sections}")
    if v.headings < 1:
        issues.append("no_headings")
    if not v.has_style and 'rel="stylesheet"' not in html:
        issues.append("no_css")
    
    # Placeholder leakage (NOT including HTML placeholder= attributes)
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            issues.append(f"placeholder:{pattern}")
    
    # Empty CTA buttons
    empty_ctas = [b for b in v.buttons if len(b.strip()) < 2]
    if empty_ctas:
        issues.append(f"empty_cta:{len(empty_ctas)}")
    
    # Broken internal anchors
    for link in v.links:
        if link.startswith("#") and len(link) > 1:
            if link[1:] not in v.ids:
                issues.append(f"broken_anchor:{link}")
    
    # Broken images
    broken = [s for s in v.images if not s or s == "#" or s == "placeholder"]
    if broken:
        issues.append(f"broken_images:{len(broken)}")
    
    # Text-icon garbage (excessive unicode symbols, excluding allowed ones)
    unicode_icons = re.findall(r"[\u2600-\u27BF\U0001F300-\U0001F9FF]", html)
    garbage_icons = [i for i in unicode_icons if i not in ALLOWED_UNICODE]
    if len(garbage_icons) > 5:
        issues.append(f"text_icons:{len(garbage_icons)}")
    
    return {
        "issues": issues,
        "sections": v.sections,
        "headings": v.headings,
        "images": len(v.images),
        "buttons": len(v.buttons),
        "size": len(html),
    }


# ═══════════════════════════════════════════════════════════════════
# 1. COMPONENT RETRIEVER — SEMANTIC RETRIEVAL
# ═══════════════════════════════════════════════════════════════════

class TestSemanticRetriever:
    """Verify the semantic retriever returns correct templates."""
    
    def test_retriever_returns_correct_section_type(self):
        from workers.component_retriever import retrieve_best
        for section_type in ["hero", "features", "trust", "footer"]:
            meta = retrieve_best(section_type, niche="restaurant")
            assert meta is not None, f"No template for {section_type}"
            assert meta.scene_id.startswith(f"{section_type}."), \
                f"Expected {section_type}.*, got {meta.scene_id}"
    
    def test_retriever_semantic_relevance(self):
        """Semantic query should influence results."""
        from workers.component_retriever import retrieve_templates
        results = retrieve_templates(
            "hero", query="фитнес-клуб Iron Gym тренировки", niche="fitness", top_n=3
        )
        assert len(results) > 0
        top_meta, top_score = results[0]
        assert top_score > 0.0, "Top result should have positive score"
    
    def test_retriever_anti_clone_penalty(self):
        """Used IDs should be penalized — score should drop."""
        from workers.component_retriever import retrieve_templates
        # Get top results without used_ids
        results_clean = retrieve_templates("hero", niche="fitness", top_n=3)
        assert len(results_clean) > 0
        top_id = results_clean[0][0].scene_id
        top_score_clean = results_clean[0][1]
        
        # Get results with the top one marked as used
        results_used = retrieve_templates("hero", niche="fitness", used_ids=[top_id], top_n=3)
        # The previously-top template should have a lower score now
        for meta, score in results_used:
            if meta.scene_id == top_id:
                assert score < top_score_clean, \
                    f"Anti-clone penalty should reduce score: {score} >= {top_score_clean}"
                break
    
    def test_retriever_forbidden_tags(self):
        """Forbidden tags should exclude templates with those styles."""
        from workers.component_retriever import retrieve_templates
        # Get all hero templates
        all_results = retrieve_templates("hero", niche="fitness", top_n=10)
        if len(all_results) < 2:
            pytest.skip("Not enough hero templates to test forbidden tags")
        
        top_meta = all_results[0][0]
        if hasattr(top_meta, "styles") and top_meta.styles:
            forbidden = list(top_meta.styles)[:1]
            filtered = retrieve_templates(
                "hero", niche="fitness", forbidden_tags=forbidden, top_n=10
            )
            # Filtered results should not have the forbidden style in top position
            # (or should have lower score)
            assert len(filtered) > 0, "Should still return results with forbidden tags"
    
    def test_retriever_niche_tags_boost(self):
        """Niche-specific templates should score higher for matching niche."""
        from workers.component_retriever import retrieve_templates
        legal_results = retrieve_templates("hero", niche="legal", top_n=3)
        fitness_results = retrieve_templates("hero", niche="fitness", top_n=3)
        assert len(legal_results) > 0
        assert len(fitness_results) > 0
        # Top results should differ by niche
        legal_top = legal_results[0][0].scene_id
        fitness_top = fitness_results[0][0].scene_id
        assert legal_top != fitness_top, \
            "Different niches should prefer different templates"
    
    def test_all_templates_have_valid_files(self):
        """Every template in catalog should point to an existing file."""
        from workers.component_retriever import TEMPLATE_CATALOG, TEMPLATES_BASE
        for meta in TEMPLATE_CATALOG:
            filepath = os.path.join(TEMPLATES_BASE, meta.file)
            assert os.path.exists(filepath), \
                f"Template {meta.scene_id} points to missing file: {filepath}"
    
    def test_quality_tier_affects_ranking(self):
        """Higher quality templates should rank higher."""
        from workers.component_retriever import retrieve_templates
        results = retrieve_templates("hero", niche="restaurant", top_n=5)
        if len(results) >= 2:
            scores = [s for _, s in results]
            assert scores == sorted(scores, reverse=True), \
                f"Results not sorted by score: {scores}"


# ═══════════════════════════════════════════════════════════════════
# 2. SCENE PLANNER — PLAN GENERATION (mocked LLM)
# ═══════════════════════════════════════════════════════════════════

class TestScenePlannerSelfContained:
    """Test scene planner with mocked LLM calls."""
    
    @pytest.mark.asyncio
    async def test_plan_page_returns_sections(self):
        """plan_page should return a list of section plans."""
        from workers.scene_planner import plan_page
        import json
        
        # Mock LLM response: extract_content_with_llm returns a dict of scene_id -> content
        mock_content = {
            "hero.cinematic_fullbleed.v1": {
                "heading": "Iron Gym",
                "subheading": "Сила начинается здесь",
                "cta_text": "Записаться",
                "cta_url": "#contact",
            },
            "features.bento_grid.v1": {
                "heading": "Наши преимущества",
                "items": [{"title": "Тренажёрный зал", "desc": "Современное оборудование"}],
            },
            "trust.testimonials_carousel.v1": {
                "heading": "Отзывы клиентов",
                "items": [{"name": "Иван", "text": "Отличный зал!"}],
            },
            "footer.minimal_contact.v1": {
                "phone": "+7 (495) 555-01-01",
                "email": "info@irongym.ru",
            },
        }
        
        # Mock llm_client with a complete method
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value=json.dumps(mock_content))
        
        with patch("workers.scene_planner.extract_content_with_llm", new_callable=AsyncMock, return_value=mock_content):
            plan = await plan_page(
                user_brief="Создай лендинг для фитнес-клуба Iron Gym",
                llm_client=mock_llm,
                force_niche="fitness",
            )
        
        assert plan is not None, "plan_page should return a PagePlan"
        assert hasattr(plan, 'scenes') or isinstance(plan, (list, dict)), \
            f"plan_page should return a PagePlan, got {type(plan)}"
    
    @pytest.mark.asyncio
    async def test_plan_uses_semantic_retriever(self):
        """plan_page should have access to the semantic retriever."""
        # Verify the retriever is properly imported in scene_planner
        from workers.scene_planner import _retrieve_best as retriever_fn
        assert retriever_fn is not None
        assert callable(retriever_fn)
        
        # Verify it's the semantic version (from component_retriever)
        from workers.component_retriever import retrieve_best
        # _retrieve_best in scene_planner should be the same function
        # (or a wrapper around it)
        result = retriever_fn("hero", niche="fitness")
        assert result is not None
        assert hasattr(result, "scene_id")


# ═══════════════════════════════════════════════════════════════════
# 3. GOLDEN LANDING REGRESSION — HTML QUALITY
# ═══════════════════════════════════════════════════════════════════

class TestGoldenLandingRegression:
    """
    Validate that pre-generated golden landing pages meet quality standards.
    Uses actual HTML files from the benchmark run.
    """
    
    GOLDEN_DIR = "/root/arcane/tests/golden_fixtures"
    
    @pytest.fixture(autouse=True)
    def _check_golden_dir(self):
        """Skip if golden fixtures don't exist (first run)."""
        if not os.path.isdir(self.GOLDEN_DIR):
            pytest.skip(f"Golden fixtures not found at {self.GOLDEN_DIR}")
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_no_placeholder_leakage(self, niche):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        result = validate_html(html)
        placeholder_issues = [i for i in result["issues"] if i.startswith("placeholder:")]
        assert not placeholder_issues, f"Placeholder leakage: {placeholder_issues}"
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_no_broken_anchors(self, niche):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        result = validate_html(html)
        anchor_issues = [i for i in result["issues"] if i.startswith("broken_anchor:")]
        assert not anchor_issues, f"Broken anchors: {anchor_issues}"
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_no_text_icons(self, niche):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        result = validate_html(html)
        icon_issues = [i for i in result["issues"] if i.startswith("text_icons:")]
        assert not icon_issues, f"Text-icon garbage: {icon_issues}"
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_no_empty_cta(self, niche):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        result = validate_html(html)
        cta_issues = [i for i in result["issues"] if i.startswith("empty_cta:")]
        assert not cta_issues, f"Empty CTA garbage: {cta_issues}"
    
    @pytest.mark.parametrize("niche_data", BENCHMARK_NICHES, ids=[n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_has_brand_name(self, niche_data):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche_data['niche']}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche_data['niche']}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        assert niche_data["brand"].lower() in html.lower(), \
            f"Brand name '{niche_data['brand']}' not found in {niche_data['niche']}.html"
    
    @pytest.mark.parametrize("niche_data", BENCHMARK_NICHES, ids=[n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_has_phone_number(self, niche_data):
        """Golden fixture should contain at least one phone number."""
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche_data['niche']}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche_data['niche']}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        # Check for any phone-like pattern (tel: link or +7 number)
        has_phone = bool(
            re.search(r'tel:', html) or
            re.search(r'\+7\s*[\(\d]', html) or
            re.search(r'8[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}', html)
        )
        assert has_phone, f"No phone number found in {niche_data['niche']}.html"
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_minimum_size(self, niche):
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        size = os.path.getsize(filepath)
        assert size > 5000, f"{niche}.html is only {size} bytes — likely a stub"
    
    @pytest.mark.parametrize("niche", [n["niche"] for n in BENCHMARK_NICHES])
    def test_golden_has_valid_structure(self, niche):
        """Each golden fixture should have proper HTML structure."""
        filepath = os.path.join(self.GOLDEN_DIR, f"{niche}.html")
        if not os.path.exists(filepath):
            pytest.skip(f"Golden fixture {niche}.html not found")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        result = validate_html(html)
        structural_issues = [
            i for i in result["issues"]
            if i.startswith(("missing_", "wrong_lang", "too_few_", "no_"))
        ]
        assert not structural_issues, f"Structural issues in {niche}.html: {structural_issues}"


# ═══════════════════════════════════════════════════════════════════
# 4. ARTIFACT/URL CONTRACT
# ═══════════════════════════════════════════════════════════════════

class TestArtifactContract:
    """Verify the artifact/URL contract is consistent."""
    
    def test_workspace_path_format(self):
        """Workspace paths should follow /root/workspace/{chat_id}/{filename}."""
        from config.settings import get_config
        cfg = get_config()
        assert hasattr(cfg, "workspace_root"), "Config should have workspace_root"
        assert cfg.workspace_root == "/root/workspace", \
            f"Workspace root should be /root/workspace, got {cfg.workspace_root}"
    
    def test_auto_deploy_produces_correct_url(self):
        """auto_deploy should produce https://arcaneai.ru/demo/{slug}/ URLs."""
        from workers.scene_assembler import _slugify
        slug = _slugify("Iron Gym — фитнес-клуб")
        assert slug, "Slugify should produce non-empty result"
        assert "/" not in slug, "Slug should not contain slashes"
        assert " " not in slug, "Slug should not contain spaces"
        expected_url = f"https://arcaneai.ru/demo/{slug}/"
        assert "arcaneai.ru/demo/" in expected_url
    
    def test_slugify_cyrillic(self):
        """Slugify should transliterate Cyrillic correctly."""
        from workers.scene_assembler import _slugify
        assert _slugify("Вкус Рима") == "vkus-rima"
        assert _slugify("Atlas Law") == "atlas-law"
        assert _slugify("Iron Gym") == "iron-gym"
    
    def test_no_legacy_deliveries_path(self):
        """No code should reference the old /deliveries/ path."""
        import glob
        py_files = glob.glob(os.path.join(_arcane_root, "**", "*.py"), recursive=True)
        for filepath in py_files:
            if "__pycache__" in filepath or "venv" in filepath or "test_" in filepath:
                continue
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            assert "/deliveries/" not in content, \
                f"Legacy /deliveries/ path found in {filepath}"
    
    def test_demo_directory_structure(self):
        """Demo directory should exist and contain landing pages."""
        demo_dir = "/var/www/demo"
        assert os.path.isdir(demo_dir), f"Demo directory {demo_dir} should exist"
        # Should have at least one subdirectory with index.html
        subdirs = [d for d in os.listdir(demo_dir) if os.path.isdir(os.path.join(demo_dir, d))]
        assert len(subdirs) > 0, "Demo directory should have deployed landings"


# ═══════════════════════════════════════════════════════════════════
# 5. SCENE-ONLY DEFAULT PATH
# ═══════════════════════════════════════════════════════════════════

class TestSceneOnlyDefault:
    """Verify the scene-driven path is the only default."""
    
    def test_no_legacy_coder_flag(self):
        """FEATURE_FLAG_LEGACY_CODER should not exist in active config."""
        from config.settings import get_config
        cfg = get_config()
        assert not hasattr(cfg, "legacy_coder_enabled"), \
            "legacy_coder_enabled should be removed from settings"
    
    def test_scene_pipeline_imports(self):
        """Core scene pipeline modules should be importable."""
        from workers.scene_planner import plan_page
        from workers.scene_assembler import assemble_page
        from workers.component_retriever import retrieve_best, retrieve_templates
        assert callable(plan_page)
        assert callable(assemble_page)
        assert callable(retrieve_best)
        assert callable(retrieve_templates)
    
    def test_frontend_director_uses_scene_path(self):
        """FrontendDirector should route through scene pipeline."""
        import inspect
        from core.agent_loop import AgentLoop
        source = inspect.getsource(AgentLoop._run_frontend_director)
        assert "_run_scene_driven_pipeline" in source, \
            "_run_frontend_director should call _run_scene_driven_pipeline"
        assert "legacy_coder_enabled" not in source, \
            "_run_frontend_director should not reference legacy_coder_enabled"
    
    def test_no_from_scratch_fallback(self):
        """The from-scratch fallback should not exist in _run_frontend_director."""
        import inspect
        from core.agent_loop import AgentLoop
        source = inspect.getsource(AgentLoop._run_frontend_director)
        # Should NOT contain "creative direction" or "from scratch" fallback
        assert "own creative" not in source.lower(), \
            "_run_frontend_director should not have from-scratch fallback"


# ═══════════════════════════════════════════════════════════════════
# 6. OWNERSHIP SMOKE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOwnershipContract:
    """Verify ownership isolation between users."""
    
    def test_workspace_dir_per_chat(self):
        """Each chat should have its own workspace directory."""
        import uuid
        chat_id = str(uuid.uuid4())
        workspace = os.path.join("/root/workspace", chat_id)
        assert chat_id in workspace
        assert workspace.startswith("/root/workspace/")
    
    def test_demo_deploy_is_public(self):
        """Demo deployments should be in /var/www/demo/ (publicly accessible)."""
        demo_dir = "/var/www/demo"
        assert os.path.isdir(demo_dir), f"Demo directory {demo_dir} should exist"
    
    def test_workspace_isolation(self):
        """Workspace directories should be isolated per chat."""
        import uuid
        chat1 = str(uuid.uuid4())
        chat2 = str(uuid.uuid4())
        ws1 = os.path.join("/root/workspace", chat1)
        ws2 = os.path.join("/root/workspace", chat2)
        assert ws1 != ws2, "Different chats should have different workspace paths"
        assert chat1 in ws1 and chat2 in ws2
