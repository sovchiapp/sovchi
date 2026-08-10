from django.urls import path

from integrations.logs.views import TailLogsView, LogExportView

urlpatterns = [
    path('logs/tail/', TailLogsView.as_view(), name='logs-tail'),
    path('logs/export/', LogExportView.as_view(), name='logs-export'),
]