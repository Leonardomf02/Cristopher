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


# ── Browser: classificar pelo título da janela ───────────────────
#
# 183h/mês de browser caíam todas em "browser" (e no Screen Time da Apple em
# "Productivity & Finance", porque o perfil do Brave se chama Work). Isso torna o
# maior número da app inútil. Aqui olha-se para o título da janela, que é onde
# está o site: "Facebook - Brave - Work" → social.

BROWSER_TITLE_RULES: list[tuple[tuple[str, ...], str]] = [
    # sites de LoL/TFT: são horas de jogo disfarçadas de browser
    (("u.gg", "op.gg", "mobalytics", "lolalytics", "metasrc", "porofessor",
      "blitz.gg", "leagueoflegends", "league of legends", "teamfight", "tft ",
      " tft", "tracker.gg", "deeplol", "dpm.lol"), "gaming"),
    (("facebook", "instagram", "twitter", " x — ", "tiktok", "reddit", "linkedin",
      "snapchat", "whatsapp web", "messenger", "discord"), "social"),
    (("youtube", "netflix", "twitch", "prime video", "disney", "hbo", "aniwave",
      "anime", "crunchyroll", "filme", "movie", "série", "series", "streamcinema",
      "cinespot", "imdb", "spotify"), "entertainment"),
    # os projectos dele a correr no browser (o site local chama-se como o projecto)
    (("cristopher", "travel planner", "imdb —", "jungle meta", "oracle cloud",
      "console.cloud", "aws console", "azure portal", "railway", "render.com",
      "codespaces"), "development"),
    (("github", "gitlab", "stack overflow", "stackoverflow", "localhost", "docs.",
      "documentation", "developer.", "mdn", "npm", "pypi", "claude", "chatgpt",
      "vercel", "supabase", "figma"), "development"),
    (("gmail", "outlook", "mail", "calendar", "drive.google", "docs.google",
      "sheets", "notion", "trello", "jira", "moodle", "classroom", "fenix",
      "clickup", "asana"), "productivity"),
    (("bank", "banco", "revolut", "trading212", "trading 212", "binance", "coinbase",
      "finst", "degiro", "investing", "bolsa", "irs", "financas", "finanças"), "finance"),
    (("olx", "vinted", "standvirtual", "amazon", "aliexpress", "worten", "fnac",
      "shop", "loja", "carrinho", "checkout"), "shopping"),
    (("league of legends", "op.gg", "u.gg", "porofessor", "mobalytics", "lolalytics",
      "steam", "epic games"), "gaming"),
]

BROWSER_BUNDLES = {
    "com.brave.Browser", "com.google.Chrome", "com.apple.Safari",
    "org.mozilla.firefox", "company.thebrowser.Browser", "com.microsoft.edgemac",
}


def is_browser(bundle_id: str | None, app_name: str | None) -> bool:
    if bundle_id and bundle_id in BROWSER_BUNDLES:
        return True
    low = (app_name or "").lower()
    return any(k in low for k in ("safari", "chrome", "firefox", "arc", "brave", "edge"))


# O utilizador separa o browser por perfis com nome ("… - Brave - Work",
# "- Brave - lol", "- Brave - Cinema"). O perfil é a melhor pista quando o site
# não é reconhecido.
BROWSER_PROFILE_RULES: dict[str, str] = {
    "work": "productivity",
    "trabalho": "productivity",
    "dev": "development",
    "lol": "gaming",
    "gaming": "gaming",
    "cinema": "entertainment",
    "chill": "entertainment",
    "social media": "social",
    "social": "social",
    "compras": "shopping",
    "shopping": "shopping",
    "financas": "finance",
    "finanças": "finance",
}


def _profile_category(title: str) -> str | None:
    partes = [p.strip().lower() for p in title.split(" - ")]
    if len(partes) >= 3 and partes[-2] in ("brave", "chrome", "edge"):
        return BROWSER_PROFILE_RULES.get(partes[-1])
    return None


# Títulos que são o próprio browser a falar, não um site: apareciam nos rankings
# como se fossem páginas visitadas ("Translate this page?" tinha 7h36, à frente
# do YouTube).
TITULOS_DO_BROWSER = (
    "translate this page", "find in page", "problem loading page", "new tab",
    "novo separador", "nova aba", "página em branco", "about:blank", "settings",
    "definições", "extensions", "extensões", "downloads", "histórico", "history",
    "brave", "mozilla firefox", "firefox developer edition", "google chrome",
    "privacy error", "sem ligação", "no internet", "err_",
)


def e_ruido_do_browser(title: str | None) -> bool:
    """True quando o título é da interface do browser e não de uma página."""
    low = (title or "").strip().lower()
    if not low:
        return False
    return any(low == p or low.startswith(p) for p in TITULOS_DO_BROWSER)


# ── Browser: classificar pelo domínio ────────────────────────────
#
# O domínio é o que o título devia ser: youtube.com é sempre entretenimento, e o
# título dessa mesma página muda a cada vídeo (e em ecrã inteiro nem existe). São
# umas dezenas de sites contra 1970 títulos distintos.

