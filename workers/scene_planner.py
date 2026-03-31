"""
ARCANE Premium Scenes — Scene Planner
workers/scene_planner.py

Принимает user_brief + niche_tags, возвращает ordered list SceneSpec.
Использует LLM для интерпретации запроса и выбора сцен из COMPATIBILITY_MATRIX.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
#  SCENE SPEC
# ─────────────────────────────────────────────────────────────────

@dataclass
class SceneSpec:
    """One section of the final landing page."""
    scene_id: str
    modifiers: dict[str, str] = field(default_factory=dict)
    content: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "modifiers": self.modifiers,
            "content": self.content,
            "order": self.order,
        }


@dataclass
class PagePlan:
    """Complete page plan: ordered list of scenes + global metadata."""
    niche: str
    niche_tags: list[str]
    global_theme: str
    scenes: list[SceneSpec] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "niche": self.niche,
            "niche_tags": self.niche_tags,
            "global_theme": self.global_theme,
            "scenes": [s.to_dict() for s in self.scenes],
            "meta": self.meta,
        }


# ─────────────────────────────────────────────────────────────────
#  NICHE DETECTION
# ─────────────────────────────────────────────────────────────────

NICHE_KEYWORDS: dict[str, list[str]] = {
    "restaurant": ["ресторан", "кафе", "кофейн", "бар", "пиццери", "суши", "доставка еды", "restaurant", "cafe", "coffee"],
    "fitness": ["фитнес", "спортзал", "тренажёрн", "йога", "пилатес", "тренер", "gym", "fitness", "workout"],
    "beauty": ["барбершоп", "парикмахер", "салон красот", "салон", "маникюр", "спа", "косметолог", "красот", "barbershop", "beauty", "salon", "spa"],
    "real_estate": ["недвижимост", "риелтор", "квартир", "ипотек", "real estate", "realtor", "агентство недвижимост"],
    "legal": ["юрист", "адвокат", "юридическ", "нотариус", "правов", "lawyer", "attorney", "legal", "law firm"],
    "medical": ["клиник", "врач", "медицин", "стоматолог", "здоровь", "clinic", "doctor", "medical"],
    "saas": ["saas", "software", "платформ", "приложени", "app", "dashboard", "crm", "it", "IT", "разработк", "digital", "веб-", "агентство разработк", "студия разработк", "tech", "технологи", "программирован", "devops", "автоматизац", "ai-платформ", "ai платформ", "искусственн"],
    "finance": ["финанс", "инвестиц", "банк", "страхован", "бухгалтер", "finance", "investment", "accounting"],
    "education": ["обучени", "курс", "школ", "университет", "онлайн-курс", "education", "course", "training"],
    "hospitality": ["отель", "гостиниц", "апартамент", "аренда жиль", "hotel", "accommodation"],
    "luxury_service": ["премиум", "люкс", "vip", "элитный", "premium", "luxury"],
}

# ─────────────────────────────────────────────────────────────────
#  THEME MAPPING — DEFAULT: LIGHT (most professional and universal)
# ─────────────────────────────────────────────────────────────────

NICHE_TO_THEME: dict[str, str] = {
    "restaurant": "warm_editorial_v1",
    "fitness": "dark_premium_v1",
    "beauty": "warm_gold_v1",            # CHANGED: warm gold for beauty/barbershop niches
    "real_estate": "light_trust_v1",
    "legal": "light_trust_v1",
    "medical": "light_trust_v1",
    "saas": "light_trust_v1",           # CHANGED: was dark_tech_v1 — light is more professional
    "finance": "light_trust_v1",         # CHANGED: was neutral_minimal_v1 — light is safer
    "education": "light_trust_v1",
    "hospitality": "warm_gold_v1",       # CHANGED: warm gold for hospitality
    "luxury_service": "dark_elegant_v1", # CHANGED: dark elegant for luxury
    "default": "light_trust_v1",
}

# ─────────────────────────────────────────────────────────────────
#  ALTERNATING THEME PAIRS — for WOW contrast between sections
#  Each pair: (primary_theme, contrast_theme)
#  Sections alternate between primary and contrast themes
# ─────────────────────────────────────────────────────────────────
ALTERNATING_THEME_PAIRS: dict[str, tuple[str, str]] = {
    "light_trust_v1": ("light_trust_v1", "dark_premium_v1"),
    "dark_premium_v1": ("dark_premium_v1", "light_trust_v1"),
    "warm_editorial_v1": ("warm_editorial_v1", "dark_premium_v1"),
    "warm_gold_v1": ("warm_gold_v1", "dark_elegant_v1"),
    "dark_elegant_v1": ("dark_elegant_v1", "warm_gold_v1"),
    "neutral_minimal_v1": ("neutral_minimal_v1", "dark_premium_v1"),
    "dark_tech_v1": ("dark_tech_v1", "light_trust_v1"),
}

# Scenes that should ALWAYS use the dark/contrast variant (hero, CTA, footer)
FORCE_DARK_SCENES: set[str] = {
    "hero.cinematic_fullbleed.v1",
    "cta.executive_split.v1",
    "footer.authority_contact.v1",
    "parallax.quote.v1",
}

# Scenes that should ALWAYS use the light/primary variant
FORCE_LIGHT_SCENES: set[str] = {
    "proof.stats_bar.v1",
    "testimonials.quote_wall.v1",
}

# Default scene sequences per niche
NICHE_SCENE_TEMPLATES: dict[str, list[str]] = {
    "restaurant": [
        "hero.cinematic_fullbleed.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.editorial_cards.v1",
        "parallax.quote.v1",
        "gallery.masonry_grid.v1",
        "testimonials.quote_wall.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "fitness": [
        "hero.cinematic_fullbleed.v1",
        "proof.stats_bar.v1",
        "features.bento_premium.v1",
        "parallax.quote.v1",
        "about.split_image.v1",
        "trust.comparison_block.v1",
        "gallery.masonry_grid.v1",
        "testimonials.quote_wall.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "beauty": [
        "hero.cinematic_fullbleed.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.editorial_cards.v1",
        "parallax.quote.v1",
        "gallery.masonry_grid.v1",
        "testimonials.marquee.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "real_estate": [
        "hero.editorial_split.v1",
        "trust.authority_facts_rail.v1",
        "about.split_image.v1",
        "features.process_timeline.v1",
        "parallax.quote.v1",
        "gallery.masonry_grid.v1",
        "trust.case_grid.v1",
        "testimonials.quote_wall.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "legal": [
        "hero.legal_authority.v1",
        "trust.authority_facts_rail.v1",
        "about.split_image.v1",
        "features.process_timeline.v1",
        "trust.comparison_block.v1",
        "testimonials.quote_wall.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "medical": [
        "hero.legal_authority.v1",
        "trust.authority_facts_rail.v1",
        "about.split_image.v1",
        "features.editorial_cards.v1",
        "trust.case_grid.v1",
        "testimonials.quote_wall.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "saas": [
        "hero.product_showcase.v1",
        "proof.stats_bar.v1",
        "features.bento_premium.v1",
        "parallax.quote.v1",
        "about.split_image.v1",
        "trust.comparison_block.v1",
        "testimonials.marquee.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "finance": [
        "hero.legal_authority.v1",
        "trust.authority_facts_rail.v1",
        "about.split_image.v1",
        "features.process_timeline.v1",
        "trust.case_grid.v1",
        "testimonials.quote_wall.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "education": [
        "hero.editorial_split.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.editorial_cards.v1",
        "parallax.quote.v1",
        "testimonials.quote_wall.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "hospitality": [
        "hero.cinematic_fullbleed.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.editorial_cards.v1",
        "parallax.quote.v1",
        "gallery.masonry_grid.v1",
        "testimonials.marquee.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "luxury_service": [
        "hero.cinematic_fullbleed.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.bento_premium.v1",
        "parallax.quote.v1",
        "gallery.masonry_grid.v1",
        "testimonials.marquee.v1",
        "pricing.cards.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
    "default": [
        "hero.editorial_split.v1",
        "proof.stats_bar.v1",
        "about.split_image.v1",
        "features.bento_premium.v1",
        "parallax.quote.v1",
        "trust.authority_facts_rail.v1",
        "testimonials.quote_wall.v1",
        "cta.executive_split.v1",
        "footer.authority_contact.v1",
    ],
}


def _kw_match(keyword: str, text: str) -> bool:
    """
    Match keyword in text using word boundaries.
    For short keywords (<=3 chars) require word boundary to avoid false positives.
    For longer keywords use simple substring match.
    """
    if len(keyword) <= 3:
        pattern = r"(?<![а-яёa-z])" + re.escape(keyword) + r"(?![а-яёa-z])"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return keyword in text


def detect_niche(user_brief: str) -> tuple[str, list[str]]:
    """Detect niche from user brief text. Returns (niche_name, niche_tags)."""
    brief_lower = user_brief.lower()
    scores: dict[str, int] = {}
    for niche, keywords in NICHE_KEYWORDS.items():
        score = sum(1 for kw in keywords if _kw_match(kw, brief_lower))
        if score > 0:
            scores[niche] = score
    if not scores:
        return "default", []
    best_niche = max(scores, key=lambda n: scores[n])
    tags = [n for n, s in scores.items() if s > 0]
    return best_niche, tags


# ─────────────────────────────────────────────────────────────────
#  USER PREFERENCE DETECTION
# ─────────────────────────────────────────────────────────────────

# Keywords that indicate user wants a LIGHT theme
LIGHT_THEME_KEYWORDS = [
    "светл", "белый", "белая", "белое", "белые", "white",
    "light", "чистый", "чистая", "минималист", "minimal",
    "нежн", "мягк", "воздушн", "лёгк", "легк",
    "пастельн", "свеж", "яркий", "яркая",
]

# Keywords that indicate user wants a DARK theme
DARK_THEME_KEYWORDS = [
    "тёмн", "темн", "чёрн", "черн", "dark", "black",
    "ночн", "night", "неон", "neon", "кибер", "cyber",
]

# Keywords that indicate user wants a WARM theme
WARM_THEME_KEYWORDS = [
    "тёпл", "тепл", "warm", "уютн", "cozy",
    "золот", "бежев", "кремов", "карамел",
]


def detect_user_theme_preference(user_brief: str) -> str | None:
    """
    Detect explicit theme preference from user brief.
    Returns theme name or None if no preference detected.
    User preference ALWAYS overrides niche default.
    """
    brief_lower = user_brief.lower()

    light_score = sum(1 for kw in LIGHT_THEME_KEYWORDS if kw in brief_lower)
    dark_score = sum(1 for kw in DARK_THEME_KEYWORDS if kw in brief_lower)
    warm_score = sum(1 for kw in WARM_THEME_KEYWORDS if kw in brief_lower)

    if light_score == 0 and dark_score == 0 and warm_score == 0:
        return None

    best = max(
        [("light_trust_v1", light_score),
         ("dark_premium_v1", dark_score),
         ("warm_editorial_v1", warm_score)],
        key=lambda x: x[1],
    )

    if best[1] > 0:
        logger.info(f"User theme preference detected: {best[0]} (score={best[1]})")
        return best[0]

    return None


# ─────────────────────────────────────────────────────────────────
#  CONTENT EXTRACTION VIA LLM
# ─────────────────────────────────────────────────────────────────

CONTENT_EXTRACTION_PROMPT = """You are a premium landing page content writer for ARCANE.

