from app.models.idea import IdeaCategory


CATEGORY_LABELS: dict[str, str] = {
    IdeaCategory.AGRICULTURE.name: "Agriculture",
    IdeaCategory.HEALTHCARE.name: "Healthcare",
    IdeaCategory.EDUCATION.name: "Education",
    IdeaCategory.ENVIRONMENT.name: "Environment",
    IdeaCategory.ENERGY.name: "Energy",
    IdeaCategory.WATER.name: "Water",
    IdeaCategory.WASTE_MANAGEMENT.name: "Waste Management",
    IdeaCategory.ASSISTIVE_TECHNOLOGY.name: "Assistive Technology",
    IdeaCategory.WOMEN_SAFETY.name: "Women Safety",
    IdeaCategory.RURAL_DEVELOPMENT.name: "Rural Development",
    IdeaCategory.ELECTRONICS_IOT.name: "Electronics / IoT",
    IdeaCategory.MECHANICAL.name: "Mechanical Innovation",
    IdeaCategory.AI_SOFTWARE.name: "AI / Software",
    IdeaCategory.SOCIAL_INNOVATION.name: "Social Innovation",
    IdeaCategory.OTHERS.name: "Other",
}


_ALIASES: dict[str, IdeaCategory] = {
    "AGRICULTURE": IdeaCategory.AGRICULTURE,
    "AGRICULTURE & FARMING": IdeaCategory.AGRICULTURE,
    "AGRICULTURE AND FARMING": IdeaCategory.AGRICULTURE,
    "FARMING": IdeaCategory.AGRICULTURE,
    "HEALTHCARE": IdeaCategory.HEALTHCARE,
    "HEALTHCARE / MEDICAL": IdeaCategory.HEALTHCARE,
    "HEALTHCARE MEDICAL": IdeaCategory.HEALTHCARE,
    "HEALTH": IdeaCategory.HEALTHCARE,
    "MEDICAL": IdeaCategory.HEALTHCARE,
    "EDUCATION": IdeaCategory.EDUCATION,
    "EDUCATION & LEARNING": IdeaCategory.EDUCATION,
    "EDUCATION AND LEARNING": IdeaCategory.EDUCATION,
    "ENVIRONMENT": IdeaCategory.ENVIRONMENT,
    "ENVIRONMENT & CLIMATE": IdeaCategory.ENVIRONMENT,
    "ENVIRONMENT AND CLIMATE": IdeaCategory.ENVIRONMENT,
    "ENERGY": IdeaCategory.ENERGY,
    "RENEWABLE ENERGY": IdeaCategory.ENERGY,
    "WATER": IdeaCategory.WATER,
    "WATER & SANITATION": IdeaCategory.WATER,
    "WATER AND SANITATION": IdeaCategory.WATER,
    "WASTE": IdeaCategory.WASTE_MANAGEMENT,
    "WASTE MANAGEMENT": IdeaCategory.WASTE_MANAGEMENT,
    "ASSISTIVE TECHNOLOGY": IdeaCategory.ASSISTIVE_TECHNOLOGY,
    "WOMEN SAFETY": IdeaCategory.WOMEN_SAFETY,
    "WOMEN SAFETY & EMPOWERMENT": IdeaCategory.WOMEN_SAFETY,
    "WOMEN SAFETY AND EMPOWERMENT": IdeaCategory.WOMEN_SAFETY,
    "RURAL DEVELOPMENT": IdeaCategory.RURAL_DEVELOPMENT,
    "RURAL INNOVATION": IdeaCategory.RURAL_DEVELOPMENT,
    "ELECTRONICS / IOT": IdeaCategory.ELECTRONICS_IOT,
    "ELECTRONICS IOT": IdeaCategory.ELECTRONICS_IOT,
    "MECHANICAL": IdeaCategory.MECHANICAL,
    "MECHANICAL INNOVATION": IdeaCategory.MECHANICAL,
    "AI / SOFTWARE": IdeaCategory.AI_SOFTWARE,
    "AI SOFTWARE": IdeaCategory.AI_SOFTWARE,
    "AI / TECHNOLOGY / DIGITAL": IdeaCategory.AI_SOFTWARE,
    "AI TECHNOLOGY DIGITAL": IdeaCategory.AI_SOFTWARE,
    "TECHNOLOGY": IdeaCategory.AI_SOFTWARE,
    "SOCIAL INNOVATION": IdeaCategory.SOCIAL_INNOVATION,
    "COMMUNITY DEVELOPMENT": IdeaCategory.SOCIAL_INNOVATION,
    "FOOD & NUTRITION": IdeaCategory.OTHERS,
    "FOOD AND NUTRITION": IdeaCategory.OTHERS,
    "TRANSPORTATION": IdeaCategory.OTHERS,
    "TRANSPORTATION & MOBILITY": IdeaCategory.OTHERS,
    "TRANSPORTATION AND MOBILITY": IdeaCategory.OTHERS,
    "OTHER": IdeaCategory.OTHERS,
    "OTHERS": IdeaCategory.OTHERS,
}


def _key(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").strip().upper().split())


def coerce_idea_category(value: str | IdeaCategory | None) -> IdeaCategory | None:
    if value is None:
        return None
    if isinstance(value, IdeaCategory):
        return value
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned in IdeaCategory.__members__:
        return IdeaCategory[cleaned]
    for category in IdeaCategory:
        if cleaned == category.value:
            return category
    return _ALIASES.get(_key(cleaned), IdeaCategory.OTHERS)


def normalize_idea_category(value: str | IdeaCategory | None) -> str | None:
    category = coerce_idea_category(value)
    return category.name if category else None


def idea_category_label(value: str | IdeaCategory | None) -> str:
    category = coerce_idea_category(value)
    if not category:
        return ""
    return CATEGORY_LABELS.get(category.name, category.value)
