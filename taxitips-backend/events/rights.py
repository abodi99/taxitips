"""
Vad en evenemangskälla får användas till, och på vilken grund.

Två handlingar hålls isär: att LAGRA källans data och att VISA den i den betalda
förarappen. Varje handling kräver två saker samtidigt (settings.EVENT_SOURCES):

* en brytare som är på, och
* en rättighetsreferens -- den villkorspunkt eller det skriftliga avtal som faktiskt
  tillåter handlingen.

En påslagen brytare utan referens ger ingenting. Brytaren är teknik; rätten kommer
bara från det referensen pekar på, och det kan koden inte kontrollera. Därför skrivs
referensen i källstatus och visas på pipeline-sidan, där den kan granskas.

Utgångsläget (2026-09-14, se docs/data-sources.md):

* Ticketmaster: lagring enligt de publicerade villkoren ("for reasonable periods in
  order to provide the service"). Visning i den betalda appen kräver avtal -- villkoren
  förbjuder att "derive revenues".
* PredictHQ: varken lagring eller visning utan skriftligt avtal (villkor 3.7 d i).
  De publicerade villkoren undantar inte lokal testlagring.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


class StorageNotPermitted(ValueError):
    """Ett försök att spara en källa som inte får lagras."""


@dataclass(frozen=True)
class SourceRights:
    source: str
    store: bool
    store_reference: str
    show_in_app: bool
    app_reference: str

    def may_store(self) -> bool:
        return self.store and bool(self.store_reference.strip())

    def may_show_in_app(self) -> bool:
        return self.may_store() and self.show_in_app and bool(self.app_reference.strip())

    def refusal(self, action: str) -> str:
        """Varför handlingen ("store" eller "app") inte är tillåten; tom sträng om den är det."""
        if action == "store":
            if not self.store:
                return "lagring är avstängd för källan"
            if not self.store_reference.strip():
                return "lagring saknar rättighetsreferens (villkorspunkt eller skriftligt avtal)"
            return ""
        if not self.may_store():
            return "källan får inte lagras och alltså inte heller visas"
        if not self.show_in_app:
            return "visning i förarappen är avstängd för källan"
        if not self.app_reference.strip():
            return "visning i förarappen saknar rättighetsreferens (avtal)"
        return ""

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "mayStore": self.may_store(),
            "storeReference": self.store_reference,
            "storeRefusal": self.refusal("store"),
            "mayShowInApp": self.may_show_in_app(),
            "appReference": self.app_reference,
            "appRefusal": self.refusal("app"),
        }


def rights_for(source: str) -> SourceRights:
    config = (getattr(settings, "EVENT_SOURCES", None) or {}).get(source) or {}
    return SourceRights(
        source=source,
        store=bool(config.get("store")),
        store_reference=str(config.get("store_reference") or ""),
        show_in_app=bool(config.get("show_in_app")),
        app_reference=str(config.get("app_reference") or ""),
    )


def app_sources() -> list[str]:
    """Källorna förarappen får visa."""
    configured = getattr(settings, "EVENT_SOURCES", None) or {}
    return [source for source in configured if rights_for(source).may_show_in_app()]