Given a user brief, generate high-quality marketing content for each scene.
Return a JSON object where keys are scene_ids and values are content objects.

User brief: {user_brief}
Niche: {niche}
Scene IDs to fill: {scene_ids}

For each scene, generate the following content:

hero scenes:
  - headline: powerful, short (5-8 words), emotional headline
  - subheadline: 1-2 sentences expanding on the headline
  - cta_primary_text: action button text (e.g. "Начать бесплатно", "Получить консультацию")
  - cta_primary_href: "#contact"
  - hero_media_url: Pexels search query for hero image (e.g. "modern office technology team")
  - kicker: short badge text above headline (e.g. "AI-платформа нового поколения")

features scenes (features.bento_premium, features.editorial_cards, features.process_timeline):
  - headline: section title (e.g. "Наши возможности")
  - subheadline: 1 sentence description
  - features: array of EXACTLY 4-6 objects, each with:
    - title: feature name (2-4 words)
    - description: 1-2 sentences about the feature
    - icon: Lucide icon name (use ONLY: code, palette, bar-chart-3, zap, shield, globe, layers, cpu, rocket, target, users, clock, check-circle, star, heart, trending-up, settings, database, lock, sparkles)

trust.authority_facts_rail:
  - facts: array of 4 objects with {{value: "500+", label: "Проектов"}}

