from django.urls import path

from .views import (
    PlansListView,
    ServicesListView,
    MySubscriptionView,
    CreatePaymentView,
    CreateServicePaymentView,
    PaymentHistoryView,
    PaymentStatusView,
    ClickPrepareView,
    ClickCompleteView,
    PaymeWebhookView,
)

urlpatterns = [
    path('plans/', PlansListView.as_view()),
    path('services/', ServicesListView.as_view()),
    path('my-subscription/', MySubscriptionView.as_view()),
    path('create/', CreatePaymentView.as_view()),
    path('create-service/', CreateServicePaymentView.as_view()),
    path('status/<str:transaction_id>/', PaymentStatusView.as_view()),
    path('history/', PaymentHistoryView.as_view()),
    # Click webhooks
    path('click/prepare/', ClickPrepareView.as_view()),
    path('click/complete/', ClickCompleteView.as_view()),
    # Payme webhook (single endpoint for all methods)
    path('payme/', PaymeWebhookView.as_view()),
]
