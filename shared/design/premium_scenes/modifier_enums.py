"""
ARCANE Premium Scenes — Modifier Enums & Token Registry
shared/design/premium_scenes/modifier_enums.py

Все разрешённые значения модификаторов для Scene-Driven Code-RAG pipeline.
LLM может использовать ТОЛЬКО значения из этих enum'ов — никаких произвольных Tailwind-классов.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


# ─────────────────────────────────────────────────────────────────
#  ENUMS
# ─────────────────────────────────────────────────────────────────

class ThemePack(str, Enum):
    LIGHT_TRUST_V1 = "light_trust_v1"
    DARK_PREMIUM_V1 = "dark_premium_v1"
    WARM_EDITORIAL_V1 = "warm_editorial_v1"
    NEUTRAL_MINIMAL_V1 = "neutral_minimal_v1"
    DARK_TECH_V1 = "dark_tech_v1"
    WARM_GOLD_V1 = "warm_gold_v1"
    DARK_ELEGANT_V1 = "dark_elegant_v1"


class HeadingMode(str, Enum):
    SERIF_CLASSIC = "serif_classic"
    SANS_EXECUTIVE = "sans_executive"
    DISPLAY_BOLD = "display_bold"
    MONO_TECH = "mono_tech"


class BodyMode(str, Enum):
    BODY_CLEAN = "body_clean"
    BODY_COMPACT = "body_compact"
    BODY_EDITORIAL = "body_editorial"


class MediaStyle(str, Enum):
    PORTRAIT_EDITORIAL = "portrait_editorial"
    RECT_SOFT = "rect_soft"
    FULLBLEED = "fullbleed"
    SQUARE_CROP = "square_crop"
    NONE = "none"


class ButtonStyle(str, Enum):
    FILLED_ACCENT = "filled_accent"
    OUTLINE_CLEAN = "outline_clean"
    GHOST_MINIMAL = "ghost_minimal"
    PILL_ACCENT = "pill_accent"


class DecoratorMode(str, Enum):
    NONE = "none"
    GRID_FAINT = "grid_faint"
    GRAIN_SOFT = "grain_soft"
    LINE_DIVIDER = "line_divider"
    GRADIENT_ORBS = "gradient_orbs"


class TrustMode(str, Enum):
    NONE = "none"
    AUTHORITY_FACTS = "authority_facts"
    SOCIAL_PROOF_LIGHT = "social_proof_light"
    DISCREET_ASSURANCE = "discreet_assurance"
    LEGAL_PRECISION = "legal_precision"


class SpacingMode(str, Enum):
    COMPACT_TRUST = "compact_trust"
    BALANCED_EXEC = "balanced_exec"
    AIRY_EDITORIAL = "airy_editorial"


class MotionProfile(str, Enum):
    MOTION_OFF = "motion_off"
    MOTION_MINIMAL = "motion_minimal"
    MOTION_SUBTLE = "motion_subtle"


class ContainerMode(str, Enum):
    CONTAINER_WIDE = "container_wide"
    CONTAINER_STANDARD = "container_standard"
    CONTAINER_NARROW = "container_narrow"


class SurfaceStyle(str, Enum):
    SURFACE_SOFT = "surface_soft"
    SURFACE_CLEAN = "surface_clean"
    SURFACE_DARK = "surface_dark"
    SURFACE_ACCENT = "surface_accent"


class AccentCardMode(str, Enum):
    ACCENT_FILL = "accent_fill"
    ACCENT_OUTLINE = "accent_outline"
    ACCENT_GLOW_SOFT = "accent_glow_soft"


class DividerStyle(str, Enum):
    LINE_SOFT = "line_soft"
    LINE_STRICT = "line_strict"
    LINE_NONE = "line_none"


class IconStyle(str, Enum):
    ICON_MINIMAL = "icon_minimal"
    ICON_OUTLINE = "icon_outline"
    ICON_NONE = "icon_none"


# ─────────────────────────────────────────────────────────────────
#  DATACLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ThemeDef:
    bg: str
    surface: str
    text: str
    muted: str
    accent: str
    accent_bg: str
    border: str
    name: str


@dataclass(slots=True)
class SpacingDef:
    section: str
    gap: str
    container: str


@dataclass(slots=True)
class MotionDef:
    reveal: bool
    hover: bool
    parallax: bool


# ─────────────────────────────────────────────────────────────────
#  THEME PACKS
# ─────────────────────────────────────────────────────────────────

THEME_PACKS: dict[str, ThemeDef] = {
    ThemePack.LIGHT_TRUST_V1.value: ThemeDef(
        bg="bg-white",
        surface="bg-gray-50",
        text="text-gray-900",
        muted="text-gray-500",
        accent="text-blue-600",
        accent_bg="bg-blue-600",
        border="border-gray-200",
        name="light_trust_v1",
    ),
    ThemePack.DARK_PREMIUM_V1.value: ThemeDef(
        bg="bg-gray-950",
        surface="bg-gray-900",
        text="text-white",
        muted="text-gray-400",
        accent="text-violet-400",
        accent_bg="bg-violet-600",
        border="border-white/10",
        name="dark_premium_v1",
    ),
    ThemePack.WARM_EDITORIAL_V1.value: ThemeDef(
        bg="bg-stone-50",
        surface="bg-stone-100",
        text="text-stone-900",
        muted="text-stone-500",
        accent="text-amber-600",
        accent_bg="bg-amber-600",
        border="border-stone-200",
        name="warm_editorial_v1",
    ),
    ThemePack.NEUTRAL_MINIMAL_V1.value: ThemeDef(
        bg="bg-neutral-50",
        surface="bg-white",
        text="text-neutral-900",
        muted="text-neutral-500",
        accent="text-neutral-800",
        accent_bg="bg-neutral-900",
        border="border-neutral-200",
        name="neutral_minimal_v1",
    ),
    ThemePack.DARK_TECH_V1.value: ThemeDef(
        bg="bg-slate-950",
        surface="bg-slate-900",
        text="text-slate-50",
        muted="text-slate-400",
        accent="text-cyan-400",
        accent_bg="bg-cyan-500",
        border="border-slate-700",
        name="dark_tech_v1",
    ),
    ThemePack.WARM_GOLD_V1.value: ThemeDef(
        bg="bg-[#F5F0E8]",
        surface="bg-[#EDE7DB]",
        text="text-[#2A2118]",
        muted="text-[#8B7D6B]",
        accent="text-[#C8A96E]",
        accent_bg="bg-[#C8A96E]",
        border="border-[#D4C9B8]",
        name="warm_gold_v1",
    ),
    ThemePack.DARK_ELEGANT_V1.value: ThemeDef(
        bg="bg-[#1A1A1A]",
        surface="bg-[#242424]",
        text="text-[#F5F0E8]",
        muted="text-[#8B8B8B]",
        accent="text-[#C8A96E]",
        accent_bg="bg-[#C8A96E]",
        border="border-[#333333]",
        name="dark_elegant_v1",
    ),
}

# ─────────────────────────────────────────────────────────────────
#  CSS CLASS MAPS
# ─────────────────────────────────────────────────────────────────

HEADING_MODE_CLASSES: dict[str, str] = {
    HeadingMode.SERIF_CLASSIC.value: "font-serif font-semibold tracking-tight",
    HeadingMode.SANS_EXECUTIVE.value: "font-sans font-bold tracking-tight",
    HeadingMode.DISPLAY_BOLD.value: "font-sans font-black tracking-tighter",
    HeadingMode.MONO_TECH.value: "font-mono font-bold tracking-tight",
}

BODY_MODE_CLASSES: dict[str, str] = {
    BodyMode.BODY_CLEAN.value: "font-sans font-normal leading-relaxed",
    BodyMode.BODY_COMPACT.value: "font-sans font-normal leading-snug",
    BodyMode.BODY_EDITORIAL.value: "font-serif font-normal leading-loose",
}

MEDIA_STYLE_CLASSES: dict[str, str] = {
    MediaStyle.PORTRAIT_EDITORIAL.value: "rounded-2xl object-cover aspect-[3/4]",
    MediaStyle.RECT_SOFT.value: "rounded-2xl object-cover aspect-video",
    MediaStyle.FULLBLEED.value: "w-full h-full object-cover",
    MediaStyle.SQUARE_CROP.value: "rounded-2xl object-cover aspect-square",
    MediaStyle.NONE.value: "",
}

BUTTON_STYLE_CLASSES: dict[str, str] = {
    ButtonStyle.FILLED_ACCENT.value: "inline-flex items-center justify-center rounded-xl px-6 py-3 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors",
    ButtonStyle.OUTLINE_CLEAN.value: "inline-flex items-center justify-center rounded-xl px-6 py-3 text-sm font-semibold border border-current hover:bg-black/5 transition-colors",
    ButtonStyle.GHOST_MINIMAL.value: "inline-flex items-center justify-center rounded-lg px-5 py-2.5 text-sm font-medium hover:underline transition-colors",
    ButtonStyle.PILL_ACCENT.value: "inline-flex items-center justify-center rounded-full px-7 py-3 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25",
}

DECORATOR_PARTIALS: dict[str, str] = {
    DecoratorMode.NONE.value: "",
    DecoratorMode.GRID_FAINT.value: "partials/decorators/grid_faint.html",
    DecoratorMode.GRAIN_SOFT.value: "partials/decorators/grain_soft.html",
    DecoratorMode.LINE_DIVIDER.value: "partials/decorators/line_divider.html",
    DecoratorMode.GRADIENT_ORBS.value: "partials/decorators/gradient_orbs.html",
}

TRUST_MODE_RENDERERS: dict[str, str] = {
    TrustMode.NONE.value: "",
    TrustMode.AUTHORITY_FACTS.value: "render_authority_facts_strip",
    TrustMode.SOCIAL_PROOF_LIGHT.value: "render_social_proof_light",
    TrustMode.DISCREET_ASSURANCE.value: "render_discreet_assurance_block",
    TrustMode.LEGAL_PRECISION.value: "render_legal_precision_notes",
}

SPACING_PRESETS: dict[str, SpacingDef] = {
    SpacingMode.COMPACT_TRUST.value: SpacingDef(
        section="py-12 md:py-16",
        gap="gap-4 md:gap-6",
        container="max-w-5xl px-4 md:px-6",
    ),
    SpacingMode.BALANCED_EXEC.value: SpacingDef(
        section="py-16 md:py-24",
        gap="gap-6 md:gap-10",
        container="max-w-6xl px-5 md:px-8",
    ),
    SpacingMode.AIRY_EDITORIAL.value: SpacingDef(
        section="py-20 md:py-32",
        gap="gap-8 md:gap-12",
        container="max-w-5xl px-5 md:px-6",
    ),
}

CONTAINER_MODE_CLASSES: dict[str, str] = {
    ContainerMode.CONTAINER_WIDE.value: "max-w-7xl mx-auto",
    ContainerMode.CONTAINER_STANDARD.value: "max-w-6xl mx-auto",
    ContainerMode.CONTAINER_NARROW.value: "max-w-5xl mx-auto",
}

SURFACE_STYLE_CLASSES: dict[str, str] = {
    SurfaceStyle.SURFACE_SOFT.value: "rounded-3xl border border-black/5 bg-white/80 backdrop-blur-sm",
    SurfaceStyle.SURFACE_CLEAN.value: "rounded-2xl border border-black/5 bg-white",
    SurfaceStyle.SURFACE_DARK.value: "rounded-3xl border border-white/10 bg-white/5 backdrop-blur-md",
    SurfaceStyle.SURFACE_ACCENT.value: "rounded-3xl border border-transparent bg-blue-600 text-white",
}

ACCENT_CARD_MODE_CLASSES: dict[str, str] = {
    AccentCardMode.ACCENT_FILL.value: "bg-blue-600 text-white border-transparent",
    AccentCardMode.ACCENT_OUTLINE.value: "bg-transparent border border-blue-600 text-inherit",
    AccentCardMode.ACCENT_GLOW_SOFT.value: "bg-white border border-blue-600/30 shadow-[0_0_40px_rgba(37,99,235,0.12)]",
}

DIVIDER_STYLE_CLASSES: dict[str, str] = {
    DividerStyle.LINE_SOFT.value: "border-t border-black/10",
    DividerStyle.LINE_STRICT.value: "border-t border-black/20",
    DividerStyle.LINE_NONE.value: "",
}

ICON_STYLE_CLASSES: dict[str, str] = {
    IconStyle.ICON_MINIMAL.value: "w-5 h-5 opacity-80",
    IconStyle.ICON_OUTLINE.value: "w-5 h-5 opacity-90 stroke-[1.75]",
    IconStyle.ICON_NONE.value: "",
}

MOTION_PROFILES: dict[str, MotionDef] = {
    MotionProfile.MOTION_OFF.value: MotionDef(reveal=False, hover=False, parallax=False),
    MotionProfile.MOTION_MINIMAL.value: MotionDef(reveal=True, hover=True, parallax=False),
    MotionProfile.MOTION_SUBTLE.value: MotionDef(reveal=True, hover=True, parallax=True),
}

# ─────────────────────────────────────────────────────────────────
#  ENUM REGISTRY (for validation)
# ─────────────────────────────────────────────────────────────────

ENUM_REGISTRY: dict[str, set[str]] = {
    "theme_pack": {e.value for e in ThemePack},
    "heading_mode": {e.value for e in HeadingMode},
    "body_mode": {e.value for e in BodyMode},
    "media_style": {e.value for e in MediaStyle},
    "button_style": {e.value for e in ButtonStyle},
    "decorator_mode": {e.value for e in DecoratorMode},
    "trust_mode": {e.value for e in TrustMode},
    "spacing_mode": {e.value for e in SpacingMode},
    "motion_profile": {e.value for e in MotionProfile},
    "container_mode": {e.value for e in ContainerMode},
    "surface_style": {e.value for e in SurfaceStyle},
    "accent_card_mode": {e.value for e in AccentCardMode},
    "divider_style": {e.value for e in DividerStyle},
    "icon_style": {e.value for e in IconStyle},
}


def validate_modifier_payload(modifiers: Mapping[str, Any]) -> list[str]:
    """Validate that all modifier keys and values are in the registry."""
    errors: list[str] = []
    for key, value in modifiers.items():
        if key not in ENUM_REGISTRY:
            errors.append(f"Unknown modifier key: {key!r}")
            continue
        if not isinstance(value, str):
            errors.append(f"Modifier {key!r} must be a string enum value, got {type(value).__name__}")
            continue
        if value not in ENUM_REGISTRY[key]:
            errors.append(
                f"Invalid value {value!r} for {key!r}. Allowed: {sorted(ENUM_REGISTRY[key])}"
            )
    return errors


def resolve_modifier_bundle(modifiers: Mapping[str, str]) -> dict[str, Any]:
    """Resolve modifier enum values to their CSS class / object representations."""
    bundle: dict[str, Any] = {}
    if "theme_pack" in modifiers:
        bundle["theme_pack"] = THEME_PACKS.get(modifiers["theme_pack"])
    if "heading_mode" in modifiers:
        bundle["heading_class"] = HEADING_MODE_CLASSES.get(modifiers["heading_mode"], "")
    if "body_mode" in modifiers:
        bundle["body_class"] = BODY_MODE_CLASSES.get(modifiers["body_mode"], "")
    if "media_style" in modifiers:
        bundle["media_class"] = MEDIA_STYLE_CLASSES.get(modifiers["media_style"], "")
    if "button_style" in modifiers:
        bundle["button_class"] = BUTTON_STYLE_CLASSES.get(modifiers["button_style"], "")
    if "decorator_mode" in modifiers:
        bundle["decorator_partial"] = DECORATOR_PARTIALS.get(modifiers["decorator_mode"], "")
    if "trust_mode" in modifiers:
        bundle["trust_renderer"] = TRUST_MODE_RENDERERS.get(modifiers["trust_mode"], "")
    if "spacing_mode" in modifiers:
        bundle["spacing"] = SPACING_PRESETS.get(modifiers["spacing_mode"])
    if "motion_profile" in modifiers:
        bundle["motion"] = MOTION_PROFILES.get(modifiers["motion_profile"])
    if "container_mode" in modifiers:
        bundle["container_class"] = CONTAINER_MODE_CLASSES.get(modifiers["container_mode"], "")
    if "surface_style" in modifiers:
        bundle["surface_class"] = SURFACE_STYLE_CLASSES.get(modifiers["surface_style"], "")
    if "accent_card_mode" in modifiers:
        bundle["accent_card_class"] = ACCENT_CARD_MODE_CLASSES.get(modifiers["accent_card_mode"], "")
    if "divider_style" in modifiers:
        bundle["divider_class"] = DIVIDER_STYLE_CLASSES.get(modifiers["divider_style"], "")
    if "icon_style" in modifiers:
        bundle["icon_class"] = ICON_STYLE_CLASSES.get(modifiers["icon_style"], "")
    return bundle