trust.case_grid:
  - cases: array of 3 objects with {{title, description, result}}

trust.comparison_block:
  - headline: "Почему мы лучше"
  - before_items: array of 3-4 strings (problems without the product)
  - after_items: array of 3-4 strings (benefits with the product)

proof.stats_bar:
  - stats: array of 4 objects with {{value: "500+", label: "Проектов"}}

testimonials scenes:
  - testimonials: array of 3 objects with {{quote: "Full testimonial text 2-3 sentences", author: "Full Name", role: "Position, Company"}}

cta scenes:
  - headline: compelling call to action headline
  - subheadline: 1-2 sentences urgency/benefit
  - cta_primary_text: button text
  - cta_primary_href: "#contact"

footer:
  - brand_name: company/product name
  - tagline: short company description (1 sentence)
  - phone: "+7 (XXX) XXX-XX-XX" (generate realistic)
  - email: "info@domain.com" (generate realistic)
  - address: realistic Russian city address
  - social_links: [{{"platform": "Telegram", "url": "#"}}, {{"platform": "VK", "url": "#"}}]

CRITICAL RULES:
1. Write in the SAME LANGUAGE as the user brief (Russian if Russian, English if English)
2. Make ALL content specific to the business described — NO generic placeholder text
3. hero_media_url MUST be a Pexels search query (2-4 words), NOT a URL
4. Every features array MUST have exactly 4-6 items with real content
5. Every testimonials array MUST have exactly 3 items with realistic quotes
6. Every stats/facts array MUST have exactly 4 items with realistic numbers
7. Icon names MUST be from the whitelist above — do NOT invent icons
8. Return ONLY valid JSON, no markdown code blocks, no comments

