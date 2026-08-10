from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Q, Exists, OuterRef, Subquery, FloatField
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from matching.models import CompatibilityScore, Match
from matching.views import build_queryset_without_swipe_filter
from notification.services import create_notification
from users.models import Preferences
from .models import Guardianship, GuardianSeen, SavedCandidate, ForwardedCandidate
from .serializers import ChildPreviewSerializer, GuardianConnectSerializer, GuardianRequestSerializer, \
    GuardianActionSerializer, GuardianChildSerializer, GuardianCandidateSerializer, SaveCandidateSerializer, \
    ForwardCandidateSerializer, ForwardNoteSerializer, ReceivedActionSerializer, ForwardedItemSerializer, \
    ReceivedItemSerializer, SeenSerializer, GuardianDeleteSerializer, GuardianPreferencesSerializer, \
    GuardianChildDetailSerializer

User = get_user_model()

DISCOVERY_PAGE_SIZE = 15


class IsGuardian(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.account_type == 'guardian'


def _guardian_child(guardian):
    guardianship = Guardianship.objects.filter(
        guardian=guardian, child_approved=True, is_active=True,
    ).select_related('child').first()
    return guardianship.child if guardianship else None


def _apply_candidate_filters(queryset, filt):
    if filt is None:
        return queryset

    today = timezone.localdate()

    if filt.age_min is not None:
        queryset = queryset.filter(
            date_of_birth__lte=date(today.year - filt.age_min, today.month, today.day)
        )
    if filt.age_max is not None:
        queryset = queryset.filter(
            date_of_birth__gte=date(today.year - filt.age_max, today.month, today.day)
        )

    if filt.weight_min:
        queryset = queryset.filter(profile__weight__gte=filt.weight_min)
    if filt.weight_max:
        queryset = queryset.filter(profile__weight__lte=filt.weight_max)

    if filt.height_min:
        queryset = queryset.filter(profile__height__gte=filt.height_min)
    if filt.height_max:
        queryset = queryset.filter(profile__height__lte=filt.height_max)

    if filt.education_min_plural:
        queryset = queryset.filter(profile__education__in=filt.education_min_plural)
    if filt.marital_status_pref:
        queryset = queryset.filter(profile__marital_status__in=filt.marital_status_pref)
    if filt.religious_identity_pref:
        queryset = queryset.filter(profile__religious_identity=filt.religious_identity_pref)
    if filt.children_preference_pref:
        queryset = queryset.filter(profile__children_preference=filt.children_preference_pref)
    if filt.birthplace_region_pref:
        queryset = queryset.filter(profile__birthplace_region=filt.birthplace_region_pref)

    return queryset


def _find_child(q):
    return User.objects.filter(
        public_id__iexact=q,
        account_type='user',
        registration_completed=True,
        deletion_requested_at__isnull=True,
    ).first()


class GuardianChildSearchView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if not q:
            return Response({'error': 'query_required'}, status=status.HTTP_400_BAD_REQUEST)

        child = _find_child(q)
        if not child or child.id == request.user.id:
            return Response({'error': 'child_not_found'}, status=status.HTTP_404_NOT_FOUND)

        return Response(ChildPreviewSerializer(child).data)


class GuardianConnectView(APIView):
    permission_classes = [IsGuardian]

    def post(self, request):
        serializer = GuardianConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        child_id = serializer.validated_data['child_id']
        relation = serializer.validated_data['relation']
        guardian = request.user

        if child_id == guardian.id:
            return Response({'error': 'cannot_connect_self'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            child = User.objects.get(
                id=child_id,
                account_type='user',
                registration_completed=True,
                deletion_requested_at__isnull=True,
            )
        except User.DoesNotExist:
            return Response({'error': 'child_not_found'}, status=status.HTTP_404_NOT_FOUND)

        guardianship, created = Guardianship.objects.get_or_create(
            guardian=guardian, child=child,
            defaults={'relation': relation},
        )
        if not created:
            return Response({
                'id': guardianship.id,
                'child_approved': guardianship.child_approved,
                'status': 'already_requested',
            }, status=status.HTTP_200_OK)

        create_notification(
            recipient_id=child.id,
            actor_id=guardian.id,
            type='guardian_request',
            target_id=guardianship.id,
        )

        return Response({
            'id': guardianship.id,
            'child_approved': False,
            'status': 'request_sent',
        }, status=status.HTTP_201_CREATED)


class GuardianListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = GuardianRequestSerializer

    def get_queryset(self):
        return Guardianship.objects.filter(
            child=self.request.user,
        ).select_related('guardian').order_by('-child_approved', '-created_at')


class GuardianRequestActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, guardianship_id):
        serializer = GuardianActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']

        try:
            guardianship = Guardianship.objects.get(
                id=guardianship_id,
                child=request.user,
            )
        except Guardianship.DoesNotExist:
            return Response({'error': 'guardianship_not_found'}, status=status.HTTP_404_NOT_FOUND)

        if action == 'approve':
            if guardianship.child_approved:
                return Response({'error': 'already_approved'}, status=status.HTTP_400_BAD_REQUEST)
            guardianship.child_approved = True
            guardianship.approved_at = timezone.now()
            guardianship.save(update_fields=['child_approved', 'approved_at', 'updated_at'])

            from notification.tasks import push_guardian
            push_guardian.delay(guardianship.guardian_id, request.user.id, 'guardian_approved', guardianship.id)

            return Response({'status': 'approved'})

        if action == 'reject':
            if guardianship.child_approved:
                return Response({'error': 'already_approved'}, status=status.HTTP_400_BAD_REQUEST)
            guardianship.delete()
            return Response({'status': 'rejected'})

        guardianship.delete()
        return Response({'status': 'removed'})


class GuardianChildrenView(ListAPIView):
    permission_classes = [IsGuardian]
    serializer_class = GuardianChildSerializer

    def get_queryset(self):
        return Guardianship.objects.filter(
            guardian=self.request.user,
        ).select_related('child').order_by('-child_approved', '-created_at')


class GuardianChildDetailView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        guardianship = Guardianship.objects.filter(
            guardian=request.user, child_approved=True, is_active=True,
        ).select_related('child', 'child__profile').prefetch_related('child__photos').first()
        if guardianship is None:
            return Response({'error': 'no_approved_child'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = GuardianChildDetailSerializer(
            guardianship.child,
            context={'request': request, 'relation': guardianship.relation},
        )
        return Response(serializer.data)


class GuardianDisconnectView(APIView):
    permission_classes = [IsGuardian]

    def post(self, request, guardianship_id):
        deleted, _ = Guardianship.objects.filter(
            id=guardianship_id, guardian=request.user,
        ).delete()
        if not deleted:
            return Response({'error': 'guardianship_not_found'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'status': 'disconnected'})


class GuardianDiscoveryView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        guardian = request.user
        guardianship = Guardianship.objects.filter(
            guardian=guardian, child_approved=True, is_active=True,
        ).select_related('child').first()
        if guardianship is None:
            return Response({'error': 'no_approved_child'}, status=status.HTTP_400_BAD_REQUEST)
        child = guardianship.child

        queryset = build_queryset_without_swipe_filter(child).filter(account_type='user')

        already_seen = GuardianSeen.objects.filter(
            guardian=guardian, child=child, candidate=OuterRef('pk'),
        )
        queryset = queryset.exclude(Exists(already_seen))

        matched_1 = Match.objects.filter(user1=child, user2=OuterRef('pk'))
        matched_2 = Match.objects.filter(user1=OuterRef('pk'), user2=child)
        queryset = queryset.exclude(Q(Exists(matched_1)) | Q(Exists(matched_2)))

        candidate_filter = Preferences.objects.filter(user=guardian).first()
        queryset = _apply_candidate_filters(queryset, candidate_filter)

        queryset = queryset.annotate(
            compat_score=Coalesce(
                Subquery(
                    CompatibilityScore.objects.filter(
                        user=child, potential_match=OuterRef('pk'),
                    ).values('overall_score')[:1]
                ),
                0.0,
                output_field=FloatField(),
            )
        ).order_by('-compat_score', '-id')

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1

        total = queryset.count()
        total_pages = (total + DISCOVERY_PAGE_SIZE - 1) // DISCOVERY_PAGE_SIZE
        offset = (page - 1) * DISCOVERY_PAGE_SIZE
        candidates = list(queryset[offset:offset + DISCOVERY_PAGE_SIZE])

        forwarded_ids = set(
            ForwardedCandidate.objects.filter(
                guardian=guardian, child=child, candidate__in=candidates,
            ).values_list('candidate_id', flat=True)
        )
        saved_ids = set(
            SavedCandidate.objects.filter(
                guardian=guardian, child=child, candidate__in=candidates,
            ).values_list('candidate_id', flat=True)
        )

        serializer = GuardianCandidateSerializer(
            candidates, many=True,
            context={'request': request, 'saved_ids': saved_ids, 'forwarded_ids': forwarded_ids},
        )
        return Response({
            'page': page,
            'page_size': DISCOVERY_PAGE_SIZE,
            'total': total,
            'total_pages': total_pages,
            'results': serializer.data,
        })


class GuardianSavedView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        guardian = request.user
        child = _guardian_child(guardian)
        if child is None:
            return Response({'results': []})

        saved = SavedCandidate.objects.filter(
            guardian=guardian, child=child,
        ).select_related('candidate__profile').prefetch_related('candidate__photos').order_by('-created_at')
        candidates = [item.candidate for item in saved]

        forwarded_ids = set(
            ForwardedCandidate.objects.filter(
                guardian=guardian, child=child, candidate__in=candidates,
            ).values_list('candidate_id', flat=True)
        )

        serializer = GuardianCandidateSerializer(
            candidates, many=True,
            context={
                'request': request,
                'saved_ids': {c.id for c in candidates},
                'forwarded_ids': forwarded_ids,
            },
        )
        return Response({'results': serializer.data})

    def post(self, request):
        serializer = SaveCandidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate_id = serializer.validated_data['candidate_id']

        guardian = request.user
        child = _guardian_child(guardian)
        if child is None:
            return Response({'error': 'no_approved_child'}, status=status.HTTP_400_BAD_REQUEST)

        candidate = User.objects.filter(
            id=candidate_id, account_type='user', registration_completed=True, is_active=True,
        ).first()
        if candidate is None or candidate.id == child.id:
            return Response({'error': 'candidate_not_found'}, status=status.HTTP_404_NOT_FOUND)

        SavedCandidate.objects.get_or_create(guardian=guardian, child=child, candidate=candidate)
        return Response({'status': 'saved'}, status=status.HTTP_201_CREATED)


class GuardianUnsaveView(APIView):
    permission_classes = [IsGuardian]

    def delete(self, request, candidate_id):
        guardian = request.user
        child = _guardian_child(guardian)
        if child is not None:
            SavedCandidate.objects.filter(
                guardian=guardian, child=child, candidate_id=candidate_id,
            ).delete()
        return Response({'status': 'unsaved'})


class GuardianDeleteAccountView(APIView):
    permission_classes = [IsGuardian]

    def post(self, request):
        serializer = GuardianDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.is_active = False
        user.deletion_requested_at = timezone.now()
        user.deletion_reason = 'not_specified'
        user.deletion_note = serializer.validated_data.get('deletion_note') or None
        user.save(update_fields=[
            'is_active', 'deletion_requested_at', 'deletion_reason', 'deletion_note', 'updated_at',
        ])
        return Response({'status': 'deletion_requested'})


class GuardianFilterView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        preferences, _ = Preferences.objects.get_or_create(user=request.user)
        return Response(GuardianPreferencesSerializer(preferences).data)

    def put(self, request):
        preferences, _ = Preferences.objects.get_or_create(user=request.user)
        serializer = GuardianPreferencesSerializer(preferences, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class GuardianSeenView(APIView):
    permission_classes = [IsGuardian]

    def post(self, request):
        serializer = SeenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate_id = serializer.validated_data['candidate_id']

        guardian = request.user
        child = _guardian_child(guardian)
        if child is None:
            return Response({'error': 'no_approved_child'}, status=status.HTTP_400_BAD_REQUEST)

        GuardianSeen.objects.get_or_create(
            guardian=guardian, child=child, candidate_id=candidate_id,
        )
        return Response({'status': 'ok'})


class GuardianForwardView(APIView):
    permission_classes = [IsGuardian]

    def get(self, request):
        guardian = request.user
        child = _guardian_child(guardian)
        if child is None:
            return Response({'results': []})

        forwarded = ForwardedCandidate.objects.filter(
            guardian=guardian, child=child,
        ).select_related('candidate__profile').prefetch_related('candidate__photos').order_by('-created_at')

        serializer = ForwardedItemSerializer(forwarded, many=True, context={'request': request})
        return Response({'results': serializer.data})

    def post(self, request):
        serializer = ForwardCandidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate_id = serializer.validated_data['candidate_id']
        note = serializer.validated_data.get('note', '')

        guardian = request.user
        guardianship = Guardianship.objects.filter(
            guardian=guardian, child_approved=True, is_active=True,
        ).select_related('child').first()
        if guardianship is None:
            return Response({'error': 'no_approved_child'}, status=status.HTTP_400_BAD_REQUEST)
        child = guardianship.child

        candidate = User.objects.filter(
            id=candidate_id, account_type='user', registration_completed=True, is_active=True,
        ).first()
        if candidate is None or candidate.id == child.id:
            return Response({'error': 'candidate_not_found'}, status=status.HTTP_404_NOT_FOUND)

        guardian_name = f"{guardian.first_name} {guardian.last_name}".strip()
        forwarded, created = ForwardedCandidate.objects.get_or_create(
            guardian=guardian, child=child, candidate=candidate,
            defaults={
                'note': note,
                'guardian_name': guardian_name,
                'guardian_relation': guardianship.relation,
            },
        )
        if not created:
            return Response({
                'id': forwarded.id, 'status': forwarded.status, 'detail': 'already_forwarded',
            }, status=status.HTTP_200_OK)

        return Response({'id': forwarded.id, 'status': 'sent'}, status=status.HTTP_201_CREATED)


class GuardianForwardDetailView(APIView):
    permission_classes = [IsGuardian]

    def patch(self, request, candidate_id):
        guardian = request.user
        child = _guardian_child(guardian)
        forwarded = None
        if child is not None:
            forwarded = ForwardedCandidate.objects.filter(
                guardian=guardian, child=child, candidate_id=candidate_id,
            ).first()
        if forwarded is None:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)

        note_serializer = ForwardNoteSerializer(data=request.data)
        note_serializer.is_valid(raise_exception=True)
        forwarded.note = note_serializer.validated_data.get('note', '')
        forwarded.save(update_fields=['note', 'updated_at'])
        return Response({'status': 'updated'})

    def delete(self, request, candidate_id):
        guardian = request.user
        child = _guardian_child(guardian)
        if child is not None:
            ForwardedCandidate.objects.filter(
                guardian=guardian, child=child, candidate_id=candidate_id,
            ).delete()
        return Response({'status': 'unsent'})


class GuardianReceivedView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReceivedItemSerializer

    def get_queryset(self):
        return ForwardedCandidate.objects.filter(
            child=self.request.user,
        ).select_related('candidate__profile').prefetch_related('candidate__photos').order_by('-created_at')


class GuardianReceivedActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, forwarded_id):
        serializer = ReceivedActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        forwarded = ForwardedCandidate.objects.filter(
            id=forwarded_id, child=request.user,
        ).first()
        if forwarded is None:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)

        if forwarded.status == 'sent':
            forwarded.status = 'viewed'
            forwarded.save(update_fields=['status', 'updated_at'])

        return Response({'status': forwarded.status})