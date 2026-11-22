#!/usr/bin/env python3
"""
Slår ihop lib/l10n/parts/*.json till lib/l10n/app_sv.arb, app_en.arb och app_ar.arb.

Varför delar: texterna för en skärm ligger i EN fil med alla tre språken bredvid
varandra, så att den som ändrar en svensk mening ser engelskan och arabiskan
samtidigt -- och flera kan arbeta i olika delar utan att krocka i samma arb-fil.

En del ser ut så här:

    {
      "settingsLanguageTitle": {
        "sv": "Språk",
        "en": "Language",
        "ar": "اللغة",
        "description": "Rubrik i inställningarna"          (valfri)
        "placeholders": {"count": {"type": "int"}}          (valfri)
      }
    }

Kör: python3 tool/build_arb.py   (sedan flutter gen-l10n, eller flutter pub get / build)
Avbryter med fel om en nyckel finns i två delar, saknar ett språk, eller om
platshållarna ({namn}) skiljer sig mellan språken.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "lib" / "l10n" / "parts"
OUT = ROOT / "lib" / "l10n"
LANGS = ("sv", "en", "ar")
KEY = re.compile(r"^[a-z][A-Za-z0-9]*$")


def placeholders(text: str) -> set[str]:
    """Namnen i {namn}, utan ICU-grenarna (plural/select har {namn, plural, ...})."""
    names = set()
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == "{":
            if depth == 0:
                m = re.match(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)", text[i:])
                if m:
                    names.add(m.group(1))
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return names


def main() -> int:
    merged: dict[str, dict] = {}
    origin: dict[str, str] = {}
    errors: list[str] = []
    for part in sorted(PARTS.glob("*.json")):
        try:
            data = json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{part.name}: ogiltig JSON: {exc}")
            continue
        for key, entry in data.items():
            if not KEY.match(key):
                errors.append(f"{part.name}: {key}: nyckeln ska vara lowerCamelCase")
            if key in merged:
                errors.append(f"{part.name}: {key}: finns redan i {origin[key]}")
                continue
            missing = [lang for lang in LANGS if not isinstance(entry.get(lang), str) or not entry[lang]]
            if missing:
                errors.append(f"{part.name}: {key}: saknar {', '.join(missing)}")
                continue
            base = placeholders(entry["sv"])
            for lang in LANGS[1:]:
                if placeholders(entry[lang]) != base:
                    errors.append(
                        f"{part.name}: {key}: platshållarna i {lang} "
                        f"{sorted(placeholders(entry[lang]))} != sv {sorted(base)}"
                    )
            merged[key] = entry
            origin[key] = part.name
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    for lang in LANGS:
        arb: dict[str, object] = {"@@locale": lang}
        for key in sorted(merged):
            entry = merged[key]
            arb[key] = entry[lang]
            if lang == "sv":
                meta = {}
                if entry.get("description"):
                    meta["description"] = entry["description"]
                if entry.get("placeholders"):
                    meta["placeholders"] = entry["placeholders"]
                if meta:
                    arb[f"@{key}"] = meta
        (OUT / f"app_{lang}.arb").write_text(
            json.dumps(arb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"{len(merged)} texter i {len(list(PARTS.glob('*.json')))} delar -> app_sv/en/ar.arb")
    return 0


if __name__ == "__main__":
    sys.exit(main())
