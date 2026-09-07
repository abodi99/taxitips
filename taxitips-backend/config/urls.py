from django.contrib import admin
from django.urls import include, path

from core.pipeline_view import pipeline
from core.views import health

urlpatterns = [
    path("health", health),
    path("api/pipeline", pipeline),
    path("billing/", include("billing.urls")),
    path("admin/", admin.site.urls),
]
