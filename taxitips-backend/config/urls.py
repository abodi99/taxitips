from django.contrib import admin
from django.urls import include, path

from core import api
from core.pipeline_view import pipeline
from core import service_view
from maritime import views as maritime_views
from core.views import health, pipeline_health
from events import api as events_api
from events import live as events_live
from fleet import support_api

urlpatterns = [
    path("health", health),
    path("health/pipeline", pipeline_health),
    path("api/pipeline", pipeline),
    # En tjänst i taget (tåg, kollektivtrafik, väg, flyg, väder, evenemang) och ett tips med hela
    # kedjan -- bara med DEBUG. Se core/service_view.py.
    path("api/pipeline/services", service_view.services),
    path("api/pipeline/airport-delays", service_view.airport_delays),
    path("api/pipeline/service/<str:key>", service_view.service),
    path("api/pipeline/tip/<uuid:opportunity_id>", service_view.tip),
    # PredictHQ live, bara med DEBUG: deras data får inte sparas. Se events/live.py.
    path("api/pipeline/predicthq", events_live.pipeline_predicthq),
    # Färjor på väg in, live -- bara med DEBUG. Se maritime/approach.py.
    path("api/pipeline/ferries", maritime_views.ferries_live),
    # Förar-API:t (Spår B). Samma fältnamn som Supabase-RPC:erna, se
    # core/api.py -- appen byter väg utan att kortens kod skrivs om.
    path("api/alerts", api.alerts),
    path("api/events", events_api.upcoming),
    path("api/opportunities/<uuid:opportunity_id>", api.opportunity_detail),
    path("api/feedback", api.feedback),
    path("api/config", api.config),
    # Notiser och favoriter. Favoritlistan ligger både i /api/alerts (som
    # `favorites`, så ett kort aldrig kan försvinna bakom ett filter) och
    # som en egen endpoint, så listan går att öppna utan att hämta flödet.
    path("api/favorites", api.favorites),
    path("api/notifications", api.notifications),
    path("api/notify-prefs", api.notify_prefs),
    # Färjor på väg in i förarens område -- se maritime/views.py.
    path("api/ferries", maritime_views.ferries),
    path("api/presence", api.presence),
    path("api/device/session", api.device_session),
    # DEBUG-only: lista enheter + skicka test-FCM (pipeline-viz).
    path("api/dev/devices", api.push_devices),
    path("api/dev/push", api.push_send),
    # Kundlivscykeln: parkoppling, skiftbyte, bilar, licenser, län,
    # beställningar och uppsägning. Se fleet/urls.py.
    path("api/fleet/", include("fleet.urls")),
    # Supportchatten, användarens sida (kontot eller telefonen).
    path("api/support", support_api.conversation),
    path("api/support/unread", support_api.unread),
    path("api/support/messages", support_api.send),
    # Plattformens egen back-office. Kräver StaffRole -- se fleet/admin_api.py.
    path("api/admin/", include("fleet.admin_urls")),
    path("billing/", include("billing.urls")),
    path("admin/", admin.site.urls),
]