Return format:
{{
  "scene_id_1": {{content_object}},
  "scene_id_2": {{content_object}},
  ...
}}"""


async def extract_content_with_llm(
    llm_client: Any,
    user_brief: str,
    niche: str,
    scene_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Use LLM to extract content for each scene."""
    try:
        from shared.models.schemas import LLMRequest
        prompt = CONTENT_EXTRACTION_PROMPT.format(
            user_brief=user_brief,
            niche=niche,
            scene_ids=json.dumps(scene_ids, ensure_ascii=False),
        )
        req = LLMRequest(
            model_id="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=4000,
        )
        resp = await llm_client.complete(req, role="planner", worker="scene_planner")
        content_raw = (resp.content or "").strip()
        # Strip markdown code blocks if present
        if "```" in content_raw:
            parts = content_raw.split("```")
            if len(parts) >= 3:
                content_raw = parts[1]
            else:
                content_raw = parts[1] if len(parts) > 1 else content_raw
            if content_raw.startswith("json"):
                content_raw = content_raw[4:]
            content_raw = content_raw.strip()

        result = json.loads(content_raw)

        # Post-process: validate and fix common issues
        result = _validate_content_map(result, scene_ids, niche, user_brief)

        return result
    except Exception as e:
        logger.warning(f"Content extraction LLM failed: {e}")
        # Return rich fallback content instead of empty dict
        return _generate_fallback_content(scene_ids, niche, user_brief)


def _validate_content_map(
    content_map: dict[str, dict],
    scene_ids: list[str],
    niche: str,
    user_brief: str,
) -> dict[str, dict]:
    """Validate and fix LLM-generated content map."""
    # Ensure all scene_ids have content
    for scene_id in scene_ids:
        if scene_id not in content_map or not content_map[scene_id]:
            fallback = _generate_fallback_content([scene_id], niche, user_brief)
            content_map[scene_id] = fallback.get(scene_id, {})

    # Validate hero_media_url is not a full URL (should be search query)
    for scene_id, content in content_map.items():
        if "hero_media_url" in content:
            url = content["hero_media_url"]
            if url and url.startswith("http"):
                # Convert URL to search query
                content["hero_media_url"] = "modern technology workspace"

    # Validate features arrays have content
    for scene_id, content in content_map.items():
        if scene_id.startswith("features."):
            features = content.get("features", [])
            if not features or len(features) < 3:
                content["features"] = _get_default_features(niche)

    # Validate testimonials have content
    for scene_id, content in content_map.items():
        if scene_id.startswith("testimonials."):
            testimonials = content.get("testimonials", [])
            if not testimonials or len(testimonials) < 2:
                content["testimonials"] = _get_default_testimonials(niche)

    # Validate stats/facts have content
    for scene_id, content in content_map.items():
        if scene_id.startswith("proof."):
            stats = content.get("stats", [])
            if not stats or len(stats) < 3:
                content["stats"] = _get_default_stats(niche)
        if "authority_facts" in scene_id:
            facts = content.get("facts", [])
            if not facts or len(facts) < 3:
                content["facts"] = _get_default_stats(niche)

    return content_map


