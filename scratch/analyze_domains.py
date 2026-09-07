import json
import re

with open('scratch/artifacts_dump.json', 'r', encoding='utf-8') as f:
    artifacts = json.load(f)

domains = {
    "calls": ["call", "facetime", "voip"],
    "messages": ["message", "sms", "imessage", "chat", "whatsapp", "telegram", "signal", "viber"],
    "web": ["safari", "chrome", "firefox", "browser", "history", "bookmark", "tab", "search"],
    "locations": ["location", "routine", "significant", "gps", "geopoint", "map", "parked", "cell_tower"],
    "apps": ["installed", "application", "app", "permissions", "guid", "bundle"],
    "networks": ["wifi", "wi-fi", "wireless", "cellular", "bluetooth", "network", "airdrop"],
    "notes": ["note", "memo", "voice", "reminder", "calendar"],
    "photos": ["photo", "media", "camera", "exif", "image", "video"],
    "health": ["health", "step", "heart", "workout", "sleep"],
    "system_state": ["battery", "power", "lock", "unlock", "reboot", "state", "screen"]
}

for domain, keywords in domains.items():
    matches = []
    for art in artifacts:
        name = art['name']
        if any(kw in name.lower() for kw in keywords):
            matches.append(art['safe_name'])
    print(f"Domain '{domain}': {len(matches)} matching artifacts. Sample: {matches[:6]}")
