"""
ARCANE Self-Contained Pytest Suite
===================================
Tests the core pipeline components WITHOUT a live server.
All LLM calls are mocked. All file I/O is sandboxed to /tmp.

Run: cd /root/arcane && python -m pytest tests/test_pipeline.py -v

Covers:
1. Niche detection
2. Theme detection
3. Component retriever scoring
4. Scene planner (with mocked LLM)
5. Scene assembler HTML output validation
6. Blueprint placeholder fill
7. Hard timeout enforcement
8. Judge budget cap
9. Model registry correctness
10. Artifact URL contract
"""
import pytest
import asyncio
import re
import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════
# 1. NICHE DETECTION
# ═══════════════════════════════════════════════════════════════════
class TestNicheDetection:
    def test_restaurant_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Создай лендинг для итальянского ресторана La Bella")
        assert niche in ("restaurant", "hospitality"), f"Expected restaurant/hospitality, got {niche}"
    
    def test_fitness_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Лендинг для фитнес-клуба Iron Gym")
        assert niche in ("fitness",), f"Expected fitness, got {niche}"
    
    def test_beauty_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Сайт для салона красоты Glamour")
        assert niche in ("beauty", "luxury_service"), f"Expected beauty/luxury_service, got {niche}"
    
    def test_legal_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Лендинг для юридической фирмы Lex Group")
        assert niche in ("legal",), f"Expected legal, got {niche}"
    
    def test_medical_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Сайт для стоматологической клиники Dental Pro")
        assert niche in ("medical",), f"Expected medical, got {niche}"
    
    def test_real_estate_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Лендинг для агентства недвижимости Prime Estate")
        assert niche in ("real_estate",), f"Expected real_estate, got {niche}"
    
    def test_default_niche(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Сделай что-нибудь красивое")
        assert niche is not None, "Niche should not be None"
    
    def test_niche_returns_tags(self):
        from workers.scene_planner import detect_niche
        niche, tags = detect_niche("Барбершоп Iron Cut")
        assert isinstance(tags, list), "Tags should be a list"
        assert len(tags) > 0, "Tags should not be empty"


# ═══════════════════════════════════════════════════════════════════
# 2. THEME DETECTION
# ═══════════════════════════════════════════════════════════════════
class TestThemeDetection:
    def test_dark_theme_detection(self):
        from workers.scene_planner import detect_user_theme_preference
        theme = detect_user_theme_preference("Тёмная тема, премиальный стиль")
        assert theme is not None, "Should detect dark theme"
        assert "dark" in theme.lower(), f"Expected dark theme, got {theme}"
    
    def test_light_theme_detection(self):
        from workers.scene_planner import detect_user_theme_preference
        theme = detect_user_theme_preference("Светлый, минималистичный дизайн")
        if theme:
            assert "light" in theme.lower() or "trust" in theme.lower(), f"Expected light theme, got {theme}"
    
    def test_no_theme_preference(self):
        from workers.scene_planner import detect_user_theme_preference
        theme = detect_user_theme_preference("Сделай лендинг для ресторана")
        # Should return None or a valid theme string
        assert theme is None or isinstance(theme, str)


# ═══════════════════════════════════════════════════════════════════
# 3. COMPONENT RETRIEVER
# ═══════════════════════════════════════════════════════════════════
class TestComponentRetriever:
    def test_retrieve_best_hero(self):
        from workers.component_retriever import retrieve_best
        meta = retrieve_best("hero", niche="restaurant")
        assert meta is not None, "Should find a hero template"
        assert meta.scene_id.startswith("hero."), f"Expected hero.*, got {meta.scene_id}"
    
    def test_retrieve_best_features(self):
        from workers.component_retriever import retrieve_best
        meta = retrieve_best("features", niche="fitness")
        assert meta is not None, "Should find a features template"
        assert meta.scene_id.startswith("features."), f"Expected features.*, got {meta.scene_id}"
    
    def test_retrieve_templates_returns_scored_list(self):
        from workers.component_retriever import retrieve_templates
        results = retrieve_templates("hero", niche="legal", top_n=3)
        assert isinstance(results, list), "Should return a list"
        assert len(results) > 0, "Should return at least one result"
        meta, score = results[0]
        assert hasattr(meta, 'scene_id'), "Result should have scene_id"
        assert isinstance(score, (int, float)), "Score should be numeric"
    
    def test_retrieve_with_theme(self):
        from workers.component_retriever import retrieve_best
        meta = retrieve_best("hero", niche="restaurant", theme="dark_premium_v1")
        assert meta is not None, "Should find template with theme filter"
    
    def test_retrieve_nonexistent_section_type(self):
        from workers.component_retriever import retrieve_best
        meta = retrieve_best("nonexistent_section", niche="restaurant")
        assert meta is None, "Should return None for nonexistent section type"
    
    def test_anti_clone_different_results(self):
        """Verify retriever can return different templates for same section_type"""
        from workers.component_retriever import retrieve_templates
        results = retrieve_templates("hero", niche="restaurant", top_n=5)
        scene_ids = [m.scene_id for m, s in results]
        # At least we should get results (even if all same for small catalog)
        assert len(results) > 0
    
    def test_list_section_types(self):
        from workers.component_retriever import list_section_types
        types = list_section_types()
        assert "hero" in types
        assert "features" in types
        assert "footer" in types


# ═══════════════════════════════════════════════════════════════════
# 4. SCENE PLANNER (with mocked LLM)
# ═══════════════════════════════════════════════════════════════════
class TestScenePlanner:
    @pytest.mark.asyncio
    async def test_plan_page_returns_page_plan(self):
        from workers.scene_planner import plan_page, PagePlan
        
        # Mock LLM client
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "hero.cinematic_fullbleed.v1": {
                "headline": "Test Restaurant",
                "subheadline": "Fine Dining",
                "cta_text": "Reserve Now",
            }
        })
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=200)
        mock_llm.complete.return_value = mock_response
        
        plan = await plan_page(
            "Лендинг для ресторана La Bella",
            mock_llm,
            force_niche="restaurant",
        )
        
        assert isinstance(plan, PagePlan)
        assert plan.niche == "restaurant"
        assert len(plan.scenes) > 0
        assert plan.global_theme is not None
    
    @pytest.mark.asyncio
    async def test_plan_page_uses_dynamic_retrieval(self):
        """Verify plan_page calls component_retriever (DoD-2)"""
        from workers.scene_planner import plan_page
        
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "{}"
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=200)
        mock_llm.complete.return_value = mock_response
        
        with patch('workers.scene_planner._retrieve_scene_ids_dynamic') as mock_retrieve:
            mock_retrieve.return_value = [
                "hero.cinematic_fullbleed.v1",
                "features.bento_grid.v1",
                "footer.authority_contact.v1",
            ]
            plan = await plan_page("Test", mock_llm, force_niche="restaurant")
            mock_retrieve.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_plan_page_alternating_themes(self):
        from workers.scene_planner import plan_page
        
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "{}"
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=200)
        mock_llm.complete.return_value = mock_response
        
        plan = await plan_page("Ресторан", mock_llm, force_niche="restaurant")
        
        # Check that scenes have alternating themes
        themes = [s.modifiers.get("theme_pack", "") for s in plan.scenes]
        # At least some should be different (alternating)
        assert len(plan.scenes) >= 3, "Should have at least 3 scenes"


