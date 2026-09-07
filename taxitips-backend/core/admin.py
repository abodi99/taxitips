"""
Admin -- ett av huvudskälen till Django i det här projektet.

Att kunna öppna listan över tips, sortera på poäng och se VARFÖR ett tåg
fick sitt värde är skillnaden mot att fråga databasen via MCP varje gång.
"""

from django.contrib import admin
from django.utils.html import format_html, format_html_join

from core.models import (
    Opportunity,
    RailAssessment,
    ScoringRule,
    SourceEvent,
    Station,
    StopArea,
)


@admin.register(ScoringRule)
class ScoringRuleAdmin(admin.ModelAdmin):
    """
    Poängreglerna som rader. Det här är stället där taken slutar vara
    hårdkodade tal utspridda i scoring.js.
    """

    list_display = ("tier", "mode", "condition", "bound", "confidence", "updated_at")
    list_filter = ("tier", "mode", "confidence")
    search_fields = ("tier", "condition", "note")

    @admin.display(description="gräns")
    def bound(self, obj):
        if obj.floor is not None:
            return f"golv {obj.floor}"
        if obj.cap is not None:
            return f"tak {obj.cap}"
        return "—"


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = (
        "demand_score",
        "severity_tier",
        "mode",
        "region",
        "short_title",
        "confidence",
        "located",
        "active",
        "notified_at",
    )
    list_filter = ("severity_tier", "mode", "region", "confidence", "kind")
    search_fields = ("title", "summary", "external_id", "rule_id")
    readonly_fields = ("computed_at", "updated_at", "notified_at", "why")
    ordering = ("-demand_score",)
    list_per_page = 50

    fieldsets = (
        ("Vad", {"fields": ("title", "summary", "external_id", "kind", "mode")}),
        ("Bedömning", {"fields": ("severity_tier", "demand_score", "confidence",
                                  "level", "rule_id", "why")}),
        ("Var", {"fields": ("lat", "lon", "region", "places", "h3_index")}),
        ("När", {"fields": ("start_time", "end_time", "computed_at", "updated_at")}),
        ("Push", {"fields": ("notified_at", "expired_reason")}),
        ("Spårbarhet", {"fields": ("source_event_ids",), "classes": ("collapse",)}),
    )

    @admin.display(description="titel")
    def short_title(self, obj):
        return obj.title[:60] if obj.title else "—"

    @admin.display(description="plats", boolean=True)
    def located(self, obj):
        """Utan koordinat kan tipset inte avståndsfiltreras."""
        return obj.lat is not None

    @admin.display(description="aktiv", boolean=True)
    def active(self, obj):
        return obj.is_active

    @admin.display(description="motivering")
    def why(self, obj):
        if not obj.reasons:
            return "—"
        # format_html_join escapar varje motivering. Motiveringarna byggs
        # av oss, men de innehåller källtext (stationsnamn, destinationer)
        # -- den ska renderas som text, inte som markup.
        return format_html_join("", "• {}<br>", ((r,) for r in obj.reasons))


@admin.register(SourceEvent)
class SourceEventAdmin(admin.ModelAdmin):
    list_display = ("source", "external_id", "mode", "active_from", "active_to")
    list_filter = ("source", "mode")
    search_fields = ("external_id",)
    readonly_fields = ("fetched_at", "created_at", "raw")
    ordering = ("-fetched_at",)


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("signature", "name", "lat", "lon", "fetched_at")
    search_fields = ("signature", "name")


@admin.register(StopArea)
class StopAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "operator", "gid", "lat", "lon")
    list_filter = ("operator",)
    search_fields = ("name", "gid")


@admin.register(RailAssessment)
class RailAssessmentAdmin(admin.ModelAdmin):
    """
    Genkits granskningar. `lowered` är den kolumn som betyder något: om
    modellen aldrig sänker någon poäng gör den ingen nytta, och om den
    påstår sig höja är skyddsräcket i modellen brutet.
    """

    list_display = ("created_at", "rule_score", "model_score", "final_score",
                    "lowered", "model_name")
    list_filter = ("model_name",)
    search_fields = ("cache_key", "verdict")
    readonly_fields = ("created_at",)

    @admin.display(description="sänkte", boolean=True)
    def lowered(self, obj):
        return obj.final_score < obj.rule_score


admin.site.site_header = "TaxiTips"
admin.site.site_title = "TaxiTips"
admin.site.index_title = "Databearbetning"
