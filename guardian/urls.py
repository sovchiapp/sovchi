from django.urls import path

from .views import (
    GuardianChildSearchView,
    GuardianConnectView,
    GuardianListView,
    GuardianRequestActionView,
    GuardianChildrenView,
    GuardianChildDetailView,
    GuardianDisconnectView,
    GuardianDiscoveryView,
    GuardianSavedView,
    GuardianUnsaveView,
    GuardianFilterView,
    GuardianSeenView,
    GuardianForwardView,
    GuardianForwardDetailView,
    GuardianReceivedView,
    GuardianReceivedActionView,
    GuardianDeleteAccountView,
)

app_name = 'guardian'

urlpatterns = [
    path('search-child/', GuardianChildSearchView.as_view(), name='search-child'),
    path('connect/', GuardianConnectView.as_view(), name='connect'),
    path('my-guardians/', GuardianListView.as_view(), name='my-guardians'),
    path('my-guardians/<int:guardianship_id>/action/', GuardianRequestActionView.as_view(), name='request-action'),
    path('children/', GuardianChildrenView.as_view(), name='children'),
    path('child/', GuardianChildDetailView.as_view(), name='child-detail'),
    path('children/<int:guardianship_id>/disconnect/', GuardianDisconnectView.as_view(), name='disconnect'),
    path('discovery/', GuardianDiscoveryView.as_view(), name='discovery'),
    path('filter/', GuardianFilterView.as_view(), name='filter'),
    path('seen/', GuardianSeenView.as_view(), name='seen'),
    path('saved/', GuardianSavedView.as_view(), name='saved'),
    path('saved/<int:candidate_id>/', GuardianUnsaveView.as_view(), name='unsave'),
    path('forward/', GuardianForwardView.as_view(), name='forward'),
    path('forward/<int:candidate_id>/', GuardianForwardDetailView.as_view(), name='forward-detail'),
    path('received/', GuardianReceivedView.as_view(), name='received'),
    path('received/<int:forwarded_id>/action/', GuardianReceivedActionView.as_view(), name='received-action'),
    path('delete-account/', GuardianDeleteAccountView.as_view(), name='delete-account'),
]