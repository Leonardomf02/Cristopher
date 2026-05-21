"""Mapping bundle_id → categoria (estilo Apple Screen Time).

A Apple categoriza apps a partir do `LSApplicationCategoryType` no Info.plist
de cada app (e da App Store quando o user a instalou). Como não temos acesso
ao agregador interno (`ScreenTimeAgent`), mantemos um mapping manual com as
apps mais comuns. Apps não mapeadas → 'Other'.

Categorias seguem exactamente as labels que a Apple usa em Settings.
"""
from __future__ import annotations

BUNDLE_CATEGORIES: dict[str, str] = {
    # ── Social ─────────────────────────────────────────────────────
    "com.apple.MobileSMS": "Social",
    "com.apple.iChat": "Social",
    "com.apple.MessagesApp": "Social",
    "com.apple.mail": "Social",
    "com.apple.facetime": "Social",
    "com.apple.FaceTime": "Social",
    "net.whatsapp.WhatsApp": "Social",
    "ru.keepcoder.Telegram": "Social",
    "org.telegram.desktop": "Social",
    "com.hnc.Discord": "Social",
    "com.tinyspeck.slackmacgap": "Social",
    "com.microsoft.teams2": "Social",
    "com.microsoft.teams": "Social",
    "us.zoom.xos": "Social",
    "com.skype.skype": "Social",
    "com.microsoft.Outlook": "Social",
    "com.readdle.smartemail-Mac": "Social",
    "com.tinder.tinder": "Social",
    "com.linkedin.LinkedIn": "Social",
    "com.toyopagroup.picaboo": "Social",  # Snapchat
    "com.burbn.instagram": "Social",
    "com.atebits.Tweetie2": "Social",  # X / Twitter
    "com.twitter.twitter-mac": "Social",
    "com.signal.Signal": "Social",
    "org.signal.MacOSSignal": "Social",
    "com.facebook.Facebook": "Social",
    "com.facebook.archon": "Social",  # Messenger

    # ── Productivity & Finance ─────────────────────────────────────
    "com.microsoft.VSCode": "Productivity & Finance",
    "com.apple.dt.Xcode": "Productivity & Finance",
    "com.googlecode.iterm2": "Productivity & Finance",
    "com.apple.Terminal": "Productivity & Finance",
    "com.jetbrains.intellij": "Productivity & Finance",
    "com.jetbrains.intellij.ce": "Productivity & Finance",
    "com.jetbrains.pycharm": "Productivity & Finance",
    "com.jetbrains.WebStorm": "Productivity & Finance",
    "com.jetbrains.toolbox": "Productivity & Finance",
    "com.sublimetext.4": "Productivity & Finance",
    "com.todesktop.230313mzl4w4u92": "Productivity & Finance",  # Cursor
    "com.exafunction.windsurf": "Productivity & Finance",
    "com.anthropic.claude": "Productivity & Finance",
    "com.openai.chat": "Productivity & Finance",
    # Browsers contam como Productivity & Finance no Apple Screen Time
    "com.apple.Safari": "Productivity & Finance",
    "com.google.Chrome": "Productivity & Finance",
    "com.brave.Browser": "Productivity & Finance",
    "org.mozilla.firefox": "Productivity & Finance",
    "com.microsoft.edgemac": "Productivity & Finance",
    "company.thebrowser.Browser": "Productivity & Finance",  # Arc
    # Office / docs
    "com.apple.iWork.Pages": "Productivity & Finance",
    "com.apple.iWork.Numbers": "Productivity & Finance",
    "com.apple.iWork.Keynote": "Productivity & Finance",
    "com.microsoft.Word": "Productivity & Finance",
    "com.microsoft.Excel": "Productivity & Finance",
    "com.microsoft.Powerpoint": "Productivity & Finance",
    "com.microsoft.onenote.mac": "Productivity & Finance",
    "com.apple.Notes": "Productivity & Finance",
    "notion.id": "Productivity & Finance",
    "com.electron.obsidian": "Productivity & Finance",
    "md.obsidian": "Productivity & Finance",
    "com.apple.iCal": "Productivity & Finance",
    "com.apple.reminders": "Productivity & Finance",
    "com.things3.Things": "Productivity & Finance",
    "com.todoist.mac.Todoist": "Productivity & Finance",
    "com.linear": "Productivity & Finance",
    "com.figma.Desktop": "Productivity & Finance",  # também aparece em Creativity, Apple coloca em Productivity
    # Finance
    "com.apple.stocks": "Productivity & Finance",
    "com.revolut.RevolutAppMac": "Productivity & Finance",

    # ── Creativity ─────────────────────────────────────────────────
    "com.adobe.Photoshop": "Creativity",
    "com.adobe.illustrator": "Creativity",
    "com.adobe.Premiere Pro": "Creativity",
    "com.adobe.AfterEffects": "Creativity",
    "com.adobe.LightroomClassicCC7": "Creativity",
    "com.adobe.lightroom": "Creativity",
    "com.bohemiancoding.sketch3": "Creativity",
    "com.apple.iMovie": "Creativity",
    "com.apple.FinalCut": "Creativity",
    "com.apple.garageband10": "Creativity",
    "com.apple.logic10": "Creativity",
    "com.apple.Photos": "Creativity",
    "com.apple.Preview": "Creativity",
    "com.pixelmatorteam.pixelmator.x": "Creativity",
    "com.serif.affinityphoto2": "Creativity",
    "com.serif.affinitydesigner2": "Creativity",
    "com.blackmagic-design.DaVinciResolve": "Creativity",
    "org.blenderfoundation.blender": "Creativity",
    "com.apple.iBooksAuthor": "Creativity",
    "com.canva.CanvaDesktop": "Creativity",

    # ── Travel ─────────────────────────────────────────────────────
    "com.apple.Maps": "Travel",
    "com.google.Maps": "Travel",
    "com.ubercab.UberClient": "Travel",
    "com.bolt.consumer.ios": "Travel",
    "com.airbnb.app": "Travel",
    "com.booking.BookingApp": "Travel",

    # ── Games ──────────────────────────────────────────────────────
    "com.riotgames.LeagueofLegends.LeagueClientUx": "Games",
    "com.riotgames.LeagueofLegends.GameClient": "Games",
    "com.riotgames.LeagueofLegends": "Games",
    "com.valvesoftware.steam": "Games",
    "com.epicgames.EpicGamesLauncher": "Games",
    "com.blizzard.agent": "Games",
    "net.minecraft.MinecraftLauncher": "Games",
    "com.riotgames.RiotClientUx": "Games",

    # ── Utilities ──────────────────────────────────────────────────
    "com.apple.finder": "Utilities",
    "com.apple.systempreferences": "Utilities",
    "com.apple.ActivityMonitor": "Utilities",
    "com.apple.AppStore": "Utilities",
    "com.apple.calculator": "Utilities",
    "com.apple.archiveutility": "Utilities",
    "com.apple.diskutility": "Utilities",
    "com.apple.keychainaccess": "Utilities",
    "com.apple.print.PrinterProxy": "Utilities",
    "com.apple.installer": "Utilities",
    "com.apple.airport.airportutility": "Utilities",
    "com.tunnelblick.tunnelblick": "Utilities",
    "com.tailscale.ipn.macsys": "Utilities",
    "io.tailscale.ipn.macos": "Utilities",
    "com.1password.1password": "Utilities",
    "com.googlecode.rectangle": "Utilities",
    "com.knollsoft.Rectangle": "Utilities",
    "com.if.Amphetamine": "Utilities",
    "com.runningwithcrayons.Alfred": "Utilities",
    "com.raycast.macos": "Utilities",
    "com.apple.ScreenTime": "Utilities",
    "com.apple.weather": "Utilities",

    # ── Entertainment ──────────────────────────────────────────────
    "com.apple.Music": "Entertainment",
    "com.apple.iTunes": "Entertainment",
    "com.spotify.client": "Entertainment",
    "com.apple.TV": "Entertainment",
    "com.netflix.Netflix": "Entertainment",
    "com.google.YouTube": "Entertainment",
    "com.apple.QuickTimePlayerX": "Entertainment",
    "tv.plex.player": "Entertainment",
    "org.videolan.vlc": "Entertainment",
    "com.colliderli.iina": "Entertainment",
    "com.amazon.aiv.AIVApp": "Entertainment",
    "com.twitch.desktop": "Entertainment",

    # ── Information & Reading ──────────────────────────────────────
    "com.apple.iBooksX": "Information & Reading",
    "com.apple.News": "Information & Reading",
    "com.apple.Books": "Information & Reading",
    "com.amazon.Kindle": "Information & Reading",
    "com.apple.Dictionary": "Information & Reading",
    "com.readdle.PDFExpert-Mac": "Information & Reading",
    "com.feedly.Feedly": "Information & Reading",
}


CATEGORY_ORDER = [
    "Social",
    "Productivity & Finance",
    "Other",
    "Creativity",
    "Travel",
    "Games",
    "Utilities",
    "Entertainment",
    "Information & Reading",
]


def category_for(bundle_id: str | None) -> str:
    if not bundle_id:
        return "Other"
    return BUNDLE_CATEGORIES.get(bundle_id, "Other")
