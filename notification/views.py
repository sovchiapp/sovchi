from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, UserDevice
from .serializers import NotificationSerializer, DeviceRegisterSerializer, DeviceDeleteSerializer

MAX_ACTIVE_DEVICES = 10


class NotificationListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return (
            Notification.objects
            .filter(recipient=self.request.user)
            .select_related('actor')
            .prefetch_related('actor__photos')
        )


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({'unread_count': count})


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = request.data.get('ids')
        queryset = Notification.objects.filter(recipient=request.user, is_read=False)
        if ids:
            queryset = queryset.filter(id__in=ids)
        updated = queryset.update(is_read=True)
        return Response({'marked': updated})


class DeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        token = data['fcm_token']
        device_id = data['device_id']

        UserDevice.objects.filter(fcm_token=token).exclude(
            user=user, device_id=device_id,
        ).delete()

        device, _ = UserDevice.objects.update_or_create(
            user=user, device_id=device_id,
            defaults={
                'platform': data['platform'],
                'fcm_token': token,
                'app_version': data.get('app_version') or None,
                'locale': data.get('locale') or None,
                'is_active': True,
            },
        )

        active = list(
            UserDevice.objects.filter(user=user, is_active=True).order_by('-updated_at')
        )
        if len(active) > MAX_ACTIVE_DEVICES:
            stale_ids = [d.id for d in active[MAX_ACTIVE_DEVICES:]]
            UserDevice.objects.filter(id__in=stale_ids).update(is_active=False)

        return Response({
            'id': device.id,
            'device_id': device.device_id,
            'platform': device.platform,
            'is_active': device.is_active,
        }, status=status.HTTP_200_OK)

    def delete(self, request):
        serializer = DeviceDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserDevice.objects.filter(
            user=request.user, device_id=serializer.validated_data['device_id'],
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