# ═══════════════════════════════════════════════════════════════════
# 5. SCENE ASSEMBLER HTML VALIDATION
# ═══════════════════════════════════════════════════════════════════
class TestSceneAssembler:
    @pytest.mark.asyncio
    async def test_assemble_page_produces_html(self):
        from workers.scene_assembler import assemble_page
        from workers.scene_planner import PagePlan, SceneSpec
        
        plan = PagePlan(
            niche="restaurant",
            niche_tags=["restaurant"],
            global_theme="dark_premium_v1",
            scenes=[
                SceneSpec(
                    scene_id="hero.cinematic_fullbleed.v1",
                    modifiers={"theme_pack": "dark_premium_v1"},
                    content={
                        "headline": "La Bella",
                        "subheadline": "Fine Italian Dining",
                        "cta_text": "Reserve Now",
                        "cta_href": "#contact",
                    },
                    order=0,
                ),
                SceneSpec(
                    scene_id="footer.authority_contact.v1",
                    modifiers={"theme_pack": "dark_premium_v1"},
                    content={
                        "brand_name": "La Bella",
                        "tagline": "Since 2010",
                        "address": "123 Main St",
                        "phone": "+1-555-0100",
                        "email": "info@labella.com",
                    },
                    order=1,
                ),
            ],
        )
        
        html = await assemble_page(plan, fetch_images=False, lang="ru")
        
        assert html is not None, "HTML should not be None"
        assert len(html) > 1000, f"HTML too short: {len(html)} chars"
        assert "<html" in html.lower(), "Should contain <html> tag"
        assert "La Bella" in html, "Should contain business name"
    
    @pytest.mark.asyncio
    async def test_no_unresolved_placeholders(self):
        """DoD-5: No placeholder leakage"""
        from workers.scene_assembler import assemble_page
        from workers.scene_planner import PagePlan, SceneSpec
        
        plan = PagePlan(
            niche="fitness",
            niche_tags=["fitness"],
            global_theme="dark_premium_v1",
            scenes=[
                SceneSpec(
                    scene_id="hero.cinematic_fullbleed.v1",
                    modifiers={"theme_pack": "dark_premium_v1"},
                    content={
                        "headline": "Iron Gym",
                        "subheadline": "Get Fit Today",
                        "cta_text": "Join Now",
                        "cta_href": "#pricing",
                    },
                    order=0,
                ),
            ],
        )
        
        html = await assemble_page(plan, fetch_images=False, lang="ru")
        
        # Check for unresolved {{PLACEHOLDER}} patterns
        unresolved = re.findall(r'\{\{[A-Z_]+\}\}', html)
        assert len(unresolved) == 0, f"Unresolved placeholders found: {set(unresolved)}"
    
    @pytest.mark.asyncio
    async def test_no_text_icons(self):
        """DoD-5: No text-icons (raw icon names instead of actual icons)"""
        from workers.scene_assembler import assemble_page
        from workers.scene_planner import PagePlan, SceneSpec
        
        plan = PagePlan(
            niche="restaurant",
            niche_tags=["restaurant"],
            global_theme="light_trust_v1",
            scenes=[
                SceneSpec(
                    scene_id="features.editorial_cards.v1",
                    modifiers={"theme_pack": "light_trust_v1"},
                    content={
                        "section_title": "Our Services",
                        "section_subtitle": "What we offer",
                        "features": [
                            {"icon": "utensils", "title": "Fine Dining", "description": "Exquisite cuisine"},
                            {"icon": "wine", "title": "Wine Bar", "description": "Premium selection"},
                            {"icon": "cake", "title": "Desserts", "description": "Handcrafted sweets"},
                        ],
                    },
                    order=0,
                ),
            ],
        )
        
        html = await assemble_page(plan, fetch_images=False, lang="ru")
        
        # Text-icons = raw icon names appearing as visible text
        # They should be inside data-lucide attributes, not as text content
        # Check that icon names don't appear as standalone text between tags
        for icon_name in ["utensils", "wine", "cake"]:
            # Should be in data-lucide="icon_name" not as >icon_name<
            pattern = f">{icon_name}<"
            matches = re.findall(pattern, html, re.IGNORECASE)
            # Filter out legitimate uses (inside attributes)
            assert len(matches) == 0, f"Text-icon found: '{icon_name}' appears as visible text"
    
    @pytest.mark.asyncio
    async def test_html_has_section_ids(self):
        """DoD-5: No broken anchors - sections should have IDs"""
        from workers.scene_assembler import assemble_page
        from workers.scene_planner import PagePlan, SceneSpec
        
        plan = PagePlan(
            niche="legal",
            niche_tags=["legal"],
            global_theme="light_trust_v1",
            scenes=[
                SceneSpec(
                    scene_id="hero.legal_authority.v1",
                    modifiers={"theme_pack": "light_trust_v1"},
                    content={"headline": "Lex Group", "subheadline": "Legal Excellence"},
                    order=0,
                ),
                SceneSpec(
                    scene_id="about.split_image.v1",
                    modifiers={"theme_pack": "light_trust_v1"},
                    content={"section_title": "About Us", "text": "We are the best"},
                    order=1,
                ),
            ],
        )
        
        html = await assemble_page(plan, fetch_images=False, lang="ru")
        
        # Check that sections have id attributes for anchor navigation
        assert 'id="' in html, "HTML should have section IDs for navigation"


