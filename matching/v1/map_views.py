from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, Subquery, FloatField
from django.db.models.functions import Coalesce
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Block
from matching.models import CompatibilityScore, Like
from matching.utils import calculate_distance, calculate_compatibility_score, is_user_boosted, can_see_online_status

User = get_user_model()


class MapUserSerializer(drf_serializers.Serializer):
    id = drf_serializers.IntegerField()
    first_name = drf_serializers.CharField()
    photo = drf_serializers.SerializerMethodField()
    latitude = drf_serializers.FloatField(source='profile.latitude')
    longitude = drf_serializers.FloatField(source='profile.longitude')
    compatibility_score = drf_serializers.IntegerField(source='compat_score')
    distance_km = drf_serializers.FloatField()

    def get_photo(self, obj):
        request = self.context.get('request')
        photo = next((p for p in obj.photos.all() if p.is_approved and p.is_primary), None)
        if not photo:
            photo = next((p for p in obj.photos.all() if p.is_approved), None)
        if photo and request:
            return request.build_absolute_uri(photo.image.url)
        elif photo:
            return photo.image.url
        return None


class MapDetailSerializer(drf_serializers.Serializer):
    id = drf_serializers.IntegerField()
    first_name = drf_serializers.CharField()
    gender = drf_serializers.CharField()
    age = drf_serializers.IntegerField()
    is_verified = drf_serializers.BooleanField()
    profile = drf_serializers.SerializerMethodField()
    photos = drf_serializers.SerializerMethodField()
    photos_count = drf_serializers.SerializerMethodField()
    compatibility_score = drf_serializers.SerializerMethodField()
    last_active = drf_serializers.SerializerMethodField()
    is_boosted = drf_serializers.SerializerMethodField()
    is_liked = drf_serializers.SerializerMethodField()
    chat_request_status = drf_serializers.SerializerMethodField()

    @staticmethod
    def get_profile(obj):
        if not hasattr(obj, 'profile'):
            return None
        p = obj.profile
        return {
            'height': p.height,
            'weight': p.weight,
            'education': p.education,
            'occupation': p.occupation,
            'marital_status': p.marital_status,
            'birthplace_region': p.birthplace_region,
            'city': p.city,
            'district': p.district,
            'follow_daily_routine': p.follow_daily_routine,
            'follow_healthy_lifestyle': p.follow_healthy_lifestyle,
            'drinking_alcohol': p.drinking_alcohol,
            'smoking_cigarettes': p.smoking_cigarettes,
            'children_preference': p.children_preference,
            'dressing_style': p.dressing_style,
            'interests': p.interests,
            'qualities': p.qualities,
            'bio': p.bio,
            'favourite_books': p.favourite_books,
            'favourite_musics': p.favourite_musics,
            'visited_countries': p.visited_countries,
            'religious_identity': p.religious_identity,
            'marriage_timeline': p.marriage_timeline,
        }

    def get_photos(self, obj):
        request = self.context.get('request')
        photos = [p for p in obj.photos.all() if p.is_approved]
        photos.sort(key=lambda x: (not x.is_primary, x.order))
        photo_urls = []
        for photo in photos:
            url = photo.image.url
            if request:
                url = request.build_absolute_uri(url)
            photo_urls.append({
                'id': photo.id,
                'url': url,
                'is_primary': photo.is_primary,
            })
        return photo_urls

    @staticmethod
    def get_photos_count(obj):
        return sum(1 for p in obj.photos.all() if p.is_approved)

    def get_compatibility_score(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        try:
            score = CompatibilityScore.objects.get(
                user=request.user,
                potential_match=obj
            )
            return {
                'overall': score.overall_score,
                'psychological': score.psychological_score,
                'lifestyle': score.lifestyle_score,
                'demographic': score.demographic_score,
            }
        except CompatibilityScore.DoesNotExist:
            scores = calculate_compatibility_score(request.user, obj)
            return {
                'overall': int(scores['overall_score']),
                'psychological': int(scores['psychological_score']),
                'lifestyle': int(scores['lifestyle_score']),
                'demographic': int(scores['demographic_score']),
            }

    def get_last_active(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        can_see, _ = can_see_online_status(request.user)
        if can_see:
            return obj.last_active
        return None

    @staticmethod
    def get_is_boosted(obj):
        boosted, boost_type = is_user_boosted(obj)
        return boosted and boost_type == 'premium'

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Like.objects.filter(user=request.user, target=obj).exists()

    def get_chat_request_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 'none'

        from chat.models import ChatRoom
        user = request.user

        if user.gender == 'M':
            room = ChatRoom.objects.filter(user1=user, user2=obj).first()
        else:
            room = ChatRoom.objects.filter(user1=obj, user2=user).first()

        if not room:
            return 'none'

        return room.status if room.status in ['active', 'pending', 'rejected'] else 'none'


class MapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.registration_completed:
            return Response({
                'error': 'Please complete your profile first'
            }, status=status.HTTP_400_BAD_REQUEST)

        user_profile = getattr(user, 'profile', None)
        if not user_profile or not user_profile.latitude or not user_profile.longitude:
            return Response({
                'error': 'Please set your location first'
            }, status=status.HTTP_400_BAD_REQUEST)

        user_lat = float(user_profile.latitude)
        user_lon = float(user_profile.longitude)

        if user.gender == 'M':
            queryset = User.objects.filter(gender='F')
        else:
            queryset = User.objects.filter(gender='M')

        queryset = queryset.filter(
            is_active=True,
            registration_completed=True,
            profile__latitude__isnull=False,
            profile__longitude__isnull=False
        ).exclude(id=user.id)

        blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
        blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
        queryset = queryset.exclude(
            Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
        )

        queryset = queryset.annotate(
            compat_score=Coalesce(
                Subquery(
                    CompatibilityScore.objects.filter(
                        user=user,
                        potential_match=OuterRef('pk')
                    ).values('overall_score')[:1]
                ),
                0,
                output_field=FloatField()
            )
        ).filter(compat_score__gte=30)

        queryset = queryset.select_related('profile').prefetch_related('photos')
        queryset = queryset.order_by('-compat_score')

        results = []
        for match in queryset:
            distance = calculate_distance(
                user_lat, user_lon,
                float(match.profile.latitude), float(match.profile.longitude)
            )
            match.distance_km = round(distance, 1) if distance else None
            results.append(match)

        serializer = MapUserSerializer(results, many=True, context={'request': request})

        return Response({
            'results': serializer.data,
            'center': {
                'latitude': user_lat,
                'longitude': user_lon
            },
            'total_count': len(results)
        })


YOUTUBE_URLS = [
    "https://youtu.be/oTvIe-j6sYA?si=eyK-t00aQWdHJ5zA",
    "https://youtube.com/shorts/RGZASrYO5Lg?si=JFqk5CNAbs8xMoB_",
    "https://youtu.be/Rd51Du7H4OE?si=ZCP6tmH4iRhSaB-H",
    "https://youtu.be/VRp64FPZHko?si=z1LbejaNP4em1L1X",
    "https://youtu.be/VzE_RguLjxE?si=ovOh8NElxWq-EtQ7",
    "https://youtu.be/_iKVImgwRJo?si=ZxpiSw11gzF6mD1A",
    "https://youtu.be/lx7hDoD6MEI?si=_A3CkW4hP_cZTBlA",
    "https://youtu.be/RSbYononK5c?si=auNVg7LhzhULlbkK",
    "https://youtu.be/Kr3nA_xeoh4?si=9l65S4Z1yX0z4NJj",
    "https://youtu.be/A9CXFPmF1sM?si=NSMSD6jqA7dn-iBq",
    "https://youtu.be/tIUq3P_BmfY?si=ycqybEvviuyvIBI0",
    "https://youtu.be/41ulI8MwvGE?si=0raiNcBXIxFTo7zu",
    "https://youtu.be/FvPG1nUmu-k?si=kmRY70QptmSLYAnd",
    "https://youtu.be/sz3PFLFsh4s?si=RqMdt0wipO1TfHRi",
    "https://youtu.be/IexIQnGTm1c?si=g5uzmVqKCPTni7bk",
    "https://youtu.be/wp_alaLxyOo?si=Bt22TUKGGyrGdnH_",
    "https://youtube.com/shorts/f0uEs_TMEvU?si=I0TPOrUeSu-DRFjM",
    "https://youtu.be/84TEeoWxgWA?si=oP8mRGmo0XuwDdmz",
    "https://youtu.be/lZoMr4hVh3E?si=SnGBc0TELUKvvOQ2",
    "https://youtu.be/OmRdRMUSRrE?si=T-sZ4am30aXt-UzD",
    "https://youtu.be/0fDYnvgSo9g?si=99AXDB5fu1FkPCKP",
    "https://youtu.be/eO13Mp2r2e8?si=AModjwc1o6uVyaoF",
    "https://youtu.be/fy_MwXLl4YQ?si=bgnvZJ8lMtZKIGxd",
    "https://youtu.be/LUtmRbK41UY?si=VUw_wUB6tVr4WjRs",
    "https://youtu.be/QT5E5VW9de0?si=UKCLCbKxpCYXo_Qi",
    "https://youtube.com/shorts/rk5Hslm_oTc?si=mHtYECpIMoYqh4Ix",
    "https://youtu.be/UFspitXWKUs?si=4qhl95kpbKq7UBtj",
    "https://youtu.be/JwdyES3ZuM8?si=_Ha9twepI6x0v7Nz",
    "https://youtu.be/ywjlYjQ8mbE?si=rEwjp0wHKnespEPh",
    "https://youtube.com/shorts/fzAb7-9_1Go?si=syfbGJWsyGYx3BMf",
    "https://youtu.be/jJQzl_GqcQ0?si=17CneOmriyoivGUR",
    "https://youtu.be/WpfBKN3Ds4Q?si=07EFOHiI66UoFipE",
    "https://youtu.be/AO_5f9Y1lBU?si=lHeLYVA2ns1sd8YT",
    "https://youtu.be/BGpy4ON2f7A?si=bzm9r-WGwpayr01p",
    "https://youtu.be/qIX8cq54l8Q?si=NAONA6PrsVptweSJ",
    "https://youtu.be/GppqY6N8oZM?si=dS7PCGPXNm3ezyOM",
    "https://youtu.be/kkioBoLKeZo?si=ZS5fKAeMdeskyLBX",
    "https://youtu.be/oiOQBiApU_Q?si=EhMgBTk7h0i0YVY4",
    "https://youtu.be/lbWxh3aglio?si=rSA74KqxrDAUXfER",
    "https://youtu.be/Z89LEBdyJWw?si=qhzSmV3ggzsrZ9p_",
    "https://youtu.be/sNeARhKJu5c?si=PiI6FIhyfZP1bNbf",
    "https://youtu.be/sMqQbKsKzcI?si=knOaULVblFecom3I",
    "https://youtu.be/BQ7AnCvRHMU?si=C11QFs0Ch1rqY-Sx",
    "https://youtu.be/Dxs7n4pu_Ps?si=fqWU-IQOs3RCS9gT",
    "https://youtu.be/KVDXPxBPtDA?si=-OIrFCTZKuyfF9Yf",
    "https://youtu.be/XM_CtWmiQfk?si=v5j64skXRM-9vmn5",
    "https://youtu.be/yx0TyfsWkNw?si=7Fd2wdnUAz2d20kV",
    "https://youtu.be/531_0tn_R00?si=TmuenIPhvfQsie-w",
    "https://youtu.be/P7JGHKpL9ao?si=WZgx7RIcIxMIvQ7r",
    "https://youtu.be/Ie918gZFpP0?si=JDxLDkqmwtQGzKMv",
    "https://youtu.be/UYmqsw6msoA?si=C3sk9JqS76PY0S5w",
    "https://youtu.be/Dy3hexm1Vc4?si=oMCzHLSG3_fcRDDf",
    "https://youtu.be/6TSxn5A2AqY?si=bWu8q5T4wyQYzwXZ",
    "https://youtu.be/s5N-9bNRnnk?si=B0mlt_J8S_n87MCM",
    "https://youtu.be/Rl_bCNMgkFY?si=D_utu75DbhOMf0ig",
    "https://youtu.be/9miwkVCfPog?si=0E37OKg0_mpN46pi",
    "https://youtube.com/shorts/tVHatl_GECA?si=Q1UReA1tyjE7R0ZR",
    "https://youtu.be/HRLZQXAfp6U?si=ecdjvdp2f25tECDF",
    "https://youtu.be/SWU5afNmp0Y?si=sdO7JND3JrW_pPeP",
    "https://youtu.be/--Vw3QRAyUg?si=l6EFjefOfN5bFMcb",
    "https://youtu.be/fjJSgwZW_3E?si=I4jbx5lmynzwQCEf",
    "https://youtu.be/08WtILzl_yE?si=zXCizVZYy71LR4YF",
    "https://youtu.be/4tgxP0gKrPc?si=MuA-MWorpbT3G7cW",
    "https://youtu.be/wNI_9PA3rTo?si=BShiMZkPmEfim6Lm",
    "https://youtu.be/DBFFf5QMX7s?si=QBM7gabamsrx9czz",
    "https://youtu.be/uONzi8dsPF0?si=IRAcu2gc8eNLBwoT",
    "https://youtu.be/QbBBAYV1R3g?si=I3n5iFg0lWf9XfcA",
    "https://youtu.be/s5sGh_CtS4k?si=V-T5mdsKxP_0hrQs",
    "https://youtu.be/ju1Y9NgJxhc?si=eVjbJ8cd5f4EosmB",
    "https://youtu.be/fVsaMhD9aaU?si=j53A0aMH9sG7a0lS",
    "https://youtu.be/1LW-hpCglJ8?si=AjcKuRKM38sVMroA",
    "https://youtu.be/hWblYycFZVk?si=R2vORWyMmlMmr_Tm",
    "https://youtu.be/2e5ndVpDksU?si=H3E_WvLFgEmWNYXK",
    "https://youtu.be/CoRYDtOwLRQ?si=Hapc5RBQnyTQV30b",
    "https://youtu.be/9nNjktPZu_8?si=ZtgzmlCuzZ0uX8YT",
    "https://youtu.be/x_qH9bQYkvw?si=6YX2uHTUOPNHbCbR",
    "https://youtu.be/_Ee23OoHm-8?si=l5kHquvEuN-3MwjV",
    "https://youtu.be/hlZQZLhYPPo?si=S7Lpp1qMFhnYxayg",
    "https://youtu.be/OkNpjv9YV5g?si=63cK9Jc0KNoqUDRg",
    "https://youtube.com/shorts/RG8IaewYaBY?si=d3aGRVdEZfxqHr24",
    "https://youtu.be/mJqaMdUlteQ?si=rH9uyD_x2ICzHI4y",
    "https://youtu.be/BV9jBWMpaNQ?si=Al74WPccmiCRaZxL",
    "https://youtu.be/9q2PTny2BMI?si=bB-IfK2oINNVl3Zg",
    "https://youtu.be/VyhQbIJUtGc?si=e_DfErCpp0zLQAMQ",
    "https://youtu.be/g6YVEeHgzPk?si=FJOG15Jyhb5NzEJ8",
    "https://youtu.be/ZxnirBZDEHM?si=cjVQFTRClUd3cCKc",
    "https://youtu.be/OTiOiSjf9N8?si=xO8iJXrEmeGsdhbv",
    "https://youtu.be/cy52xiAfgQU?si=L6G8mu4z7g43-FSw",
    "https://youtu.be/SJSfan4FNS0?si=2PmbhVP7axOQOpVB",
    "https://youtu.be/1G4RTDYbWAE?si=8EsafWvW11_3kkUX",
    "https://youtu.be/XR7-Xzaezww?si=KUygAPCF2RCmtvz6",
    "https://youtu.be/cdaJz3TCvPE?si=FU7-izU-_r8i4oFw",
    "https://www.youtube.com/live/pyPD0VeNYhE?si=S6AzL1blY526L0pm",
    "https://www.youtube.com/live/Zkd69YUvJiY?si=ofnT_aFLi0Qh7-3U",
    "https://www.youtube.com/live/j_6Ij5JCI1A?si=B_GlqL8XABey-Hr1",
    "https://www.youtube.com/live/ZdSqDXYu1ig?si=rj-r5Ym8xy6Ptz3J",
    "https://youtu.be/zivBXtW7ILw?si=XEJ8kHVUCh0kftGM",
    "https://youtu.be/qZ6cn8KsH8E?si=teJYp79V6e927ii2",
]


class YouTubeVideosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'videos': YOUTUBE_URLS,
            'total': len(YOUTUBE_URLS)
        })


class MapDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = request.user

        if user.gender == 'M':
            queryset = User.objects.filter(gender='F')
        else:
            queryset = User.objects.filter(gender='M')

        queryset = queryset.filter(
            id=user_id,
            is_active=True,
            registration_completed=True
        )

        blocked_by_me = Block.objects.filter(blocker=user, blocked=OuterRef('pk'))
        blocked_me = Block.objects.filter(blocker=OuterRef('pk'), blocked=user)
        queryset = queryset.exclude(
            Q(Exists(blocked_by_me)) | Q(Exists(blocked_me))
        )

        queryset = queryset.select_related(
            'profile'
        ).prefetch_related('photos')

        instance = queryset.first()
        if not instance:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = MapDetailSerializer(instance, context={'request': request})
        return Response(serializer.data)