def _get_default_features(niche: str) -> list[dict]:
    """Return default features for a niche."""
    defaults = {
        "saas": [
            {"title": "Создание лендингов", "description": "Генерация премиальных лендингов за минуты с помощью AI. Адаптивный дизайн, современные эффекты, готовый к публикации код.", "icon": "code"},
            {"title": "Дизайн и визуал", "description": "Профессиональный дизайн на уровне топовых агентств. Подбор цветов, типографики и изображений автоматически.", "icon": "palette"},
            {"title": "Аналитика данных", "description": "Глубокий анализ данных и визуализация результатов. Отчёты, графики и инсайты для принятия решений.", "icon": "bar-chart-3"},
            {"title": "Автоматизация", "description": "Автоматизация рутинных задач и процессов. Экономия времени и ресурсов вашей команды.", "icon": "zap"},
            {"title": "Безопасность", "description": "Полная изоляция проектов, шифрование данных и соответствие стандартам безопасности.", "icon": "shield"},
            {"title": "Масштабирование", "description": "Платформа растёт вместе с вашим бизнесом. От одного лендинга до сотен проектов.", "icon": "layers"},
        ],
        "default": [
            {"title": "Быстрый результат", "description": "Получите готовый продукт в кратчайшие сроки без потери качества.", "icon": "zap"},
            {"title": "Профессиональное качество", "description": "Результат на уровне ведущих мировых агентств и студий.", "icon": "star"},
            {"title": "Индивидуальный подход", "description": "Каждый проект уникален и создаётся под ваши конкретные задачи.", "icon": "target"},
            {"title": "Поддержка 24/7", "description": "Круглосуточная поддержка и оперативное решение любых вопросов.", "icon": "clock"},
        ],
    }
    return defaults.get(niche, defaults["default"])


def _get_default_testimonials(niche: str) -> list[dict]:
    """Return default testimonials."""
    return [
        {"quote": "Результат превзошёл все ожидания. Профессиональный подход, быстрые сроки и отличное качество. Рекомендую всем, кто ценит своё время.", "author": "Ирина Смирнова", "role": "Директор по маркетингу, TechSolutions"},
        {"quote": "Сэкономили сотни часов работы и получили продукт, который реально работает. Теперь можем сосредоточиться на развитии бизнеса.", "author": "Алексей Петров", "role": "Основатель, StartUp Hub"},
        {"quote": "Уникальный продукт с мощными возможностями. Качество на уровне топовых мировых агентств, а скорость — в разы быстрее.", "author": "Ольга Кузнецова", "role": "Креативный директор, Creative Studio"},
    ]


def _get_default_stats(niche: str) -> list[dict]:
    """Return default stats/facts."""
    return [
        {"value": "500+", "label": "Проектов реализовано"},
        {"value": "98%", "label": "Клиентов довольны"},
        {"value": "50+", "label": "Постоянных клиентов"},
        {"value": "24/7", "label": "Поддержка"},
    ]


