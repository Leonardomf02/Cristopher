"""Built-in bundle_id → category mapping. User overrides live in app_category_overrides."""

CATEGORY_COLORS = {
    "productivity": "#10B981",
    "development": "#3B82F6",
    "communication": "#06B6D4",
    "social": "#EC4899",
    "gaming": "#EF4444",
    "entertainment": "#8B5CF6",
    "system": "#6B7280",
    "browser": "#F59E0B",
    "other": "#9CA3AF",
}

CATEGORY_LABELS = {
    "productivity": "Produtividade",
    "development": "Desenvolvimento",
    "communication": "Comunicação",
    "social": "Social",
    "gaming": "Gaming",
    "entertainment": "Entretenimento",
    "system": "Sistema",
    "browser": "Browser",
    "other": "Outros",
}

BUNDLE_CATEGORIES: dict[str, str] = {
    # Development
    "com.microsoft.VSCode": "development",
    "com.apple.dt.Xcode": "development",
    "com.jetbrains.intellij": "development",
    "com.jetbrains.pycharm": "development",
    "com.jetbrains.WebStorm": "development",
    "com.jetbrains.datagrip": "development",
    "com.sublimetext.4": "development",
    "com.googlecode.iterm2": "development",
    "com.apple.Terminal": "development",
    "com.github.atom": "development",
    "com.postmanlabs.mac": "development",
    "com.docker.docker": "development",
    "com.figma.Desktop": "development",

    # Productivity
    "com.apple.iWork.Pages": "productivity",
    "com.apple.iWork.Keynote": "productivity",
    "com.apple.iWork.Numbers": "productivity",
    "com.microsoft.Word": "productivity",
    "com.microsoft.Excel": "productivity",
    "com.microsoft.Powerpoint": "productivity",
    "com.apple.Notes": "productivity",
    "com.apple.reminders": "productivity",
    "md.obsidian": "productivity",
    "notion.id": "productivity",
    "com.culturedcode.ThingsMac": "productivity",
    "com.todoist.mac.Todoist": "productivity",

    # Communication
    "com.microsoft.teams2": "communication",
    "com.microsoft.teams": "communication",
    "us.zoom.xos": "communication",
    "com.tinyspeck.slackmacgap": "communication",
    "com.apple.mail": "communication",
    "com.google.Chrome.app.bkhkkdjakdlhpbbfidgpepoapgjbpcnf": "communication",  # Gmail PWA sample
    "com.apple.iChat": "communication",  # Messages

    # Social
    "com.hnc.Discord": "social",
    "com.twitter.twitter-mac": "social",
    "com.reeder.5macos": "social",
    "com.burbn.instagram": "social",

    # Gaming
    "com.riotgames.LeagueofLegends.GameClient": "gaming",
    "com.riotgames.LeagueofLegends.LeagueClient": "gaming",
    "com.valvesoftware.steam": "gaming",
    "com.epicgames.launcher": "gaming",
    "com.blizzard.agent": "gaming",
    "com.riotgames.RiotClientServices": "gaming",
    "com.riotgames.RiotClient": "gaming",

    # Entertainment
    "com.spotify.client": "entertainment",
    "com.apple.Music": "entertainment",
    "com.apple.TV": "entertainment",
    "com.netflix.Netflix": "entertainment",
    "com.plexapp.plex": "entertainment",

    # Browser
    "com.apple.Safari": "browser",
    "com.google.Chrome": "browser",
    "org.mozilla.firefox": "browser",
    "com.brave.Browser": "browser",
    "com.microsoft.edgemac": "browser",
    "company.thebrowser.Browser": "browser",  # Arc

    # System
    "com.apple.finder": "system",
    "com.apple.systempreferences": "system",
    "com.apple.ActivityMonitor": "system",
}

# Secondary heuristics by app name lowercase when bundle_id isn't mapped.
NAME_KEYWORDS = [
    (("steam", "battle.net", "league", "valorant", "minecraft", "epic games"), "gaming"),
    (("discord", "telegram", "whatsapp"), "social"),
    (("teams", "zoom", "slack", "meet", "webex"), "communication"),
    (("xcode", "code", "intellij", "pycharm", "terminal", "iterm", "docker"), "development"),
    (("spotify", "music", "youtube", "netflix"), "entertainment"),
    (("safari", "chrome", "firefox", "arc", "brave", "edge"), "browser"),
    (("finder", "settings", "system preferences"), "system"),
]


def categorize(bundle_id: str | None, app_name: str | None) -> str:
    if bundle_id and bundle_id in BUNDLE_CATEGORIES:
        return BUNDLE_CATEGORIES[bundle_id]
    if app_name:
        lowered = app_name.lower()
        for keywords, cat in NAME_KEYWORDS:
            if any(k in lowered for k in keywords):
                return cat
    return "other"