DOMAIN_CATEGORIES: dict[str, str] = {
    # Desenvolvimento
    "github.com": "development", "gitlab.com": "development",
    "stackoverflow.com": "development", "stackexchange.com": "development",
    "localhost": "development", "127.0.0.1": "development",
    "claude.ai": "development", "chatgpt.com": "development", "chat.openai.com": "development",
    "console.anthropic.com": "development", "platform.openai.com": "development",
    "developer.mozilla.org": "development", "npmjs.com": "development", "pypi.org": "development",
    "vercel.com": "development", "supabase.com": "development", "railway.app": "development",
    "render.com": "development", "docker.com": "development", "readthedocs.io": "development",
    "fastapi.tiangolo.com": "development", "react.dev": "development",
    "tailwindcss.com": "development", "portal.azure.com": "development",
    "console.cloud.google.com": "development", "cloud.oracle.com": "development",
    "codespaces.github.com": "development", "huggingface.co": "development",
    # Social
    "facebook.com": "social", "instagram.com": "social", "x.com": "social",
    "twitter.com": "social", "tiktok.com": "social", "reddit.com": "social",
    "linkedin.com": "social", "snapchat.com": "social", "web.whatsapp.com": "social",
    "messenger.com": "social", "discord.com": "social", "threads.net": "social",
    # Entretenimento
    "youtube.com": "entertainment", "youtu.be": "entertainment", "netflix.com": "entertainment",
    "twitch.tv": "entertainment", "primevideo.com": "entertainment",
    "disneyplus.com": "entertainment", "hbomax.com": "entertainment", "max.com": "entertainment",
    "aniwave.to": "entertainment", "crunchyroll.com": "entertainment",
    "open.spotify.com": "entertainment", "imdb.com": "entertainment",
    "letterboxd.com": "entertainment", "9gag.com": "entertainment",
    # Gaming
    "op.gg": "gaming", "u.gg": "gaming", "lolalytics.com": "gaming",
    "mobalytics.gg": "gaming", "metasrc.com": "gaming", "porofessor.gg": "gaming",
    "blitz.gg": "gaming", "tracker.gg": "gaming", "deeplol.gg": "gaming",
    "dpm.lol": "gaming", "leagueoflegends.com": "gaming", "riotgames.com": "gaming",
    "store.steampowered.com": "gaming", "steamcommunity.com": "gaming",
    "epicgames.com": "gaming", "tftactics.gg": "gaming",
    # Produtividade / estudo
    "mail.google.com": "productivity", "gmail.com": "productivity",
    "outlook.com": "productivity", "outlook.office.com": "productivity",
    "calendar.google.com": "productivity", "drive.google.com": "productivity",
    "docs.google.com": "productivity", "sheets.google.com": "productivity",
    "notion.so": "productivity", "trello.com": "productivity", "atlassian.net": "productivity",
    "moodle.org": "productivity", "classroom.google.com": "productivity",
    "fenix.tecnico.ulisboa.pt": "productivity", "overleaf.com": "productivity",
    "translate.google.com": "productivity", "chatgpt.com/g": "productivity",
    # Finanças
    "revolut.com": "finance", "app.revolut.com": "finance", "trading212.com": "finance",
    "binance.com": "finance", "coinbase.com": "finance", "finst.com": "finance",
    "degiro.nl": "finance", "investing.com": "finance", "tradingview.com": "finance",
    "finance.yahoo.com": "finance", "cgd.pt": "finance", "portaldasfinancas.gov.pt": "finance",
    "coinmarketcap.com": "finance", "coingecko.com": "finance",
    # Compras
    "olx.pt": "shopping", "vinted.pt": "shopping", "vinted.com": "shopping",
    "amazon.es": "shopping", "amazon.com": "shopping", "aliexpress.com": "shopping",
    "worten.pt": "shopping", "fnac.pt": "shopping", "standvirtual.com": "shopping",
    "marketplace.facebook.com": "shopping", "ebay.com": "shopping", "temu.com": "shopping",
}

# Sufixos: apanham subdomínios sem os listar um a um (m.youtube.com, pt.wikipedia.org).
DOMAIN_SUFFIX_RULES: list[tuple[str, str]] = [
    (".youtube.com", "entertainment"), (".facebook.com", "social"),
    (".instagram.com", "social"), (".reddit.com", "social"),
    (".github.com", "development"), (".github.io", "development"),
    (".stackexchange.com", "development"), (".readthedocs.io", "development"),
    (".google.com", "productivity"), (".wikipedia.org", "productivity"),
    (".sharepoint.com", "productivity"), (".office.com", "productivity"),
    (".op.gg", "gaming"), (".riotgames.com", "gaming"),
    (".olx.pt", "shopping"), (".vinted.pt", "shopping"),
]


def categorize_domain(domain: str | None) -> str | None:
    """Categoria a partir do domínio. None quando o site não é conhecido."""
    if not domain:
        return None
    low = domain.strip().lower()
    if low.startswith("www."):
        low = low[4:]
    if low in DOMAIN_CATEGORIES:
        return DOMAIN_CATEGORIES[low]
    for sufixo, cat in DOMAIN_SUFFIX_RULES:
        if low.endswith(sufixo):
            return cat
    # localhost:3001 e afins
    if low.startswith("localhost") or low.startswith("127.0.0.1") or low.endswith(".local"):
        return "development"
    return None


def categorize_browser_title(title: str | None, learned: dict[str, str] | None = None,
                             domain: str | None = None) -> str | None:
    """Categoria de uma janela de browser. None = não dá para saber.

    Ordem: regras aprendidas (ele ou a IA decidiram) → domínio → sites pelo
    título → perfil do browser. O domínio vem antes do título porque não muda
    a cada página e não se deixa enganar por um título ambíguo."""
    low = (title or "").lower()
    if learned and low:
        for padrao in sorted(learned, key=len, reverse=True):
            if padrao and padrao in low:
                return learned[padrao]
    porDominio = categorize_domain(domain)
    if porDominio:
        return porDominio
    if not title:
        return None
    for palavras, cat in BROWSER_TITLE_RULES:
        if any(p in low for p in palavras):
            return cat
    return _profile_category(title)


# As categorias novas precisam de cor e nome para os gráficos.
CATEGORY_COLORS.update({"finance": "#22C55E", "shopping": "#F472B6"})
CATEGORY_LABELS.update({"finance": "Finanças", "shopping": "Compras"})