def _generate_fallback_content(
    scene_ids: list[str],
    niche: str,
    user_brief: str,
) -> dict[str, dict]:
    """Generate rich fallback content when LLM fails."""
    # Extract brand name from brief
    brand_name = "Brand"
    brief_words = user_brief.split()
    for i, word in enumerate(brief_words):
        if word.lower() in ("для", "for") and i + 1 < len(brief_words):
            # Take next 1-3 words as brand name
            brand_parts = []
            for j in range(i + 1, min(i + 4, len(brief_words))):
                w = brief_words[j].strip("—.,!?:;")
                if w and w[0].isupper():
                    brand_parts.append(w)
                elif brand_parts:
                    break
            if brand_parts:
                brand_name = " ".join(brand_parts)
            break

    result = {}
    for scene_id in scene_ids:
        if scene_id.startswith("hero."):
            result[scene_id] = {
                "headline": f"{brand_name} — решения, которые работают",
                "subheadline": "Профессиональный подход к каждому проекту. Современные технологии и проверенные методы для вашего бизнеса.",
                "cta_primary_text": "Начать бесплатно",
                "cta_primary_href": "#contact",
                "hero_media_url": "modern business office technology",
                "kicker": "Инновационная платформа",
            }
        elif scene_id.startswith("features."):
            result[scene_id] = {
                "headline": f"Возможности {brand_name}",
                "subheadline": "Всё что нужно для успеха вашего бизнеса в одном месте",
                "features": _get_default_features(niche),
            }
        elif scene_id.startswith("proof."):
            result[scene_id] = {"stats": _get_default_stats(niche)}
        elif "authority_facts" in scene_id:
            result[scene_id] = {"facts": _get_default_stats(niche)}
        elif "comparison_block" in scene_id:
            result[scene_id] = {
                "headline": f"Почему {brand_name}",
                "before_items": [
                    "Долгие сроки разработки и согласований",
                    "Высокие затраты на команду и управление",
                    "Ограниченная гибкость и масштабируемость",
                    "Непредсказуемое качество результата",
                ],
                "after_items": [
                    "Мгновенный результат профессионального качества",
                    "Оптимальная цена без скрытых платежей",
                    "Гибкая система, которая растёт с вашим бизнесом",
                    "Стабильно высокое качество каждого проекта",
                ],
            }
        elif "case_grid" in scene_id:
            result[scene_id] = {
                "cases": [
                    {"title": "Увеличение конверсии", "description": "Редизайн лендинга для e-commerce проекта", "result": "+340% конверсии"},
                    {"title": "Ускорение разработки", "description": "Автоматизация процесса создания сайтов", "result": "В 10 раз быстрее"},
                    {"title": "Рост продаж", "description": "Комплексное решение для B2B компании", "result": "+200% продаж"},
                ],
            }
        elif scene_id.startswith("gallery."):
            result[scene_id] = {
                "headline": "Наши работы",
                "subheadline": "Посмотрите примеры наших лучших проектов",
                "gallery": [
                    {"url": "modern professional workspace", "alt": "Проект 1"},
                    {"url": "luxury interior design", "alt": "Проект 2"},
                    {"url": "creative team at work", "alt": "Проект 3"},
                    {"url": "premium product photography", "alt": "Проект 4"},
                    {"url": "elegant business meeting", "alt": "Проект 5"},
                    {"url": "modern office architecture", "alt": "Проект 6"},
                ],
            }
        elif scene_id.startswith("pricing."):
            result[scene_id] = {
                "headline": "Прозрачные цены",
                "subheadline": "Выберите подходящий тариф для вашего бизнеса",
                "pricing": [
                    {
                        "name": "Базовый",
                        "price": "от 5 000 ₽",
                        "period": "",
                        "features": ["Базовый функционал", "Поддержка по email", "1 пользователь"],
                        "featured": False,
                    },
                    {
                        "name": "Профессионал",
                        "price": "от 15 000 ₽",
                        "period": "",
                        "features": ["Все функции Базового", "Приоритетная поддержка", "До 5 пользователей", "Аналитика"],
                        "featured": True,
                    },
                    {
                        "name": "Бизнес",
                        "price": "от 30 000 ₽",
                        "period": "",
                        "features": ["Все функции Профессионала", "Персональный менеджер", "Безлимит пользователей", "API доступ"],
                        "featured": False,
                    },
                ],
            }
        elif scene_id.startswith("parallax."):
            result[scene_id] = {
                "headline": "Качество — это не случайность, а результат осознанного выбора",
                "subheadline": brand_name,
                "about_image": f"{niche} professional atmosphere",
            }
        elif scene_id.startswith("about."):
            result[scene_id] = {
                "headline": f"О компании {brand_name}",
                "subheadline": "Мы — команда профессионалов с многолетним опытом. Наша миссия — предоставлять услуги высочайшего качества, превосходя ожидания каждого клиента.",
                "cta_primary_text": "Узнать больше",
                "cta_primary_href": "#contact",
                "float_card_value": "98%",
                "float_card_label": "Клиентов довольны",
                "about_image": f"{niche} team professional",
                "about_features": [
                    {"icon": "award", "title": "10+ лет опыта"},
                    {"icon": "users", "title": "500+ клиентов"},
                    {"icon": "shield-check", "title": "Гарантия качества"},
                    {"icon": "clock", "title": "Точно в срок"},
                ],
            }
        elif scene_id.startswith("testimonials."):
            result[scene_id] = {"testimonials": _get_default_testimonials(niche)}
        elif scene_id.startswith("cta."):
            result[scene_id] = {
                "headline": "Готовы начать?",
                "subheadline": f"Оставьте заявку и {brand_name} покажет, на что способен. Бесплатная консультация без обязательств.",
                "cta_primary_text": "Оставить заявку",
                "cta_primary_href": "#contact",
            }
        elif scene_id.startswith("footer."):
            result[scene_id] = {
                "brand_name": brand_name,
                "tagline": f"{brand_name} — профессиональные решения для вашего бизнеса",
                "phone": "+7 (495) 123-45-67",
                "email": f"info@{brand_name.lower().replace(' ', '')}.ru",
                "address": "Москва, ул. Инноваций, 12",
                "social_links": [
                    {"platform": "Telegram", "url": "#"},
                    {"platform": "VK", "url": "#"},
                ],
            }

    return result


