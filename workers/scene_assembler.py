"""
ARCANE Premium Scenes — Scene Assembler
workers/scene_assembler.py

Собирает финальный HTML из PagePlan:
1. Для каждой SceneSpec загружает шаблон
2. Резолвит модификаторы в CSS-классы
3. Валидирует совместимость сцен (P1-FIX #4)
4. Рендерит контент через простую замену плейсхолдеров
5. Дедуплицирует CSS-классы (P1-FIX #3)
6. Собирает полный HTML-документ с динамической навигацией (P1-FIX #2)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
#  P1-FIX #5: LUCIDE ICON WHITELIST
#  Validated against Lucide icon library v0.300+
# ─────────────────────────────────────────────────────────────────

LUCIDE_ICON_WHITELIST: set[str] = {
    # Common UI
    "star", "heart", "check", "x", "plus", "minus", "search", "menu",
    "arrow-right", "arrow-left", "arrow-up", "arrow-down", "chevron-right",
    "chevron-left", "chevron-up", "chevron-down", "external-link", "link",
    "share", "download", "upload", "copy", "edit", "trash", "settings",
    "filter", "sort-asc", "sort-desc", "eye", "eye-off", "lock", "unlock",
    "bell", "bookmark", "flag", "tag", "hash", "at-sign", "paperclip",
    # Communication
    "phone", "mail", "message-circle", "message-square", "send", "inbox",
    "video", "mic", "headphones", "volume-2", "volume-x",
    # Location & Maps
    "map-pin", "map", "navigation", "compass", "globe", "home",
    # Business & Finance
    "briefcase", "building", "building-2", "credit-card", "dollar-sign",
    "trending-up", "trending-down", "bar-chart", "bar-chart-2", "pie-chart",
    "activity", "target", "award", "gift", "shopping-cart", "shopping-bag",
    "package", "truck", "receipt", "wallet", "banknote", "coins",
    # People & Users
    "user", "users", "user-check", "user-plus", "user-x", "smile",
    "frown", "meh", "thumbs-up", "thumbs-down", "hand",
    # Time & Calendar
    "clock", "timer", "calendar", "calendar-days", "alarm-clock", "hourglass",
    # Files & Documents
    "file", "file-text", "folder", "folder-open", "clipboard", "book",
    "book-open", "notebook", "scroll", "newspaper",
    # Media & Images
    "image", "camera", "film", "play", "pause", "square", "circle",
    "triangle", "hexagon", "octagon", "layers", "layout", "grid",
    # Technology
    "monitor", "smartphone", "tablet", "laptop", "server", "database",
    "cloud", "wifi", "bluetooth", "cpu", "hard-drive", "terminal",
    "code", "code-2", "braces", "binary", "bug", "git-branch",
    # Nature & Weather
    "sun", "moon", "cloud-rain", "cloud-snow", "wind", "droplets",
    "flame", "leaf", "tree", "flower", "mountain", "waves",
    # Health & Wellness
    "heart-pulse", "stethoscope", "pill", "syringe", "thermometer",
    "brain", "bone", "dna", "microscope", "test-tube",
    # Food & Drink
    "coffee", "wine", "beer", "utensils", "chef-hat", "cookie",
    "apple", "grape", "pizza", "sandwich", "soup", "cake",
    # Beauty & Personal Care
    "scissors", "palette", "brush", "spray-can", "gem", "crown",
    "sparkles", "wand", "wand-2", "droplet",
    # Fitness & Sports
    "dumbbell", "bike", "footprints", "medal", "trophy",
    # Real Estate & Construction
    "key", "door-open", "door-closed", "warehouse", "fence",
    "hammer", "wrench", "ruler", "paint-bucket", "hard-hat",
    # Legal & Education
    "scale", "gavel", "shield", "shield-check", "graduation-cap",
    "school", "library", "pen", "pen-tool", "pencil", "highlighter",
    # Transport
    "car", "bus", "train", "plane", "ship", "rocket",
    # Misc
    "zap", "bolt", "power", "battery", "plug", "lightbulb",
    "info", "help-circle", "alert-triangle", "alert-circle",
    "check-circle", "check-circle-2", "x-circle", "x-octagon",
    "loader", "refresh-cw", "rotate-cw", "maximize", "minimize",
    "move", "grip-vertical", "grip-horizontal", "more-horizontal",
    "more-vertical", "slash", "percent", "infinity",
}


def _validate_lucide_icon(icon_name: str) -> str:
    """Validate icon name against Lucide whitelist. Returns valid icon or fallback 'star'."""
    if icon_name in LUCIDE_ICON_WHITELIST:
        return icon_name
    # Try common transformations
    normalized = icon_name.lower().replace("_", "-").replace(" ", "-")
    if normalized in LUCIDE_ICON_WHITELIST:
        return normalized
    logger.debug(f"Icon {icon_name!r} not in Lucide whitelist, falling back to 'star'")
    return "star"


# ─────────────────────────────────────────────────────────────────
#  P1-FIX #3: CSS CLASS DEDUPLICATION
# ─────────────────────────────────────────────────────────────────

def _dedupe_classes(class_string: str) -> str:
    """Remove duplicate CSS classes while preserving order."""
    if not class_string:
        return class_string
    seen: set[str] = set()
    result: list[str] = []
    for cls in class_string.split():
        if cls not in seen:
            seen.add(cls)
            result.append(cls)
    return " ".join(result)


def _dedupe_html_classes(html: str) -> str:
    """Find all class="..." attributes in HTML and deduplicate their values."""
    def _replace_class(match: re.Match) -> str:
        prefix = match.group(1)  # 'class="' or "class='"
        classes = match.group(2)
        suffix = match.group(3)  # closing quote
        return f'{prefix}{_dedupe_classes(classes)}{suffix}'

    # Match class="..." and class='...'
    html = re.sub(r'(class=")([^"]*?)(")', _replace_class, html)
    html = re.sub(r"(class=')([^']*?)(')", _replace_class, html)
    return html


# ─────────────────────────────────────────────────────────────────
#  P1-FIX #2: SECTION ID MAPPING (for anchor/nav sync)
# ─────────────────────────────────────────────────────────────────

# Maps scene_id prefix to a semantic section anchor ID
SCENE_TO_SECTION_ID: dict[str, str] = {
    "hero.cinematic_fullbleed.v1": "hero",
    "hero.editorial_split.v1": "hero",
    "hero.legal_authority.v1": "hero",
    "hero.product_showcase.v1": "hero",
    "proof.stats_counters.v1": "stats",
    "features.bento_grid.v1": "services",
    "features.editorial_cards.v1": "services",
    "features.timeline_process.v1": "services",
    "trust.authority_facts_rail.v1": "about",
    "trust.case_grid.v1": "cases",
    "trust.comparison_block.v1": "about",
    "testimonials.quote_wall.v1": "reviews",
    "testimonials.marquee.v1": "reviews",
    "cta.executive_split.v1": "contact",
    "footer.authority_contact.v1": "footer",
    "gallery.masonry_grid.v1": "gallery",
    "pricing.cards.v1": "pricing",
    "parallax.quote.v1": "",
    "about.split_image.v1": "about",
}
# Add versionless aliases for backward compatibility
for _k, _v in list(SCENE_TO_SECTION_ID.items()):
    _base = re.sub(r"\.v\d+$", "", _k)
    if _base != _k and _base not in SCENE_TO_SECTION_ID:
        SCENE_TO_SECTION_ID[_base] = _v

# Maps section anchor ID to nav label (Russian)
SECTION_ID_TO_NAV_LABEL: dict[str, str] = {
    "about": "О нас",
    "services": "Услуги",
    "cases": "Кейсы",
    "reviews": "Отзывы",
    "contact": "Контакты",
    "gallery": "Галерея",
    "pricing": "Цены",
}


def _inject_section_id(rendered_html: str, section_id: str, used_ids: set = None) -> str:
    """Inject id= attribute into the first <section> or <footer> tag if not already present.
    P4-FIX: Tracks used IDs to prevent duplicates."""
    if not section_id:
        return rendered_html
    # P4-FIX: Deduplicate section IDs
    if used_ids is not None:
        if section_id in used_ids:
            # Append numeric suffix: about -> about-2, about-3, etc.
            counter = 2
            while f"{section_id}-{counter}" in used_ids:
                counter += 1
            section_id = f"{section_id}-{counter}"
        used_ids.add(section_id)

    # Check if id= already exists on the root element
    root_tag_match = re.match(r'(<!--[^>]*-->\s*)?(<(?:section|footer)\b)', rendered_html, re.DOTALL)
    if not root_tag_match:
        return rendered_html

    tag_start = root_tag_match.end()
    # Check if id= already present in this tag
    tag_end = rendered_html.find('>', tag_start)
    tag_content = rendered_html[root_tag_match.start(2):tag_end]
    if 'id="' in tag_content or "id='" in tag_content:
        return rendered_html

    # Inject id= right after the tag name
    insert_pos = root_tag_match.end()
    return rendered_html[:insert_pos] + f' id="{section_id}"' + rendered_html[insert_pos:]


def _build_nav_links(scene_ids: list[str], text_class: str) -> str:
    """Build navigation links HTML based on actual scenes in the page plan."""
    seen_sections: set[str] = set()
    nav_items: list[tuple[str, str]] = []  # (anchor_id, label)

    for scene_id in scene_ids:
        section_id = SCENE_TO_SECTION_ID.get(scene_id, "")
        if not section_id or section_id in seen_sections:
            continue
        label = SECTION_ID_TO_NAV_LABEL.get(section_id)
        if label:
            seen_sections.add(section_id)
            nav_items.append((section_id, label))

    return " ".join(
        f'<a href="#{anchor}" class="{text_class} text-sm hover:opacity-70 transition-opacity">{label}</a>'
        for anchor, label in nav_items
    )


def _build_footer_nav_html(scene_ids: list[str], text_class: str, accent_class: str) -> str:
    """Build footer navigation links based on actual scenes."""
    seen_sections: set[str] = set()
    nav_items: list[tuple[str, str]] = []

    for scene_id in scene_ids:
        section_id = SCENE_TO_SECTION_ID.get(scene_id, "")
        if not section_id or section_id in seen_sections:
            continue
        label = SECTION_ID_TO_NAV_LABEL.get(section_id)
        if label:
            seen_sections.add(section_id)
            nav_items.append((section_id, label))

    return "\n".join(
        f'          <a href="#{anchor}" class="text-sm {text_class} hover:{accent_class} transition-colors">{label}</a>'
        for anchor, label in nav_items
    )


# ─────────────────────────────────────────────────────────────────
#  AI IMAGE GENERATION (PRIMARY) + PEXELS FALLBACK
# ─────────────────────────────────────────────────────────────────

_AI_IMAGE_CACHE: dict[str, str] = {}  # query -> url, avoid duplicate generations

async def generate_ai_image(
    query: str,
    *,
    style: str = "cinematic",
    size: str = "1792x1024",
    project_dir: str = "/tmp/arcane_images",
) -> Optional[str]:
    """Generate an AI image using Nano Banana 2 (Gemini Flash) via OpenRouter.
    
    Returns a local file path or None on failure.
    Falls back to Pexels if AI generation fails.
    """
    # Check cache first
    cache_key = f"{query}:{style}:{size}"
    if cache_key in _AI_IMAGE_CACHE:
        return _AI_IMAGE_CACHE[cache_key]
    
    try:
        import os
        import uuid
        import base64
        
        os.makedirs(project_dir, exist_ok=True)
        
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            logger.warning("AI image gen: no OPENROUTER_API_KEY, falling back to Pexels")
            return await fetch_pexels_image(query)
        
        # Style presets for better prompts
        style_prompts = {
            "cinematic": "Cinematic photograph, dramatic lighting, film grain, wide angle, 8K",
            "photorealistic": "Ultra-realistic photograph, 8K resolution, professional lighting",
            "illustration": "Digital illustration, clean lines, vibrant colors, professional",
            "3d": "3D rendered image, high quality, realistic materials, professional lighting",
            "minimal": "Minimalist design, clean, simple, modern aesthetic",
            "editorial": "Editorial photography, magazine quality, artistic composition",
        }
        style_suffix = style_prompts.get(style, style_prompts["cinematic"])
        full_prompt = f"{query}. {style_suffix}. No text, no watermarks, no logos."
        
        if httpx is None:
            logger.warning("AI image gen: httpx not available, falling back to Pexels")
            return await fetch_pexels_image(query)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.5-flash-image",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"Generate this image: {full_prompt}"}
                            ]
                        }
                    ],
                    "max_tokens": 4096,
                },
            )
            
            if resp.status_code != 200:
                logger.warning(f"AI image gen failed ({resp.status_code}), falling back to Pexels")
                return await fetch_pexels_image(query)
            
            data = resp.json()
            # Extract image from response
            choices = data.get("choices", [])
            if not choices:
                return await fetch_pexels_image(query)
            
            message = choices[0].get("message", {})
            
            # Handle message.images[] format (OpenRouter Nano Banana / Gemini)
            images_list = message.get("images", [])
            if images_list:
                for img_entry in images_list:
                    if isinstance(img_entry, dict):
                        url = ""
                        if img_entry.get("type") == "image_url":
                            url = img_entry.get("image_url", {}).get("url", "")
                        elif img_entry.get("url"):
                            url = img_entry["url"]
                        if url.startswith("data:image"):
                            header, b64 = url.split(",", 1)
                            ext = "png" if "png" in header else "jpg"
                            filename = f"{uuid.uuid4().hex[:12]}.{ext}"
                            filepath = os.path.join(project_dir, filename)
                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(b64))
                            web_dir = "/var/www/demo/images"
                            os.makedirs(web_dir, exist_ok=True)
                            import shutil
                            shutil.copy2(filepath, os.path.join(web_dir, filename))
                            public_url = f"https://arcaneai.ru/demo/images/{filename}"
                            _AI_IMAGE_CACHE[cache_key] = public_url
                            logger.info(f"AI image generated (images[]): {filename} for query: {query[:50]}")
                            return public_url
                        elif url.startswith("http"):
                            _AI_IMAGE_CACHE[cache_key] = url
                            return url
            
            content = message.get("content", "")
            
            # Handle multipart content (image + text)
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        img_data = part.get("image_url", {}).get("url", "")
                        if img_data.startswith("data:image"):
                            # Base64 encoded image
                            header, b64 = img_data.split(",", 1)
                            ext = "png" if "png" in header else "jpg"
                            filename = f"{uuid.uuid4().hex[:12]}.{ext}"
                            filepath = os.path.join(project_dir, filename)
                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(b64))
                            # Serve via public URL
                            # Images served from /demo/images/ (unified URL contract)
                            # Copy to web-accessible directory
                            web_dir = "/var/www/demo/images"
                            os.makedirs(web_dir, exist_ok=True)
                            import shutil
                            shutil.copy2(filepath, os.path.join(web_dir, filename))
                            public_url = f"https://arcaneai.ru/demo/images/{filename}"
                            _AI_IMAGE_CACHE[cache_key] = public_url
                            logger.info(f"AI image generated: {filename} for query: {query[:50]}")
                            return public_url
                        elif img_data.startswith("http"):
                            _AI_IMAGE_CACHE[cache_key] = img_data
                            return img_data
            
            # If we couldn't extract image, fall back
            logger.warning(f"AI image gen: could not extract image from response, falling back to Pexels")
            return await fetch_pexels_image(query)
            
    except Exception as e:
        import traceback as _tb; logger.warning(f"AI image gen failed for {query!r}: {e}\n{_tb.format_exc()}")
        return await fetch_pexels_image(query)


async def fetch_image(query: str, *, orientation: str = "landscape", style: str = "cinematic", project_dir: str = "/tmp/arcane_images") -> Optional[str]:
    """Unified image fetcher: tries AI generation first, falls back to Pexels."""
    # Try AI generation first
    result = await generate_ai_image(query, style=style, project_dir=project_dir)
    if result:
        return result
    # Fall back to Pexels
    return await fetch_pexels_image(query, orientation=orientation)


async def fetch_pexels_image(query: str, *, orientation: str = "landscape") -> Optional[str]:
    """Fetch a Pexels image URL for the given query."""
    try:
        import os
        import aiohttp
        api_key = os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            return None
        url = "https://api.pexels.com/v1/search"
        params = {"query": query, "per_page": 3, "orientation": orientation}
        headers = {"Authorization": api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    photos = data.get("photos", [])
                    if photos:
                        return photos[0]["src"]["large2x"]
        return None
    except Exception as e:
        logger.warning(f"Pexels fetch failed for {query!r}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
#  P1-FIX #6: NICHE-SPECIFIC COPY DEFAULTS
# ─────────────────────────────────────────────────────────────────

NICHE_COPY_DEFAULTS: dict[str, dict[str, str]] = {
    "restaurant": {
        "kicker": "Гастрономическое удовольствие",
        "social_proof": "Более 10 000 гостей ежемесячно",
        "trust_1": "Свежие продукты каждый день",
        "trust_2": "Бронирование онлайн",
        "trust_3": "Авторская кухня шеф-повара",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Забронировать столик",
        "cta_secondary_text": "Посмотреть меню",
    },
    "fitness": {
        "kicker": "Путь к идеальной форме",
        "social_proof": "Более 5 000 активных членов клуба",
        "trust_1": "Первая тренировка бесплатно",
        "trust_2": "Персональный подход",
        "trust_3": "Современное оборудование",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Записаться на тренировку",
        "cta_secondary_text": "Расписание занятий",
    },
    "beauty": {
        "kicker": "Искусство красоты и стиля",
        "social_proof": "Более 15 000 довольных клиентов",
        "trust_1": "Премиальная косметика",
        "trust_2": "Мастера с опытом 10+ лет",
        "trust_3": "Индивидуальный подход",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Записаться на приём",
        "cta_secondary_text": "Наши услуги",
    },
    "real_estate": {
        "kicker": "Ваш надёжный партнёр в недвижимости",
        "social_proof": "Более 2 000 успешных сделок",
        "trust_1": "Полное юридическое сопровождение",
        "trust_2": "Без скрытых комиссий",
        "trust_3": "Гарантия чистоты сделки",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Получить консультацию",
        "cta_secondary_text": "Каталог объектов",
    },
    "legal": {
        "kicker": "Правовая защита высшего уровня",
        "social_proof": "Более 3 000 выигранных дел",
        "trust_1": "Конфиденциальность гарантирована",
        "trust_2": "Первая консультация бесплатно",
        "trust_3": "Опыт работы 20+ лет",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Записаться на консультацию",
        "cta_secondary_text": "Наши практики",
    },
    "medical": {
        "kicker": "Забота о вашем здоровье",
        "social_proof": "Более 50 000 пациентов доверяют нам",
        "trust_1": "Современное оборудование",
        "trust_2": "Врачи высшей категории",
        "trust_3": "Комфортная атмосфера",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Записаться на приём",
        "cta_secondary_text": "Наши специалисты",
    },
    "saas": {
        "kicker": "Технологии для вашего бизнеса",
        "social_proof": "Уже используют 500+ компаний",
        "trust_1": "14 дней бесплатно",
        "trust_2": "Без привязки карты",
        "trust_3": "Поддержка 24/7",
        "form_placeholder_name": "Рабочий email",
        "form_placeholder_phone": "Название компании",
        "form_cta": "Попробовать бесплатно",
        "cta_secondary_text": "Посмотреть демо",
    },
    "finance": {
        "kicker": "Финансовые решения для бизнеса",
        "social_proof": "Управляем активами на 10+ млрд ₽",
        "trust_1": "Лицензия ЦБ РФ",
        "trust_2": "Персональный менеджер",
        "trust_3": "Прозрачные условия",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Получить предложение",
        "cta_secondary_text": "Наши продукты",
    },
    "education": {
        "kicker": "Образование, которое меняет жизнь",
        "social_proof": "Более 20 000 выпускников",
        "trust_1": "Диплом государственного образца",
        "trust_2": "Практика с первого дня",
        "trust_3": "Трудоустройство выпускников",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Записаться на курс",
        "cta_secondary_text": "Программы обучения",
    },
    "hospitality": {
        "kicker": "Незабываемый отдых и комфорт",
        "social_proof": "Рейтинг 4.9 на Booking.com",
        "trust_1": "Бесплатная отмена бронирования",
        "trust_2": "Трансфер из аэропорта",
        "trust_3": "Завтрак включён",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Забронировать номер",
        "cta_secondary_text": "Посмотреть номера",
    },
    "luxury_service": {
        "kicker": "Премиальный сервис без компромиссов",
        "social_proof": "Выбор VIP-клиентов с 2010 года",
        "trust_1": "Индивидуальный подход",
        "trust_2": "Конфиденциальность",
        "trust_3": "Эксклюзивные условия",
        "form_placeholder_name": "Ваше имя",
        "form_placeholder_phone": "+7 (___) ___-__-__",
        "form_cta": "Связаться с менеджером",
        "cta_secondary_text": "Наши услуги",
    },
}

DEFAULT_COPY = {
    "kicker": "Премиальный сервис",
    "social_proof": "Уже используют 500+ компаний",
    "trust_1": "Бесплатная консультация",
    "trust_2": "Без предоплаты",
    "trust_3": "Гарантия результата",
    "form_placeholder_name": "Ваше имя",
    "form_placeholder_phone": "+7 (___) ___-__-__",
    "form_cta": "Связаться",
    "cta_secondary_text": "Узнать больше",
}


def _get_niche_copy(niche: str, key: str, fallback: str = "") -> str:
    """Get niche-specific copy text with fallback chain."""
    niche_defaults = NICHE_COPY_DEFAULTS.get(niche, {})
    return niche_defaults.get(key, DEFAULT_COPY.get(key, fallback))


# ─────────────────────────────────────────────────────────────────
#  TEMPLATE RENDERER
# ─────────────────────────────────────────────────────────────────

def _safe_str(value: Any, default: str = "") -> str:
    """Convert value to safe HTML string."""
    if value is None:
        return default
    return str(value).replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_features_html(features: list[dict], surface_class: str, icon_class: str) -> str:
    """Render features list to HTML cards."""
    html_parts = []
    import re as _re
    for feat in features:
        icon = feat.get("icon", "star")
        title = _safe_str(feat.get("title", ""))
        desc = _safe_str(feat.get("description", ""))
        # P1-FIX #5 + P4-FIX: Validate and normalize icon name
        icon_str = str(icon).strip()
        # Normalize: CamelCase -> kebab-case, underscores -> hyphens
        normalized_icon = _re.sub(r'(?<=[a-z])(?=[A-Z])', '-', icon_str).lower().replace('_', '-').replace(' ', '-')
        if _re.match(r'^[a-z][a-z0-9-]*$', normalized_icon):
            validated_icon = _validate_lucide_icon(normalized_icon)
            icon_html = f'<i data-lucide="{validated_icon}" class="w-6 h-6"></i>'
        elif len(icon_str) <= 2:
            # Single emoji character — use as-is
            icon_html = f'<span class="text-2xl">{icon_str}</span>'
        else:
            # Fallback: use star icon instead of raw text
            icon_html = f'<i data-lucide="star" class="w-6 h-6"></i>'
        html_parts.append(f"""
        <div class="{surface_class} p-6 flex flex-col gap-3">
          {icon_html}
          <h3 class="font-semibold text-lg">{title}</h3>
          <p class="text-sm opacity-70 leading-relaxed">{desc}</p>
        </div>""")
    return "\n".join(html_parts)


def _render_stats_html(stats: list[dict], heading_class: str, muted_class: str) -> str:
    """Render stats list to HTML."""
    html_parts = []
    for stat in stats:
        value = _safe_str(stat.get("value", ""))
        label = _safe_str(stat.get("label", ""))
        html_parts.append(f"""
        <div class="flex flex-col items-center gap-1 text-center">
          <span class="{heading_class} text-4xl md:text-5xl font-black">{value}</span>
          <span class="{muted_class} text-sm">{label}</span>
        </div>""")
    return "\n".join(html_parts)


def _render_testimonials_html(testimonials: list[dict], surface_class: str) -> str:
    """Render testimonials to HTML cards."""
    html_parts = []
    for t in testimonials:
        quote = _safe_str(t.get("quote", ""))
        author = _safe_str(t.get("author", ""))
        role = _safe_str(t.get("role", ""))
        html_parts.append(f"""
        <div class="{surface_class} p-6 flex flex-col gap-4">
          <p class="text-base leading-relaxed italic">&ldquo;{quote}&rdquo;</p>
          <div class="flex flex-col gap-0.5">
            <span class="font-semibold text-sm">{author}</span>
            <span class="text-xs opacity-60">{role}</span>
          </div>
        </div>""")
    return "\n".join(html_parts)


def _render_facts_html(facts: list[dict], heading_class: str, muted_class: str) -> str:
    """Render authority facts to HTML."""
    html_parts = []
    for fact in facts:
        value = _safe_str(fact.get("value", ""))
        label = _safe_str(fact.get("label", ""))
        html_parts.append(f"""
        <div class="flex flex-col items-center gap-1 text-center px-6">
          <span class="{heading_class} text-3xl font-bold">{value}</span>
          <span class="{muted_class} text-xs uppercase tracking-widest">{label}</span>
        </div>""")
    return "\n".join(html_parts)


def _render_cases_html(cases: list[dict], surface_class: str) -> str:
    """Render case studies to HTML."""
    html_parts = []
    for case in cases:
        title = _safe_str(case.get("title", ""))
        desc = _safe_str(case.get("description", ""))
        result = _safe_str(case.get("result", ""))
        html_parts.append(f"""
        <div class="{surface_class} p-6 flex flex-col gap-3">
          <h3 class="font-semibold text-base">{title}</h3>
          <p class="text-sm opacity-70 leading-relaxed">{desc}</p>
          {f'<p class="text-sm font-semibold text-green-600">{result}</p>' if result else ''}
        </div>""")
    return "\n".join(html_parts)


def _render_steps_html(steps: list[dict], accent_class: str) -> str:
    """Render process steps to HTML."""
    html_parts = []
    for i, step in enumerate(steps, 1):
        title = _safe_str(step.get("title", ""))
        desc = _safe_str(step.get("description", ""))
        html_parts.append(f"""
        <div class="flex gap-4 items-start">
          <div class="{accent_class} w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0">{i}</div>
          <div class="flex flex-col gap-1">
            <h3 class="font-semibold text-base">{title}</h3>
            <p class="text-sm opacity-70 leading-relaxed">{desc}</p>
          </div>
        </div>""")
    return "\n".join(html_parts)


def _render_comparison_html(before_items: list, after_items: list) -> str:
    """Render before/after comparison."""
    before_html = "\n".join(
        f'<li class="flex items-center gap-2 text-sm"><span class="text-red-500">✗</span> {_safe_str(item)}</li>'
        for item in before_items
    )
    after_html = "\n".join(
        f'<li class="flex items-center gap-2 text-sm"><span class="text-green-500">✓</span> {_safe_str(item)}</li>'
        for item in after_items
    )
    return f"""
    <div class="grid md:grid-cols-2 gap-6">
      <div class="bg-red-50 border border-red-100 rounded-2xl p-6">
        <h3 class="font-semibold mb-4 text-red-700">Без нас</h3>
        <ul class="flex flex-col gap-3">{before_html}</ul>
      </div>
      <div class="bg-green-50 border border-green-100 rounded-2xl p-6">
        <h3 class="font-semibold mb-4 text-green-700">С нами</h3>
        <ul class="flex flex-col gap-3">{after_html}</ul>
      </div>
    </div>"""


def _render_footer_links(social_links: list[dict]) -> str:
    """Render social links."""
    icons = {"instagram": "📷", "telegram": "✈️", "whatsapp": "💬", "vk": "🔵", "youtube": "▶️", "facebook": "👤"}
    html_parts = []
    for link in social_links:
        platform = link.get("platform", "").lower()
        url = link.get("url", "#")
        icon = icons.get(platform, "🔗")
        html_parts.append(f'<a href="{url}" class="hover:opacity-70 transition-opacity">{icon} {platform.capitalize()}</a>')
    return " · ".join(html_parts)


def _render_gallery_html(gallery_items: list[dict], surface_class: str) -> str:
    """Render gallery grid items to HTML."""
    html_parts = []
    for i, item in enumerate(gallery_items):
        url = item.get("url", item.get("image", ""))
        alt = _safe_str(item.get("alt", item.get("title", f"Gallery image {i+1}")))
        # Alternate between tall and regular aspect ratios for visual interest
        aspect = "aspect-[3/4]" if i % 3 == 0 else "aspect-square" if i % 3 == 1 else "aspect-video"
        html_parts.append(f"""
        <div class="group relative overflow-hidden rounded-xl {aspect} {surface_class} hover-lift tilt-card">
          <img src="{url}" alt="{alt}" class="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110" loading="lazy" />
          <div class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors duration-500 flex items-end">
            <span class="text-white text-sm font-medium p-4 opacity-0 group-hover:opacity-100 transition-opacity duration-500 translate-y-4 group-hover:translate-y-0">{alt}</span>
          </div>
        </div>""")
    return "\n".join(html_parts)


def _render_pricing_html(pricing_items: list[dict], surface_class: str, accent_bg: str, button_class: str) -> str:
    """Render pricing cards to HTML."""
    html_parts = []
    for item in pricing_items:
        name = _safe_str(item.get("name", item.get("title", "")))
        price = _safe_str(item.get("price", ""))
        period = _safe_str(item.get("period", ""))
        features = item.get("features", [])
        is_featured = item.get("featured", False)
        cta_text = _safe_str(item.get("cta_text", "Выбрать"))
        
        # Build features list
        features_html = "\n".join(
            f'<li class="flex items-center gap-2 text-sm"><span class="text-green-500">✓</span> {_safe_str(f)}</li>'
            for f in features
        )
        
        if is_featured:
            card_class = f"{accent_bg} text-white rounded-2xl p-8 flex flex-col gap-6 relative shadow-2xl scale-105 z-10"
            badge = '<span class="absolute -top-3 left-1/2 -translate-x-1/2 bg-white text-black text-xs font-bold px-4 py-1 rounded-full shadow-lg">Популярный</span>'
            btn_class = "inline-flex items-center justify-center w-full rounded-xl px-6 py-3 text-sm font-semibold bg-white text-gray-900 hover:bg-gray-100 transition-colors"
        else:
            card_class = f"{surface_class} p-8 flex flex-col gap-6 hover-lift"
            badge = ""
            btn_class = button_class + " w-full justify-center"
        
        html_parts.append(f"""
        <div class="{card_class}">
          {badge}
          <div class="flex flex-col gap-2">
            <h3 class="font-semibold text-lg">{name}</h3>
            <div class="flex items-baseline gap-1">
              <span class="text-4xl font-black">{price}</span>
              {f'<span class="text-sm opacity-60">{period}</span>' if period else ''}
            </div>
          </div>
          <ul class="flex flex-col gap-3 flex-1">{features_html}</ul>
          <a href="#contact" class="{btn_class}">{cta_text}</a>
        </div>""")
    return "\n".join(html_parts)


def _render_about_features_html(features: list[dict], accent_class: str) -> str:
    """Render about section feature highlights."""
    html_parts = []
    for feat in features:
        icon = feat.get("icon", "check-circle")
        title = _safe_str(feat.get("title", ""))
        if re.match(r'^[a-z][a-z0-9-]+$', str(icon)):
            validated_icon = _validate_lucide_icon(str(icon))
            icon_html = f'<i data-lucide="{validated_icon}" class="w-5 h-5 {accent_class}"></i>'
        else:
            icon_html = f'<span class="text-lg">{icon}</span>'
        html_parts.append(f"""
        <div class="flex items-center gap-3">
          {icon_html}
          <span class="text-sm font-medium">{title}</span>
        </div>""")
    return "\n".join(html_parts)


# ─────────────────────────────────────────────────────────────────
#  P1-FIX #4: SLOT VALIDATION (wires compatibility.py into assembler)
# ─────────────────────────────────────────────────────────────────

def _validate_and_fix_scene(
    scene_id: str,
    modifiers: dict[str, str],
    content: dict[str, Any],
    niche_tags: list[str],
) -> tuple[dict[str, str], dict[str, Any], list[str]]:
    """
    Validate scene modifiers and content against compatibility matrix.
    Auto-fix issues where possible, log warnings for the rest.
    Returns (fixed_modifiers, fixed_content, warnings).
    """
    warnings: list[str] = []
    try:
        from shared.design.premium_scenes.compatibility import (
            validate_scene_compatibility,
            recommend_safe_defaults,
            COMPATIBILITY_MATRIX,
        )
    except ImportError:
        logger.warning("compatibility.py not available, skipping validation")
        return modifiers, content, warnings

    # Run validation
    result = validate_scene_compatibility(
        scene_id=scene_id,
        modifiers=modifiers,
        content=content,
        niche_tags=niche_tags,
    )

    if result["ok"]:
        return modifiers, content, warnings

    # Auto-fix: replace invalid modifiers with safe defaults
    fixed_modifiers = dict(modifiers)
    safe_defaults = recommend_safe_defaults(scene_id, niche_tags=niche_tags)

    for error_msg in result["errors"]:
        # Check if it's a modifier error
        if "not allowed for scene" in error_msg:
            # Extract the modifier key from error message
            key_match = re.search(r"Modifier '(\w+)'", error_msg)
            if key_match:
                key = key_match.group(1)
                if key in safe_defaults:
                    fixed_modifiers[key] = safe_defaults[key]
                    warnings.append(f"Auto-fixed modifier {key!r} to safe default {safe_defaults[key]!r}")
                    logger.info(f"Scene {scene_id}: auto-fixed {key}={safe_defaults[key]}")

        # Check if it's a missing content slot
        elif "Required content slot" in error_msg:
            slot_match = re.search(r"slot '(\w+)'", error_msg)
            if slot_match:
                slot = slot_match.group(1)
                if slot not in content or content[slot] in (None, "", []):
                    # Provide sensible defaults for missing required slots
                    slot_defaults = {
                        "headline": "Добро пожаловать",
                        "subheadline": "Мы создаём лучший опыт для наших клиентов",
                        "cta_primary_text": "Связаться",
                        "cta_primary_href": "#contact",
                        "hero_media_url": "modern professional business",
                    }
                    if slot in slot_defaults:
                        content[slot] = slot_defaults[slot]
                        warnings.append(f"Auto-filled missing slot {slot!r} with default")
                        logger.info(f"Scene {scene_id}: auto-filled slot {slot}")

    return fixed_modifiers, content, warnings


# ─────────────────────────────────────────────────────────────────
#  SCENE RENDERER
# ─────────────────────────────────────────────────────────────────

async def render_scene(
    template: str,
    *,
    scene_id: str = "",
    modifiers: dict[str, str],
    content: dict[str, Any],
    bundle: dict[str, Any],
    niche: str = "default",
    fetch_images: bool = True,
) -> str:
    """Render a single scene template with modifiers and content."""
    from shared.design.premium_scenes.modifier_enums import (
        BUTTON_STYLE_CLASSES,
        CONTAINER_MODE_CLASSES,
        SURFACE_STYLE_CLASSES,
    )

    theme = bundle.get("theme_pack")
    spacing = bundle.get("spacing")
    motion = bundle.get("motion")

    # Build substitution map
    subs: dict[str, str] = {}

    # Theme tokens
    if theme:
        subs["{{BG}}"] = theme.bg
        subs["{{SURFACE}}"] = theme.surface
        subs["{{TEXT}}"] = theme.text
        subs["{{MUTED}}"] = theme.muted
        subs["{{ACCENT}}"] = theme.accent
        subs["{{ACCENT_BG}}"] = theme.accent_bg
        subs["{{BORDER}}"] = theme.border

    # Spacing tokens
    if spacing:
        subs["{{SECTION_PADDING}}"] = spacing.section
        subs["{{GAP}}"] = spacing.gap
        subs["{{CONTAINER}}"] = spacing.container

    # CSS class tokens
    subs["{{HEADING_CLASS}}"] = bundle.get("heading_class", "font-sans font-bold")
    subs["{{BODY_CLASS}}"] = bundle.get("body_class", "font-sans font-normal")
    subs["{{MEDIA_CLASS}}"] = bundle.get("media_class", "rounded-2xl object-cover")
    subs["{{BUTTON_CLASS}}"] = bundle.get("button_class", BUTTON_STYLE_CLASSES["filled_accent"])
    subs["{{CONTAINER_CLASS}}"] = bundle.get("container_class", CONTAINER_MODE_CLASSES["container_standard"])
    subs["{{SURFACE_CLASS}}"] = bundle.get("surface_class", SURFACE_STYLE_CLASSES["surface_soft"])
    subs["{{ACCENT_CARD_CLASS}}"] = bundle.get("accent_card_class", "")
    subs["{{DIVIDER_CLASS}}"] = bundle.get("divider_class", "")
    subs["{{ICON_CLASS}}"] = bundle.get("icon_class", "w-5 h-5")
    subs["{{DECORATOR}}"] = ""  # Will be replaced by decorator partial if needed

    # Motion tokens
    if motion:
        subs["{{REVEAL_CLASS}}"] = "reveal-on-scroll" if motion.reveal else ""
        subs["{{HOVER_CLASS}}"] = "hover-lift" if motion.hover else ""
    else:
        subs["{{REVEAL_CLASS}}"] = ""
        subs["{{HOVER_CLASS}}"] = ""

    # Content tokens — simple strings
    subs["{{HEADLINE}}"] = _safe_str(content.get("headline", content.get("title", "")))
    subs["{{SUBHEADLINE}}"] = _safe_str(content.get("subheadline", content.get("subtitle", "")))
    subs["{{CTA_PRIMARY_TEXT}}"] = _safe_str(content.get("cta_primary_text", _get_niche_copy(niche, "form_cta", "Связаться")))
    subs["{{CTA_PRIMARY_HREF}}"] = content.get("cta_primary_href", "#contact")
    subs["{{CTA_SECONDARY_TEXT}}"] = _safe_str(content.get("cta_secondary_text", _get_niche_copy(niche, "cta_secondary_text", "")))
    subs["{{CTA_SECONDARY_HREF}}"] = content.get("cta_secondary_href", "#about")
    subs["{{BRAND_NAME}}"] = _safe_str(content.get("brand_name", ""))
    subs["{{PHONE}}"] = _safe_str(content.get("phone", ""))
    subs["{{EMAIL}}"] = _safe_str(content.get("email", ""))
    subs["{{ADDRESS}}"] = _safe_str(content.get("address", ""))

    # Hero media — with robust Pexels fallback chain
    hero_media_url = content.get("hero_media_url", "")
    if fetch_images and (not hero_media_url or not hero_media_url.startswith("http")):
        query = hero_media_url or f"{niche} professional business"
        # Try 1: full query
        # AI image generation with Pexels fallback
        project_img_dir = f"/root/workspace/images"  # P4-FIX BUG-005: unified path
        fetched = await fetch_image(query, style="cinematic", project_dir=project_img_dir)
        if not fetched:
            short_query = " ".join(query.split()[:2])
            fetched = await fetch_image(short_query, style="cinematic", project_dir=project_img_dir)
        if not fetched:
            niche_queries = {
                "saas": "futuristic technology dashboard holographic",
                "restaurant": "luxury restaurant interior warm lighting",
                "fitness": "dynamic fitness athlete gym action",
                "beauty": "luxury beauty salon elegant interior",
                "real_estate": "modern luxury apartment panoramic view",
                "legal": "prestigious law office mahogany desk",
                "medical": "modern medical clinic bright clean",
                "finance": "financial trading floor modern",
                "education": "modern university campus bright",
                "hospitality": "luxury hotel lobby chandelier marble",
            }
            fallback_query = niche_queries.get(niche, "modern premium business")
            fetched = await fetch_image(fallback_query, style="cinematic", project_dir=project_img_dir)
        hero_media_url = fetched or "https://images.pexels.com/photos/3184291/pexels-photo-3184291.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750"
    elif not hero_media_url:
        hero_media_url = "https://images.pexels.com/photos/3184291/pexels-photo-3184291.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750"
    subs["{{HERO_MEDIA_URL}}"] = hero_media_url

    # ── Multi-photo: fetch Pexels images for features, about, parallax sections ──
    if fetch_images:
        niche_query = content.get("niche_query", content.get("headline", "business"))
        # Feature images (up to 5)
        for i in range(1, 6):
            key = f"feature_{i}_image"
            placeholder = f"{{{{FEATURE_{i}_IMAGE}}}}"
            img_url = content.get(key, "")
            if not img_url or not img_url.startswith("http"):
                query = img_url or f"{niche_query} professional"
                fetched = await fetch_image(query, style="editorial", project_dir=f"/root/workspace/images")  # P4-FIX BUG-005
                img_url = fetched or "https://images.pexels.com/photos/3184291/pexels-photo-3184291.jpeg?auto=compress&cs=tinysrgb&w=800"
            subs[placeholder] = img_url
        # About / parallax background image
        about_img = content.get("about_image", "")
        if not about_img or not about_img.startswith("http"):
            query = about_img or f"{niche_query} team workspace"
            fetched = await fetch_image(query, style="editorial", project_dir=f"/root/workspace/images")  # P4-FIX BUG-005
            about_img = fetched or ""
        subs["{{ABOUT_IMAGE}}"] = about_img

    # ── Extra content tokens from enhanced templates ──
    # P1-FIX #6: Use niche-specific copy defaults instead of generic ones
    subs["{{KICKER}}"] = _safe_str(content.get("kicker", _get_niche_copy(niche, "kicker")))
    subs["{{SOCIAL_PROOF}}"] = _safe_str(content.get("social_proof", _get_niche_copy(niche, "social_proof")))
    subs["{{TRUST_1}}"] = _safe_str(content.get("trust_1", _get_niche_copy(niche, "trust_1")))
    subs["{{TRUST_2}}"] = _safe_str(content.get("trust_2", _get_niche_copy(niche, "trust_2")))
    subs["{{TRUST_3}}"] = _safe_str(content.get("trust_3", _get_niche_copy(niche, "trust_3")))
    subs["{{FLOAT_CARD_LABEL}}"] = _safe_str(content.get("float_card_label", "Клиентов довольны"))
    subs["{{FLOAT_CARD_VALUE}}"] = _safe_str(content.get("float_card_value", "98%"))
    subs["{{TOP_BADGE}}"] = _safe_str(content.get("top_badge", "Топ-1 в регионе"))
    subs["{{BROWSER_URL}}"] = _safe_str(content.get("browser_url", "yoursite.com"))
    subs["{{FORM_PLACEHOLDER_NAME}}"] = _safe_str(content.get("form_placeholder_name", _get_niche_copy(niche, "form_placeholder_name")))
    subs["{{FORM_PLACEHOLDER_PHONE}}"] = _safe_str(content.get("form_placeholder_phone", _get_niche_copy(niche, "form_placeholder_phone")))
    subs["{{FORM_CTA}}"] = _safe_str(content.get("form_cta", _get_niche_copy(niche, "form_cta")))

    # ── CRITICAL FIX: Convert features ARRAY to individual slots ──
    # LLM returns features: [{title, description, icon}] but templates expect
    # {{FEATURE_1_TITLE}}, {{FEATURE_1_ICON}}, etc.
    features_arr = content.get("features", [])
    if isinstance(features_arr, list) and features_arr:
        for i, feat in enumerate(features_arr[:5], 1):
            if isinstance(feat, dict):
                if f"feature_{i}_title" not in content:
                    content[f"feature_{i}_title"] = feat.get("title", "")
                if f"feature_{i}_desc" not in content:
                    content[f"feature_{i}_desc"] = feat.get("description", feat.get("desc", ""))
                if f"feature_{i}_icon" not in content:
                    content[f"feature_{i}_icon"] = feat.get("icon", "star")
                if f"feature_{i}_quote" not in content:
                    content[f"feature_{i}_quote"] = feat.get("quote", "")
                if f"feature_{i}_stat" not in content:
                    content[f"feature_{i}_stat"] = feat.get("stat", "100")
                if f"feature_{i}_stat_label" not in content:
                    content[f"feature_{i}_stat_label"] = feat.get("stat_label", feat.get("title", ""))

    # ── CRITICAL FIX: Convert stats ARRAY to individual slots ──
    stats_arr = content.get("stats", [])
    if isinstance(stats_arr, list) and stats_arr:
        for i, stat in enumerate(stats_arr[:4], 1):
            if isinstance(stat, dict):
                if f"stat_{i}_value" not in content:
                    content[f"stat_{i}_value"] = stat.get("value", "0")
                if f"stat_{i}_label" not in content:
                    content[f"stat_{i}_label"] = stat.get("label", "")
                if f"stat_{i}_detail" not in content:
                    content[f"stat_{i}_detail"] = stat.get("detail", "")

    # Feature individual tokens (for bento template)
    for i in range(1, 6):
        icon_raw = content.get(f"feature_{i}_icon", "star")
        subs[f"{{{{FEATURE_{i}_ICON}}}}"] = _validate_lucide_icon(str(icon_raw)) if re.match(r'^[a-z][a-z0-9-]+$', str(icon_raw)) else _safe_str(icon_raw)
        subs[f"{{{{FEATURE_{i}_TITLE}}}}"] = _safe_str(content.get(f"feature_{i}_title", ""))
        subs[f"{{{{FEATURE_{i}_DESC}}}}"] = _safe_str(content.get(f"feature_{i}_desc", ""))
        subs[f"{{{{FEATURE_{i}_QUOTE}}}}"] = _safe_str(content.get(f"feature_{i}_quote", ""))
        subs[f"{{{{FEATURE_{i}_STAT}}}}"] = _safe_str(content.get(f"feature_{i}_stat", "100"))
        subs[f"{{{{FEATURE_{i}_STAT_LABEL}}}}"] = _safe_str(content.get(f"feature_{i}_stat_label", ""))
    # Stats individual tokens (for stats bar template)
    for i in range(1, 5):
        subs[f"{{{{STAT_{i}_VALUE}}}}"] = _safe_str(content.get(f"stat_{i}_value", "0"))
        subs[f"{{{{STAT_{i}_LABEL}}}}"] = _safe_str(content.get(f"stat_{i}_label", ""))
        subs[f"{{{{STAT_{i}_DETAIL}}}}"] = _safe_str(content.get(f"stat_{i}_detail", ""))
    subs["{{TRUST_BADGE_1}}"] = _safe_str(content.get("trust_badge_1", "Проверено временем"))
    subs["{{TRUST_BADGE_2}}"] = _safe_str(content.get("trust_badge_2", "Быстрый результат"))
    subs["{{TRUST_BADGE_3}}"] = _safe_str(content.get("trust_badge_3", "Высший рейтинг"))

    # Complex content tokens — rendered HTML
    surface_class = bundle.get("surface_class", "rounded-2xl border border-black/5 bg-white")
    heading_class = bundle.get("heading_class", "font-sans font-bold")
    muted_class = bundle.get("theme_pack").muted if bundle.get("theme_pack") else "text-gray-500"
    accent_bg = bundle.get("theme_pack").accent_bg if bundle.get("theme_pack") else "bg-blue-600"
    icon_class = bundle.get("icon_class", "w-5 h-5")

    features = content.get("features", [])
    subs["{{FEATURES_HTML}}"] = _render_features_html(features, surface_class, icon_class) if features else ""

    stats = content.get("stats", [])
    subs["{{STATS_HTML}}"] = _render_stats_html(stats, heading_class, muted_class) if stats else ""

    testimonials = content.get("testimonials", [])
    subs["{{TESTIMONIALS_HTML}}"] = _render_testimonials_html(testimonials, surface_class) if testimonials else ""

    facts = content.get("facts", [])
    subs["{{FACTS_HTML}}"] = _render_facts_html(facts, heading_class, muted_class) if facts else ""

    cases = content.get("cases", [])
    subs["{{CASES_HTML}}"] = _render_cases_html(cases, surface_class) if cases else ""

    steps = content.get("steps", [])
    subs["{{STEPS_HTML}}"] = _render_steps_html(steps, accent_bg) if steps else ""

    before_items = content.get("before_items", [])
    after_items = content.get("after_items", [])
    subs["{{COMPARISON_HTML}}"] = _render_comparison_html(before_items, after_items) if before_items else ""

    social_links = content.get("social_links", [])
    subs["{{SOCIAL_LINKS_HTML}}"] = _render_footer_links(social_links) if social_links else ""

    # Gallery items
    gallery_items = content.get("gallery", content.get("gallery_items", []))
    subs["{{GALLERY_HTML}}"] = _render_gallery_html(gallery_items, surface_class) if gallery_items else ""

    # Pricing items
    pricing_items = content.get("pricing", content.get("pricing_items", []))
    subs["{{PRICING_HTML}}"] = _render_pricing_html(pricing_items, surface_class, accent_bg, bundle.get("button_class", "")) if pricing_items else ""

    # About features (small highlights)
    about_features = content.get("about_features", [])
    accent_class_str = bundle.get("theme_pack").accent if bundle.get("theme_pack") else "text-blue-600"
    subs["{{ABOUT_FEATURES_HTML}}"] = _render_about_features_html(about_features, accent_class_str) if about_features else ""

    # Footer navigation (P1-FIX #2: dynamic footer nav)
    subs["{{FOOTER_NAV_HTML}}"] = ""  # Will be set by assemble_page if needed

    # Apply substitutions
    result = template
    for key, value in subs.items():
        result = result.replace(key, value)

    # P1-FIX #3: Deduplicate CSS classes in the rendered HTML
    result = _dedupe_html_classes(result)
    # P4-FIX: Final sweep — remove any unresolved {{PLACEHOLDER}} slots
    result = re.sub(r'\{\{[A-Z0-9_]+\}\}', '', result)

    return result


# ─────────────────────────────────────────────────────────────────
#  PAGE ASSEMBLER
# ─────────────────────────────────────────────────────────────────

PAGE_WRAPPER_START = """<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>
  <style>
    :root {{
      --font-heading: 'DM Sans', 'Inter', sans-serif;
      --font-body: 'Inter', sans-serif;
      --font-serif: 'Playfair Display', Georgia, serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; font-family: var(--font-body); -webkit-font-smoothing: antialiased; }}
    .font-serif {{ font-family: var(--font-serif) !important; }}
    .font-sans {{ font-family: var(--font-heading) !important; }}
    .font-mono {{ font-family: 'JetBrains Mono', 'Fira Code', monospace !important; }}
    
    /* Reveal animations — handled by GSAP, CSS is fallback only */
    .no-js .reveal-on-scroll {{ opacity: 0; transform: translateY(24px); transition: opacity 0.6s ease, transform 0.6s ease; }}
    .no-js .reveal-on-scroll.revealed {{ opacity: 1; transform: translateY(0); }}
    .hover-lift {{ transition: transform 0.2s ease, box-shadow 0.2s ease; }}
    .hover-lift:hover {{ transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,0,0,0.12); }}
    
    /* Marquee animation */
    @keyframes marquee {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
    .marquee-track {{ animation: marquee 30s linear infinite; }}
    .marquee-track:hover {{ animation-play-state: paused; }}
    
    /* Gradient orbs */
    .gradient-orb {{ position: absolute; border-radius: 50%; filter: blur(80px); opacity: 0.3; pointer-events: none; }}
    
    /* Grain texture */
    .grain-overlay::after {{
      content: '';
      position: absolute;
      inset: 0;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
      pointer-events: none;
      z-index: 1;
    }}
    
    /* Sticky nav */
    .nav-sticky {{ position: sticky; top: 0; z-index: 50; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }}
    
    /* ═══ PREMIUM WOW EFFECTS ═══ */
    
    /* Smooth scroll via Lenis-like CSS */
    html {{ scroll-behavior: smooth; }}
    html.lenis, html.lenis body {{ height: auto; }}
    .lenis.lenis-smooth {{ scroll-behavior: auto; }}
    .lenis.lenis-smooth [data-lenis-prevent] {{ overscroll-behavior: contain; }}
    
    /* Custom cursor */
    .custom-cursor {{ position: fixed; width: 20px; height: 20px; border: 2px solid currentColor; border-radius: 50%; pointer-events: none; z-index: 9999; transition: transform 0.15s ease, opacity 0.15s ease; mix-blend-mode: difference; color: white; }}
    .custom-cursor.hover {{ transform: scale(2.5); opacity: 0.5; }}
    
    /* Text split animation */
    .split-text .char {{ display: inline-block; opacity: 0; transform: translateY(40px) rotate(5deg); }}
    
    /* Image reveal with clip-path */
    .img-reveal {{ clip-path: inset(100% 0 0 0); transition: clip-path 1s cubic-bezier(0.77, 0, 0.175, 1); }}
    .img-reveal.revealed {{ clip-path: inset(0 0 0 0); }}
    
    /* Magnetic button */
    .magnetic-btn {{ position: relative; transition: transform 0.3s cubic-bezier(0.23, 1, 0.32, 1); }}
    .magnetic-btn:hover {{ transform: scale(1.05); }}
    
    /* 3D tilt card */
    .tilt-card {{ transform-style: preserve-3d; transition: transform 0.5s ease; }}
    .tilt-card:hover {{ transform: perspective(1000px) rotateX(2deg) rotateY(-2deg) translateZ(10px); }}
    
    /* Gradient text */
    .gradient-text {{ background: linear-gradient(135deg, var(--accent-1, #6366f1), var(--accent-2, #a855f7), var(--accent-3, #ec4899)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }}
    
    /* Glow effect */
    .glow {{ box-shadow: 0 0 20px rgba(99, 102, 241, 0.3), 0 0 60px rgba(99, 102, 241, 0.1); }}
    .glow:hover {{ box-shadow: 0 0 30px rgba(99, 102, 241, 0.5), 0 0 80px rgba(99, 102, 241, 0.2); }}
    
    /* Floating animation */
    @keyframes float {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-10px); }} }}
    .float {{ animation: float 3s ease-in-out infinite; }}
    
    /* Pulse ring */
    @keyframes pulse-ring {{ 0% {{ transform: scale(0.8); opacity: 1; }} 100% {{ transform: scale(2); opacity: 0; }} }}
    .pulse-ring::before {{ content: ''; position: absolute; inset: -4px; border-radius: inherit; border: 2px solid currentColor; animation: pulse-ring 2s ease-out infinite; }}
    
    /* Scroll progress bar */
    .scroll-progress {{ position: fixed; top: 0; left: 0; height: 3px; background: linear-gradient(90deg, var(--accent-1, #6366f1), var(--accent-2, #a855f7)); z-index: 9999; transform-origin: left; transform: scaleX(0); }}
    
    /* Horizontal scroll section */
    .horizontal-scroll {{ display: flex; flex-wrap: nowrap; gap: 2rem; overflow-x: auto; scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch; scrollbar-width: none; }}
    .horizontal-scroll::-webkit-scrollbar {{ display: none; }}
    .horizontal-scroll > * {{ scroll-snap-align: start; flex-shrink: 0; }}
    
    /* Glass card */
    .glass {{ background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); }}
    
    /* Shimmer loading */
    @keyframes shimmer {{ 0% {{ background-position: -200% 0; }} 100% {{ background-position: 200% 0; }} }}
    .shimmer {{ background: linear-gradient(90deg, transparent 25%, rgba(255,255,255,0.1) 50%, transparent 75%); background-size: 200% 100%; animation: shimmer 2s infinite; }}
  </style>
</head>
<body class="{body_class}">

<!-- NAVIGATION -->
<nav class="nav-sticky {nav_bg} {border_class} border-b">
  <div class="{container_class} px-5 md:px-8 mx-auto flex items-center justify-between h-16">
    <a href="#" class="{text_class} font-bold text-lg tracking-tight">{brand_name}</a>
    <div class="hidden md:flex items-center gap-8">
      {nav_links_html}
    </div>
    <a href="{cta_href}" class="{button_class} text-sm">{cta_text}</a>
  </div>
</nav>

"""

PAGE_WRAPPER_END = """
<!-- GSAP ScrollTrigger + Reveal Script -->
<script>
(function() {
  // Remove no-js class (used for CSS-only fallback)
  document.documentElement.classList.remove('no-js');

  // Init Lucide icons
  if (typeof lucide !== 'undefined') lucide.createIcons();

  // Register GSAP plugins
  if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') {
    // GSAP not loaded — use CSS fallback
    document.documentElement.classList.add('no-js');
    document.querySelectorAll('.reveal-on-scroll').forEach(el => el.classList.add('revealed'));
    return;
  }
  gsap.registerPlugin(ScrollTrigger);

  // Reveal inner elements with reveal-on-scroll class
  document.querySelectorAll('.reveal-on-scroll').forEach((el, i) => {
    gsap.from(el, {
      opacity: 0, y: 30, duration: 0.7, delay: i * 0.05,
      ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 90%', toggleActions: 'play none none none' }
    });
  });

  // Stagger cards within grids
  document.querySelectorAll('.grid, .flex.flex-wrap').forEach(grid => {
    const cards = grid.querySelectorAll(':scope > div, :scope > article');
    if (cards.length > 1) {
      gsap.from(cards, {
        opacity: 0, y: 30, duration: 0.6, stagger: 0.12, ease: 'power2.out',
        scrollTrigger: { trigger: grid, start: 'top 88%' }
      });
    }
  });

  // Animated counters (data-counter=\"340\")
  document.querySelectorAll('[data-counter]').forEach(el => {
    const raw = el.dataset.counter;
    const target = parseInt(raw);
    if (isNaN(target)) { el.textContent = raw; return; }
    const suffix = raw.replace(/[0-9,. ]+/, '');
    el.textContent = '0';
    ScrollTrigger.create({
      trigger: el, start: 'top 90%',
      onEnter: () => {
        gsap.to({val: 0}, {
          val: target, duration: 2, ease: 'power2.out',
          onUpdate: function() {
            el.textContent = Math.round(this.targets()[0].val).toLocaleString('ru-RU') + suffix;
          }
        });
      }, once: true
    });
  });

  // Parallax hero backgrounds
  document.querySelectorAll('[data-parallax]').forEach(el => {
    gsap.to(el, {
      yPercent: 20, ease: 'none',
      scrollTrigger: { trigger: el, start: 'top top', end: 'bottom top', scrub: true }
    });
  });

  // ═══ PREMIUM WOW EFFECTS ═══

  // 1. Custom cursor (desktop only)
  if (window.innerWidth > 768) {
    const cursor = document.createElement('div');
    cursor.className = 'custom-cursor';
    document.body.appendChild(cursor);
    document.addEventListener('mousemove', e => {
      cursor.style.left = e.clientX - 10 + 'px';
      cursor.style.top = e.clientY - 10 + 'px';
    });
    document.querySelectorAll('a, button, [role=button], .hover-lift, .tilt-card').forEach(el => {
      el.addEventListener('mouseenter', () => cursor.classList.add('hover'));
      el.addEventListener('mouseleave', () => cursor.classList.remove('hover'));
    });
  }

  // 2. Text split animation for hero headings
  document.querySelectorAll('.split-text, h1').forEach(heading => {
    if (heading.classList.contains('split-done')) return;
    heading.classList.add('split-done');
    const text = heading.textContent;
    heading.innerHTML = '';
    text.split('').forEach((char, i) => {
      const span = document.createElement('span');
      span.className = 'char';
      span.textContent = char === ' ' ? '\u00A0' : char;
      span.style.display = 'inline-block';
      heading.appendChild(span);
    });
    gsap.to(heading.querySelectorAll('.char'), {
      opacity: 1, y: 0, rotation: 0, duration: 0.6, stagger: 0.02, ease: 'power3.out',
      scrollTrigger: { trigger: heading, start: 'top 85%' }
    });
  });

  // 3. Image reveal with clip-path
  document.querySelectorAll('.img-reveal, section img').forEach(img => {
    if (img.closest('nav')) return;
    gsap.fromTo(img, 
      { clipPath: 'inset(100% 0 0 0)' },
      { clipPath: 'inset(0% 0 0 0)', duration: 1.2, ease: 'power4.out',
        scrollTrigger: { trigger: img, start: 'top 90%' }
      }
    );
  });

  // 4. Magnetic buttons
  document.querySelectorAll('.magnetic-btn, a[class*="rounded"][class*="px"]').forEach(btn => {
    btn.addEventListener('mousemove', e => {
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      btn.style.transform = `translate(${x * 0.2}px, ${y * 0.2}px) scale(1.05)`;
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = '';
    });
  });

  // 5. Scroll progress bar
  const progressBar = document.createElement('div');
  progressBar.className = 'scroll-progress';
  document.body.appendChild(progressBar);
  gsap.to(progressBar, {
    scaleX: 1, ease: 'none',
    scrollTrigger: { trigger: document.body, start: 'top top', end: 'bottom bottom', scrub: true }
  });

  // 6. 3D tilt on cards
  document.querySelectorAll('.tilt-card, .hover-lift').forEach(card => {
    card.addEventListener('mousemove', e => {
      const rect = card.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = `perspective(1000px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg) translateZ(10px)`;
    });
    card.addEventListener('mouseleave', () => {
      card.style.transform = '';
    });
  });

  // 7. Smooth nav background on scroll
  const nav = document.querySelector('nav');
  if (nav) {
    ScrollTrigger.create({
      start: 'top -80',
      onUpdate: self => {
        if (self.direction === 1) nav.style.boxShadow = '0 4px 30px rgba(0,0,0,0.1)';
        else nav.style.boxShadow = 'none';
      }
    });
  }

  // 8. Floating gradient orbs animation
  document.querySelectorAll('.gradient-orb').forEach((orb, i) => {
    gsap.to(orb, {
      x: `random(-50, 50)`, y: `random(-30, 30)`,
      duration: `random(4, 8)`, ease: 'sine.inOut',
      repeat: -1, yoyo: true, delay: i * 0.5
    });
  });

})();
</script>
</body>
</html>"""



# ─────────────────────────────────────────────────────────────────
#  BLUEPRINT-BASED ASSEMBLY (Day 1.5)
#  Instead of assembling from 19 small scene templates,
#  load a master blueprint (444-698 lines) and fill {{PLACEHOLDERS}} via LLM.
# ─────────────────────────────────────────────────────────────────

BLUEPRINT_FILL_PROMPT = """You are a professional copywriter. Given a client brief and a list of placeholder variables, generate the content for each placeholder.

CLIENT BRIEF:
{user_brief}

NICHE: {niche}
LANGUAGE: {lang}

PLACEHOLDERS TO FILL (return JSON object with these exact keys):
{placeholder_list}

RULES:
1. All text MUST be in {lang} language (Russian if "ru")
2. {{BRAND_NAME}} — extract from brief or invent a fitting name
3. {{HERO_TITLE}} — compelling headline, max 8 words
3a. {{HERO_TITLE_LINE1}} — first line of hero title (2-4 words)
3b. {{HERO_TITLE_LINE2}} — second line of hero title (2-4 words, accent/highlight)
3c. {{HERO_TITLE_BEFORE}}, {{HERO_TITLE_HIGHLIGHT}}, {{HERO_TITLE_AFTER}} — three parts of hero title if template uses them
4. {{HERO_DESCRIPTION}} — 1-2 sentences, persuasive
5. {{PHONE}} — use from brief or "+7 (999) 123-45-67"
6. {{ADDRESS}} — use from brief or invent realistic address
7. {{HOURS}} — use from brief or "Пн-Пт: 9:00-21:00"
8. For {{SERVICE_CARDS}} — return HTML: 3-4 <div> cards with service name, description, price
9. For {{TESTIMONIAL_CARDS}} — return HTML: 2-3 <div> cards with name, text, rating
10. For {{GALLERY_ITEMS}} — return HTML: 4-6 <div> items with image placeholders
11. For {{MARQUEE_ITEMS}} — return HTML: 5-8 <span> items for scrolling marquee
12. For image URLs ({{HERO_IMAGE_URL}}, {{ABOUT_IMAGE_URL}}) — return "https://images.pexels.com/photos/1640777/pexels-photo-1640777.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750" (will be replaced with real images later)
13. For {{LANG}} — return "{lang_code}"
14. Keep all content professional, specific to the niche, and persuasive
15. DO NOT use markdown. Return pure text or HTML as appropriate for each field.

Return ONLY a valid JSON object. No markdown, no code blocks, no explanation."""

async def _fill_blueprint_placeholders(
    blueprint_html: str,
    user_brief: str,
    niche: str,
    llm_client,
    lang: str = "ru",
) -> str:
    """
    Fill {{PLACEHOLDER}} variables in a blueprint using LLM.
    Returns the filled HTML string.
    """
    import json as _json
    import os
    
    # Extract all unique placeholders from the blueprint
    # Handle both {{KEY}} and {{KEY|default}} syntax
    all_matches = re.findall(r'\{\{([A-Z_0-9]+)(?:\|[^}]*)?\}\}', blueprint_html)
    placeholders = sorted(set(all_matches))
    if not placeholders:
        logger.warning("No placeholders found in blueprint")
        return blueprint_html
    
    logger.info(f"Blueprint has {len(placeholders)} unique placeholders: {placeholders}")
    
    placeholder_list = "\n".join(f"- {{{{{p}}}}}: <description>" for p in placeholders)
    lang_code = "ru" if lang == "ru" else "en"
    
    prompt = BLUEPRINT_FILL_PROMPT.format(
        user_brief=user_brief[:2000],
        niche=niche,
        lang="Russian" if lang == "ru" else "English",
        lang_code=lang_code,
        placeholder_list=placeholder_list,
    )
    
    try:
        # Use LLM to generate content for all placeholders
        from shared.models.schemas import LLMRequest
        from shared.llm.client import LLMResponse
        request = LLMRequest(
            model_id="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a JSON-only content generator. Return ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        response = await llm_client.complete(request, role="blueprint_fill", worker="scene_assembler")
        
        raw_content = response.content if isinstance(response, LLMResponse) else str(response)
        
        # Clean up response — remove markdown code blocks if present
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            raw_content = re.sub(r'^```(?:json)?\n?', '', raw_content)
            raw_content = re.sub(r'\n?```$', '', raw_content)
        
        content_map = _json.loads(raw_content)
        logger.info(f"LLM returned {len(content_map)} placeholder values")
        
    except Exception as e:
        logger.error(f"Blueprint LLM fill failed: {e}, using fallback content")
        content_map = _generate_blueprint_fallback(niche, user_brief, lang)
    
    # Post-process: derive missing multi-part hero title keys from HERO_TITLE
    if "HERO_TITLE" in content_map:
        hero_title = content_map["HERO_TITLE"]
        words = hero_title.split()
        mid = len(words) // 2
        if "HERO_TITLE_LINE1" not in content_map:
            content_map["HERO_TITLE_LINE1"] = " ".join(words[:mid]) if mid > 0 else hero_title
        if "HERO_TITLE_LINE2" not in content_map:
            content_map["HERO_TITLE_LINE2"] = " ".join(words[mid:]) if mid > 0 else ""
        if "HERO_TITLE_BEFORE" not in content_map:
            content_map["HERO_TITLE_BEFORE"] = " ".join(words[:1]) if len(words) > 2 else ""
        if "HERO_TITLE_HIGHLIGHT" not in content_map:
            content_map["HERO_TITLE_HIGHLIGHT"] = " ".join(words[1:3]) if len(words) > 2 else hero_title
        if "HERO_TITLE_AFTER" not in content_map:
            content_map["HERO_TITLE_AFTER"] = " ".join(words[3:]) if len(words) > 3 else ""

    # Replace placeholders in HTML (handle both {{KEY}} and {{KEY|default}} syntax)
    filled_html = blueprint_html
    for placeholder in placeholders:
        key = placeholder  # e.g. "BRAND_NAME"
        value = content_map.get(key, "")
        if not value:
            # Try with curly braces
            value = content_map.get(f"{{{{{key}}}}}", "")
        
        # Replace {{KEY|default}} first (with pipe defaults)
        # Use regex to match {{KEY|anything}} and replace with value or default
        import re as _re_inner
        pattern = r'\{\{' + _re_inner.escape(key) + r'\|([^}]*)\}\}'
        if value:
            filled_html = _re_inner.sub(pattern, lambda m: str(value), filled_html)
        else:
            # Use the default value from the pipe syntax
            filled_html = _re_inner.sub(pattern, r'\1', filled_html)
        
        # Then replace {{KEY}} (without pipe defaults)
        if value:
            filled_html = filled_html.replace(f"{{{{{key}}}}}", str(value))
        else:
            filled_html = filled_html.replace(f"{{{{{key}}}}}", f"[{key}]")
    
    # Fetch real images from Pexels for image placeholders
    if fetch_images_enabled:
        filled_html = await _replace_pexels_placeholders(filled_html, niche, user_brief)
    
    return filled_html


# Global flag for image fetching in blueprint mode
fetch_images_enabled = True


async def _replace_pexels_placeholders(html: str, niche: str, user_brief: str) -> str:
    """Replace Pexels placeholder URLs with AI-generated images (Nano Banana / Gemini Flash).
    
    Priority: AI generation (OpenRouter) → Unsplash curated fallback.
    """
    import os
    import re as _re

    # Full placeholder URL to replace
    full_placeholder = "https://images.pexels.com/photos/1640777/pexels-photo-1640777.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750"
    if full_placeholder not in html:
        return html

    count_total = html.count(full_placeholder)
    logger.info(f"Blueprint image replacement: {count_total} placeholders found for niche '{niche}'")

    # Generate niche-specific image prompts
    niche_prompts = {
        "restaurant": [
            "Elegant restaurant interior with warm ambient lighting, wooden tables, wine glasses, and soft candlelight. Professional food photography style.",
            "Beautiful gourmet dish on a white plate, artistically plated, restaurant setting with blurred background. Food photography.",
            "Cozy restaurant terrace with string lights, green plants, and elegant table settings at golden hour.",
            "Professional chef preparing food in a modern kitchen, dramatic lighting, culinary arts.",
            "Wine cellar with oak barrels and warm lighting, premium restaurant atmosphere.",
            "Close-up of fresh ingredients on a cutting board, herbs, vegetables, professional food styling.",
        ],
        "fitness": [
            "Modern gym interior with professional equipment, dramatic lighting, motivational atmosphere. Wide angle shot.",
            "Athletic person doing workout in a well-lit modern gym, dynamic pose, professional sports photography.",
            "Yoga class in a bright, minimalist studio with natural light streaming through large windows.",
            "Group fitness class with energetic participants, modern gym setting, vibrant atmosphere.",
            "Close-up of dumbbells and fitness equipment with dramatic lighting, gym aesthetic.",
            "Outdoor fitness training at sunrise, athletic silhouette, motivational sports photography.",
        ],
        "beauty": [
            "Luxury barbershop interior with leather chairs, warm wood paneling, vintage mirrors, and professional lighting.",
            "Professional barber giving a haircut, close-up, dramatic lighting, barbershop atmosphere.",
            "Beauty salon interior with modern minimalist design, clean lines, professional lighting.",
            "Hair styling tools arranged artistically on a marble surface, professional beauty photography.",
            "Elegant spa treatment room with candles, towels, and natural elements, relaxation atmosphere.",
            "Close-up of professional hair styling, salon setting, editorial beauty photography.",
        ],
        "medical": [
            "Modern dental clinic interior with state-of-the-art equipment, clean white design, professional medical setting.",
            "Friendly dentist consulting with a patient in a bright, modern clinic. Professional medical photography.",
            "Close-up of modern dental equipment in a clean, well-lit treatment room.",
            "Medical clinic reception area with modern design, comfortable seating, professional atmosphere.",
            "Team of medical professionals in white coats, confident and friendly, modern clinic background.",
            "Bright and clean medical examination room with modern equipment, professional healthcare setting.",
        ],
        "real_estate": [
            "Luxury modern apartment interior with panoramic city views, designer furniture, warm lighting.",
            "Beautiful modern house exterior with landscaped garden, architectural photography at golden hour.",
            "Spacious living room with floor-to-ceiling windows, contemporary design, natural light.",
            "Modern kitchen with marble countertops, stainless steel appliances, designer lighting.",
            "Penthouse terrace with city skyline view at sunset, luxury real estate photography.",
            "Elegant bedroom with premium bedding, soft lighting, contemporary interior design.",
        ],
        "legal": [
            "Professional law office with dark wood furniture, legal books, and warm lighting. Corporate photography.",
            "Modern conference room with glass walls, city view, professional business setting.",
            "Elegant office desk with legal documents, fountain pen, and scales of justice. Professional still life.",
            "Business professionals in a meeting, modern office, confident corporate atmosphere.",
        ],
        "saas": [
            "Modern tech office with large monitors showing dashboards, clean minimal design, professional workspace.",
            "Team of developers collaborating around a screen, modern startup office, natural lighting.",
            "Abstract technology visualization, data streams, futuristic digital interface, dark background.",
            "Clean laptop on a minimalist desk with a plant, modern workspace, productivity aesthetic.",
        ],
        "education": [
            "Modern university lecture hall with students, bright natural lighting, educational atmosphere.",
            "Library interior with bookshelves, reading areas, warm ambient lighting, academic setting.",
            "Students collaborating on a project in a modern classroom with technology, educational photography.",
            "Graduation ceremony with caps thrown in the air, celebratory moment, outdoor campus.",
        ],
        "hospitality": [
            "Luxury hotel lobby with grand chandelier, marble floors, elegant design, hospitality photography.",
            "Premium hotel room with ocean view, king bed, luxury amenities, warm lighting.",
            "Hotel infinity pool overlooking tropical landscape at sunset, luxury resort photography.",
            "Elegant hotel restaurant with fine dining setup, candlelight, premium hospitality.",
        ],
        "finance": [
            "Modern financial office with city skyline view, professional workspace, corporate photography.",
            "Business analytics dashboard on a large screen, modern office, data visualization.",
            "Professional handshake in a corporate setting, business partnership, confident atmosphere.",
        ],
    }

    prompts = niche_prompts.get(niche, [
        f"Professional {niche} business interior, modern design, warm lighting, high-end photography.",
        f"Team of {niche} professionals at work, modern office, confident and friendly atmosphere.",
        f"Close-up detail shot related to {niche} industry, professional photography, clean composition.",
        f"Modern {niche} workspace with premium design, natural lighting, professional atmosphere.",
    ])

    # Try AI image generation first
    generated_urls = []
    try:
        # Generate images in parallel (up to count_total, max 4)
        num_to_generate = min(count_total, len(prompts), 4)
        
        tasks = []
        for i in range(num_to_generate):
            prompt = prompts[i % len(prompts)]
            tasks.append(generate_ai_image(
                prompt,
                style="cinematic",
                project_dir="/root/workspace/generated_images"
            ))
        
        import asyncio
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for r in results:
            if isinstance(r, str) and r.startswith("http"):
                generated_urls.append(r)
            elif isinstance(r, Exception):
                logger.warning(f"AI image generation task failed: {r}")
        
        logger.info(f"AI image generation: {len(generated_urls)}/{num_to_generate} images generated successfully")
    except Exception as e:
        logger.warning(f"AI image generation batch failed: {e}")

    # Use generated images if we have any
    if generated_urls:
        for i, url in enumerate(generated_urls):
            if full_placeholder not in html:
                break
            html = html.replace(full_placeholder, url, 1)
        # Cycle through generated images for remaining placeholders
        idx = 0
        while full_placeholder in html and generated_urls:
            html = html.replace(full_placeholder, generated_urls[idx % len(generated_urls)], 1)
            idx += 1
        count_after = html.count(full_placeholder)
        logger.info(f"AI image replacement: {count_total - count_after} replaced with AI images, {count_after} remaining")
        return html

    # Fallback: Unsplash curated images
    logger.info("Falling back to Unsplash curated images")
    niche_images = {
        "restaurant": [
            "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1552566626-52f8b828add9?w=1200&h=800&fit=crop",
        ],
        "fitness": [
            "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1540497077202-7c8a3999166f?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?w=1200&h=800&fit=crop",
        ],
        "beauty": [
            "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1560066984-138dadb4c035?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1562322140-8baeececf3df?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1585747860715-2ba37e788b70?w=1200&h=800&fit=crop",
        ],
        "medical": [
            "https://images.unsplash.com/photo-1629909613654-28e377c37b09?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1588776814546-1ffcf47267a5?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?w=1200&h=800&fit=crop",
        ],
        "real_estate": [
            "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1200&h=800&fit=crop",
        ],
        "legal": [
            "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1505664194779-8beaceb93744?w=1200&h=800&fit=crop",
        ],
        "saas": [
            "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1551434678-e076c223a692?w=1200&h=800&fit=crop",
        ],
        "education": [
            "https://images.unsplash.com/photo-1523050854058-8df90110c476?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=1200&h=800&fit=crop",
        ],
        "hospitality": [
            "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=1200&h=800&fit=crop",
        ],
        "finance": [
            "https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=1200&h=800&fit=crop",
            "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1200&h=800&fit=crop",
        ],
    }

    images = niche_images.get(niche, [
        "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1200&h=800&fit=crop",
        "https://images.unsplash.com/photo-1497366811353-6870744d04b2?w=1200&h=800&fit=crop",
        "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?w=1200&h=800&fit=crop",
    ])

    for i, img_url in enumerate(images):
        if full_placeholder not in html:
            break
        html = html.replace(full_placeholder, img_url, 1)

    idx = 0
    while full_placeholder in html and images:
        html = html.replace(full_placeholder, images[idx % len(images)], 1)
        idx += 1

    count_after = html.count(full_placeholder)
    logger.info(f"Unsplash fallback: {count_total - count_after} replaced, {count_after} remaining (niche: {niche})")

    return html

def _generate_blueprint_fallback(niche: str, user_brief: str, lang: str) -> dict:
    """Generate fallback content when LLM fails."""
    # Extract brand name from brief
    import re as _re
    brand = "Brand"
    # Try to find quoted name in brief
    quoted = _re.findall(r'["\'«»]([^"\'«»]+)["\'«»]', user_brief)
    if quoted:
        brand = quoted[0]
    
    return {
        "BRAND_NAME": brand,
        "PAGE_TITLE": f"{brand} — Официальный сайт",
        "META_DESCRIPTION": f"{brand} — качественные услуги для вас",
        "HERO_TITLE": f"Добро пожаловать в {brand}",
        "HERO_DESCRIPTION": "Мы предлагаем лучшие решения для вашего бизнеса",
        "HERO_BADGE": "Лучший выбор",
        "HERO_IMAGE_URL": "https://images.pexels.com/photos/1640777/pexels-photo-1640777.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750",
        "HERO_IMAGE_ALT": brand,
        "CTA_PRIMARY": "Связаться",
        "CTA_SECONDARY": "Узнать больше",
        "CTA_TITLE": "Готовы начать?",
        "CTA_DESCRIPTION": "Свяжитесь с нами для бесплатной консультации",
        "CTA_PHONE_TEXT": "Позвонить",
        "ABOUT_TITLE": f"О компании {brand}",
        "ABOUT_TEXT": "Мы — команда профессионалов с многолетним опытом работы.",
        "ABOUT_LABEL": "О нас",
        "ABOUT_IMAGE_URL": "https://images.pexels.com/photos/1640777/pexels-photo-1640777.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750",
        "ABOUT_IMAGE_ALT": f"О {brand}",
        "SERVICES_TITLE": "Наши услуги",
        "SERVICES_LABEL": "Услуги",
        "SERVICE_CARDS": '<div class="service-card"><h3>Услуга 1</h3><p>Описание услуги</p></div>',
        "REVIEWS_TITLE": "Отзывы клиентов",
        "REVIEWS_LABEL": "Отзывы",
        "TESTIMONIAL_CARDS": '<div class="testimonial"><p>"Отличный сервис!"</p><span>— Клиент</span></div>',
        "GALLERY_ITEMS": "",
        "MARQUEE_ITEMS": f"<span>{brand}</span> <span>•</span> <span>Качество</span> <span>•</span>",
        "PHONE": "+7 (999) 123-45-67",
        "ADDRESS": "г. Москва, ул. Примерная, д. 1",
        "HOURS": "Пн-Пт: 9:00-21:00",
        "LABEL_PHONE": "Телефон",
        "LABEL_ADDRESS": "Адрес",
        "LABEL_HOURS": "Часы работы",
        "FOOTER_TEXT": f"© 2026 {brand}. Все права защищены.",
        "NAV_SERVICES": "Услуги",
        "NAV_ABOUT": "О нас",
        "NAV_REVIEWS": "Отзывы",
        "LANG": "ru" if lang == "ru" else "en",
    }


async def assemble_from_blueprint(
    page_plan: "PagePlan",
    *,
    fetch_images: bool = True,
    lang: str = "ru",
) -> str:
    """
    Assemble a complete HTML page from a master blueprint.
    Instead of combining 19 small templates, loads one 500+ line blueprint
    and fills {{PLACEHOLDERS}} via LLM.
    
    Returns the full HTML string, or empty string if blueprint not found.
    """
    import os
    global fetch_images_enabled
    fetch_images_enabled = fetch_images
    
    blueprint_name = page_plan.blueprint
    if not blueprint_name:
        return ""
    
    blueprint_path = f"/root/arcane/templates/blueprints/{blueprint_name}.html"
    if not os.path.exists(blueprint_path):
        logger.error(f"Blueprint not found: {blueprint_path}")
        return ""
    
    with open(blueprint_path, "r", encoding="utf-8") as f:
        blueprint_html = f.read()
    
    logger.info(f"Loaded blueprint '{blueprint_name}' ({len(blueprint_html)} chars, {blueprint_html.count(chr(10))} lines)")
    
    # Get LLM client from the page_plan meta
    llm_client = page_plan.meta.get("_llm_client")
    if not llm_client:
        logger.error("No LLM client in page_plan.meta, cannot fill placeholders")
        # Use fallback
        content_map = _generate_blueprint_fallback(page_plan.niche, page_plan.meta.get("user_brief", ""), lang)
        for key, value in content_map.items():
            blueprint_html = blueprint_html.replace(f"{{{{{key}}}}}", str(value))
        return blueprint_html
    
    # Fill placeholders via LLM
    filled_html = await _fill_blueprint_placeholders(
        blueprint_html,
        user_brief=page_plan.meta.get("user_brief", ""),
        niche=page_plan.niche,
        llm_client=llm_client,
        lang=lang,
    )
    
    logger.info(f"Blueprint assembly complete: {len(filled_html)} chars")
    return filled_html


async def assemble_page(
    page_plan: "PagePlan",  # type: ignore[name-defined]
    *,
    fetch_images: bool = True,
    lang: str = "ru",
) -> str:
    """
    Assemble a complete HTML page from a PagePlan.
    Returns the full HTML string.
    
    If page_plan has a blueprint set, tries blueprint-based assembly first.
    Falls back to scene-by-scene assembly if blueprint fails.
    """
    # ── TRY BLUEPRINT-BASED ASSEMBLY FIRST ──
    if page_plan.blueprint:
        logger.info(f"Attempting blueprint-based assembly: {page_plan.blueprint}")
        try:
            blueprint_html = await assemble_from_blueprint(
                page_plan,
                fetch_images=fetch_images,
                lang=lang,
            )
            if blueprint_html and len(blueprint_html) > 1000:
                logger.info(f"Blueprint assembly SUCCESS: {len(blueprint_html)} chars")
                return blueprint_html
            else:
                logger.warning(f"Blueprint assembly returned too short HTML ({len(blueprint_html)} chars), falling back to scene assembly")
        except Exception as e:
            logger.error(f"Blueprint assembly failed: {e}, falling back to scene assembly")
    
    from workers.component_retriever import get_template
    from shared.design.premium_scenes.modifier_enums import resolve_modifier_bundle

    # Determine page-level metadata from first hero scene
    first_hero = next((s for s in page_plan.scenes if s.scene_id.startswith("hero.")), None)
    page_title = ""
    page_description = ""
    brand_name = ""
    cta_href = "#contact"
    cta_text = "Связаться"

    if first_hero:
        page_title = first_hero.content.get("headline", "")
        page_description = first_hero.content.get("subheadline", "")
        cta_text = first_hero.content.get("cta_primary_text", "Связаться")
        cta_href = first_hero.content.get("cta_primary_href", "#contact")

    # Get footer brand name
    footer_scene = next((s for s in page_plan.scenes if s.scene_id.startswith("footer.")), None)
    if footer_scene:
        brand_name = footer_scene.content.get("brand_name", "")

    if not brand_name:
        brand_name = page_title.split(".")[0][:30] if page_title else "Brand"

    # Resolve global theme from first scene
    first_scene = page_plan.scenes[0] if page_plan.scenes else None
    global_bundle = resolve_modifier_bundle(first_scene.modifiers) if first_scene else {}
    theme = global_bundle.get("theme_pack")

    nav_bg = theme.surface if theme else "bg-white/90"
    border_class = theme.border if theme else "border-gray-200"
    text_class = theme.text if theme else "text-gray-900"
    body_class = theme.bg if theme else "bg-white"
    button_class = global_bundle.get("button_class", "inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors")
    container_class = global_bundle.get("container_class", "max-w-6xl")
    accent_class = theme.accent if theme else "text-blue-600"

    # P1-FIX #2: Build nav links from actual scenes (not hardcoded)
    scene_ids = [s.scene_id for s in sorted(page_plan.scenes, key=lambda s: s.order)]
    nav_links_html = _build_nav_links(scene_ids, text_class)

    # Build page start
    page_html = PAGE_WRAPPER_START.format(
        lang=lang,
        title=page_title or brand_name,
        description=page_description or "",
        body_class=body_class,
        nav_bg=nav_bg,
        border_class=border_class,
        text_class=text_class,
        container_class=container_class,
        brand_name=brand_name,
        nav_links_html=nav_links_html,
        cta_href=cta_href,
        cta_text=cta_text,
        button_class=button_class,
    )

    # Build footer nav HTML for footer template
    footer_nav_html = _build_footer_nav_html(scene_ids, text_class, accent_class)

    # Render each scene
    rendered_scenes = []
    _used_section_ids = set()  # P4-FIX: track used IDs to prevent duplicates
    all_warnings: list[str] = []

    for scene_spec in sorted(page_plan.scenes, key=lambda s: s.order):
        template = get_template(scene_spec.scene_id)
        if not template:
            logger.warning(f"Skipping scene {scene_spec.scene_id!r} — no template found")
            continue

        # P1-FIX #4: Validate and auto-fix scene before rendering
        fixed_modifiers, fixed_content, warnings = _validate_and_fix_scene(
            scene_spec.scene_id,
            scene_spec.modifiers,
            scene_spec.content,
            page_plan.niche_tags,
        )
        all_warnings.extend(warnings)

        bundle = resolve_modifier_bundle(fixed_modifiers)

        try:
            rendered = await render_scene(
                template,
                scene_id=scene_spec.scene_id,
                modifiers=fixed_modifiers,
                content=fixed_content,
                bundle=bundle,
                niche=page_plan.niche,
                fetch_images=fetch_images,
            )

            # P1-FIX #2: Inject section IDs for anchor navigation
            # P4-FIX: Pass used_ids to prevent duplicate IDs
            section_id = SCENE_TO_SECTION_ID.get(scene_spec.scene_id, "")
            rendered = _inject_section_id(rendered, section_id, _used_section_ids)

            # Replace footer nav placeholder if this is a footer scene
            if scene_spec.scene_id.startswith("footer."):
                # Replace hardcoded footer nav with dynamic one
                rendered = re.sub(
                    r'<nav class="flex flex-col gap-2">.*?</nav>',
                    f'<nav class="flex flex-col gap-2">\n{footer_nav_html}\n        </nav>',
                    rendered,
                    flags=re.DOTALL,
                )

            rendered_scenes.append(rendered)
        except Exception as e:
            logger.error(f"Failed to render scene {scene_spec.scene_id!r}: {e}")
            # Fallback: render a minimal placeholder
            section_id = SCENE_TO_SECTION_ID.get(scene_spec.scene_id, "")
            id_attr = f' id="{section_id}"' if section_id else ""
            rendered_scenes.append(
                f'<section class="py-16 text-center opacity-50"{id_attr}><p>Section: {scene_spec.scene_id}</p></section>'
            )

    if all_warnings:
        logger.info(f"Scene assembly completed with {len(all_warnings)} auto-fixes: {all_warnings}")

    page_html += "\n".join(rendered_scenes)
    page_html += PAGE_WRAPPER_END

    return page_html


# ─────────────────────────────────────────────────────────────────
#  AUTO-DEPLOY TO /var/www/demo/
# ─────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    import re as _re
    import unicodedata
    # Transliterate Cyrillic
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    result = ''
    for char in text.lower():
        result += translit_map.get(char, char)
    # Remove non-alphanumeric, replace spaces/underscores with hyphens
    result = _re.sub(r'[^a-z0-9\s-]', '', result)
    result = _re.sub(r'[\s_]+', '-', result.strip())
    result = _re.sub(r'-+', '-', result)
    return result[:50].strip('-') or 'landing'


async def auto_deploy(
    html: str,
    project_name: str,
    *,
    deploy_dir: str = "/var/www/demo",
    domain: str = "arcaneai.ru",
) -> dict:
    """
    Auto-deploy generated HTML to a web-accessible directory.
    Returns dict with 'url', 'path', 'slug'.
    """
    import os
    import shutil
    
    slug = _slugify(project_name)
    target_dir = os.path.join(deploy_dir, slug)
    os.makedirs(target_dir, exist_ok=True)
    
    # Write HTML
    html_path = os.path.join(target_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    # Copy any generated images from /root/workspace/images/ to the deploy dir  # P4-FIX BUG-005
    img_src = "/root/workspace/images"  # P4-FIX BUG-005
    img_dst = os.path.join(deploy_dir, "images")
    if os.path.exists(img_src):
        os.makedirs(img_dst, exist_ok=True)
        for fname in os.listdir(img_src):
            src_file = os.path.join(img_src, fname)
            dst_file = os.path.join(img_dst, fname)
            if os.path.isfile(src_file) and not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)
    
    public_url = f"https://{domain}/demo/{slug}/"
    logger.info(f"Auto-deployed landing to {public_url} ({html_path})")
    
    return {
        "url": public_url,
        "path": html_path,
        "slug": slug,
    }
