from django.urls import path

from .views import ClientWebhookView, TeamWebhookView

urlpatterns = [
    path("client/webhook/", ClientWebhookView.as_view()),
    path("team/webhook/", TeamWebhookView.as_view()),
]