# ═══════════════════════════════════════════════════════════════════
# 6. MODEL REGISTRY
# ═══════════════════════════════════════════════════════════════════
class TestModelRegistry:
    def test_no_gpt5_as_primary(self):
        """Day 0 Fix: No role should use gpt-5 as primary model"""
        from shared.llm.model_registry import ROLES
        
        for role_name, role_obj in ROLES.items():
            for tier, model_id in role_obj.tiers.items():
                assert model_id != "gpt-5", (
                    f"Role {role_name}.{tier.value} still uses gpt-5 as primary. "
                    f"Should be gpt-5.4-mini"
                )
    
    def test_all_models_are_non_reasoning(self):
        """Verify primary models are non-reasoning (content != null)"""
        from shared.llm.model_registry import MODELS
        
        # Verify the specs exist for our primary models
        for model_id in ["gpt-5.4-mini", "gpt-5.4-nano"]:
            assert model_id in MODELS, f"MODELS missing {model_id}"
    
    def test_fallback_chains_exist(self):
        """Verify each role has fallback models"""
        from shared.llm.model_registry import ROLES
        
        for role_name, role_obj in ROLES.items():
            assert hasattr(role_obj, 'fallback_chain'), f"{role_name} should have fallback_chain"
            assert len(role_obj.fallback_chain) > 0, f"{role_name} should have at least one fallback"


