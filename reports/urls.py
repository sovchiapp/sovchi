from django.urls import path
from .views import (
    CreateReportView,
    ReportListView,
    ReportUpdateStatusView,
    FlaggedUsersListView,
    UserReportsView,
    ReportEventsView,
)

urlpatterns = [
    path("report-create/", CreateReportView.as_view(), name="report-create"),
    path("admin/reports/", ReportListView.as_view(), name="admin-report-list"),
    path("admin/reports/<int:report_id>/status/", ReportUpdateStatusView.as_view(), name="admin-report-update-status"),
    path("admin/reports/<int:report_id>/events/", ReportEventsView.as_view(), name="admin-report-events"),
    path("admin/flagged-users/", FlaggedUsersListView.as_view(), name="admin-flagged-users"),
    path("admin/user-reports/<int:user_id>/", UserReportsView.as_view(), name="admin-user-reports"),
]