from django.contrib import admin
from django.urls import include, path

from core import api
from core.pipeline_view import pipeline
from core.views import health

urlpatterns = [
    path("health", health),
    path("api/pipeline", pipeline),
    # Förar-API:t (Spår B). Samma fältnamn som Supabase-RPC:erna, se
    # core/api.py -- appen byter väg utan att kortens kod skrivs om.
    path("api/alerts", api.alerts),
    path("api/opportunities/<uuid:opportunity_id>", api.opportunity_detail),
    path("api/feedback", api.feedback),
    path("api/config", api.config),
    path("billing/", include("billing.urls")),
    path("admin/", admin.site.urls),
]