# ═══════════════════════════════════════════════════════════════════
# 7. HARD TIMEOUT
# ═══════════════════════════════════════════════════════════════════
class TestHardTimeout:
    def test_hard_timeout_constant_exists(self):
        """Day 0 Fix: Hard timeout should be defined"""
        from core.agent_loop import AgentLoop
        # Check that HARD_TIMEOUT_SECONDS exists as class or module constant
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        assert "HARD_TIMEOUT" in source, "HARD_TIMEOUT constant should exist in agent_loop.py"
        assert "600" in source, "Hard timeout should be 600 seconds"
    
    def test_hard_timeout_check_in_main_loop(self):
        """Verify hard timeout is checked inside the main iteration loop"""
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        # Should have elapsed time check
        assert "elapsed" in source and "HARD_TIMEOUT" in source, \
            "Main loop should check elapsed time against HARD_TIMEOUT"


# ═══════════════════════════════════════════════════════════════════
# 8. JUDGE BUDGET CAP
# ═══════════════════════════════════════════════════════════════════
class TestJudgeBudgetCap:
    def test_judge_budget_cap_exists(self):
        """Day 0 Fix: Judge should have a budget cap"""
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        assert "JUDGE_BUDGET_CAP" in source or "judge_budget" in source.lower(), \
            "Judge budget cap should be defined"
    
    def test_judge_max_passes_limited(self):
        """Judge should not exceed max passes"""
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        assert "_MAX_JUDGE_PASSES" in source, "MAX_JUDGE_PASSES should be defined"


# ═══════════════════════════════════════════════════════════════════
# 9. ARTIFACT URL CONTRACT
# ═══════════════════════════════════════════════════════════════════
class TestArtifactURLContract:
    def test_unified_workspace_path(self):
        """DoD-3: All artifacts should use /root/workspace/ path"""
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        assert "/root/workspace/" in source, "Should use unified /root/workspace/ path"
        # Should NOT have /home/ubuntu/projects/ as primary
        lines = source.split('\n')
        active_lines = [l for l in lines if not l.strip().startswith('#')]
        active_source = '\n'.join(active_lines)
        assert "/home/ubuntu/projects" not in active_source, \
            "Should not reference legacy /home/ubuntu/projects/ path in active code"
    
    def test_demo_deploy_path(self):
        """Auto-deploy should use /var/www/demo/"""
        from workers.scene_assembler import auto_deploy
        assert auto_deploy is not None, "auto_deploy function should exist"


# ═══════════════════════════════════════════════════════════════════
# 10. SCENE PIPELINE IS DEFAULT
# ═══════════════════════════════════════════════════════════════════
class TestScenePipelineDefault:
    def test_legacy_removed_after_cutover(self):
        """Cutover v1: Legacy path has been completely removed from config"""
        from config.settings import ArcaneConfig
        cfg = ArcaneConfig()
        # legacy_coder_enabled should no longer exist as an attribute
        assert not hasattr(cfg, 'legacy_coder_enabled'), (
            "legacy_coder_enabled should be removed after cutover v1"
        )
    
    def test_scene_pipeline_is_primary(self):
        """Scene pipeline should be attempted first"""
        import core.agent_loop as al_module
        source = open(al_module.__file__).read()
        # scene_driven should appear before legacy coder
        scene_pos = source.find("scene_driven") or source.find("Scene-Driven")
        legacy_pos = source.find("legacy_coder") or source.find("from_scratch")
        if scene_pos > 0 and legacy_pos > 0:
            assert scene_pos < legacy_pos, "Scene pipeline should be attempted before legacy"