# ─────────────────────────────────────────────────────────────────
#  MAIN PLANNER
# ─────────────────────────────────────────────────────────────────

async def plan_page(
    user_brief: str,
    llm_client: Any,
    *,
    force_niche: str | None = None,
    force_theme: str | None = None,
) -> PagePlan:
    """
    Main entry point: given user brief, produce a complete PagePlan.

    1. Detect niche
    2. Detect user theme preference (OVERRIDES niche default)
    3. Select scene sequence from template
    4. Apply safe defaults for modifiers
    5. Extract content via LLM
    6. Return PagePlan
    """
    from shared.design.premium_scenes.compatibility import recommend_safe_defaults

    # Step 1: Detect niche
    niche, niche_tags = detect_niche(user_brief)
    if force_niche:
        niche = force_niche
        niche_tags = [force_niche]

    # Step 2: Select scene sequence
    scene_ids = NICHE_SCENE_TEMPLATES.get(niche, NICHE_SCENE_TEMPLATES["default"])

    # Step 3: Determine global theme
    # Priority: force_theme > user_preference > niche_default
    user_theme = detect_user_theme_preference(user_brief)
    if force_theme:
        global_theme = force_theme
    elif user_theme:
        global_theme = user_theme
        logger.info(f"User theme preference '{user_theme}' overrides niche default for '{niche}'")
    else:
        global_theme = NICHE_TO_THEME.get(niche, "light_trust_v1")

    # Step 4: Extract content via LLM
    content_map = await extract_content_with_llm(llm_client, user_brief, niche, scene_ids)

    # Step 5: Build SceneSpec list with ALTERNATING THEMES for WOW contrast
    theme_pair = ALTERNATING_THEME_PAIRS.get(global_theme, (global_theme, global_theme))
    primary_theme, contrast_theme = theme_pair
    
    # Determine which theme is "dark" and which is "light" for force rules
    _dark_themes = {"dark_premium_v1", "dark_tech_v1", "dark_elegant_v1"}
    dark_of_pair = contrast_theme if primary_theme not in _dark_themes else primary_theme
    light_of_pair = primary_theme if primary_theme not in _dark_themes else contrast_theme
    
    scenes: list[SceneSpec] = []
    alternating_idx = 0  # tracks alternation for non-forced scenes
    for i, scene_id in enumerate(scene_ids):
        modifiers = recommend_safe_defaults(scene_id, niche_tags=niche_tags)
        
        # Determine per-section theme with alternating logic
        if scene_id in FORCE_DARK_SCENES:
            section_theme = dark_of_pair
        elif scene_id in FORCE_LIGHT_SCENES:
            section_theme = light_of_pair
        else:
            # Alternate between primary and contrast
            section_theme = primary_theme if alternating_idx % 2 == 0 else contrast_theme
            alternating_idx += 1
        
        if "theme_pack" in modifiers:
            modifiers["theme_pack"] = section_theme
        
        content = content_map.get(scene_id, {})
        scenes.append(SceneSpec(
            scene_id=scene_id,
            modifiers=modifiers,
            content=content,
            order=i,
        ))
    
    logger.info(f"Page plan: niche={niche}, global_theme={global_theme}, "
                f"alternating={primary_theme}/{contrast_theme}, scenes={len(scenes)}")

    return PagePlan(
        niche=niche,
        niche_tags=niche_tags,
        global_theme=global_theme,
        scenes=scenes,
        meta={
            "user_brief": user_brief[:200],
            "scene_count": len(scenes),
            "pipeline": "scene_driven_v2_alternating",
            "user_theme_override": user_theme,
            "alternating_themes": [primary_theme, contrast_theme],
        },
    )
