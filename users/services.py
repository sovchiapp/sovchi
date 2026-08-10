import json
import logging
from typing import Tuple

from boto3 import client
from openai import OpenAI

from utils.core import core

logger = logging.getLogger(__name__)

PORTRAIT_PROMPT = """Siz Sovchi AI - O'zbekiston nikoh ilovasi uchun foydalanuvchi portretini yaratuvchisiz.

Foydalanuvchi ma'lumotlari:
- Ism: {name}
- Yosh: {age}
- Shahar: {city}
- Kasb: {occupation}
- Maqsad: {relationship_goal}
- Qadriyatlar: {core_values}
- Shaxsiyat turi: {personality_type}
- Ideal sherik xususiyatlari: {ideal_partner_qualities}
- Qiziqishlar: {interests}

Vazifalar:
1. 2-3 gapda foydalanuvchini tavsiflovchi tabiiy o'zbek tilidagi matn yozing. Iliq, samimiy ohangda.
2. Quyidagi tag'lardan 4 tasini tanlang va har biriga qisqa (3-5 so'z) o'zbek tilidagi description yozing.

Mavjud tag'lar (faqat shu ro'yxatdan tanlang):
{available_tags}

JSON formatda javob bering:
{{
  "portrait_text": "...",
  "portrait_tags": [
    {{"id": "tag_id", "description": "qisqa tavsif"}},
    {{"id": "tag_id", "description": "qisqa tavsif"}},
    {{"id": "tag_id", "description": "qisqa tavsif"}},
    {{"id": "tag_id", "description": "qisqa tavsif"}}
  ]
}}"""

PERSONALITY_MAP = {
    'calm_thinker': 'tinch va o\'ylanadigan',
    'emotional': 'his-tuyg\'uli',
    'adaptive': 'moslashuvchan'
}

RELATIONSHIP_GOAL_MAP = {
    'serious': 'jiddiy munosabat',
    'casual': 'tanishish',
    'not_sure': 'hali aniq emas'
}

CORE_VALUES_MAP = {
    'family': 'oila',
    'faith': 'imon',
    'respect': 'hurmat',
    'loyalty': 'sadoqat',
    'honesty': 'halollik',
    'kindness': 'mehribonlik',
    'stability': 'barqarorlik'
}

AVAILABLE_TAGS = {
    'family': {'emoji': '🏠', 'label': 'Oilaviy'},
    'faith': {'emoji': '🕌', 'label': 'Diniy'},
    'loyal': {'emoji': '🤝', 'label': 'Sadoqatli'},
    'kind': {'emoji': '💝', 'label': 'Mehribon'},
    'honest': {'emoji': '🌟', 'label': 'Halol'},
    'stable': {'emoji': '⚓', 'label': 'Barqaror'},
    'respectful': {'emoji': '🙏', 'label': 'Hurmatli'},
    'calm': {'emoji': '🧘', 'label': 'Tinch'},
    'emotional': {'emoji': '🎭', 'label': 'His-tuyg\'uli'},
    'adaptive': {'emoji': '🔄', 'label': 'Moslashuvchan'},
    'serious': {'emoji': '💍', 'label': 'Jiddiy'},
    'open': {'emoji': '💬', 'label': 'Ochiq'},
    'educated': {'emoji': '📚', 'label': 'Ziyoli'},
    'career': {'emoji': '💼', 'label': 'Kasbdosh'},
    'healthy': {'emoji': '🏋️', 'label': 'Sog\'lom'},
    'active': {'emoji': '⚡', 'label': 'Faol'},
    'creative': {'emoji': '🎨', 'label': 'Ijodkor'},
    'traditional': {'emoji': '🏛️', 'label': 'An\'anaviy'},
    'modern': {'emoji': '✨', 'label': 'Zamonaviy'},
    'caring': {'emoji': '🫂', 'label': 'G\'amxo\'r'},
    'ambitious': {'emoji': '🎯', 'label': 'Maqsadli'},
    'patient': {'emoji': '🕰️', 'label': 'Sabr-toqatli'},
    'romantic': {'emoji': '🌹', 'label': 'Romantik'},
    'practical': {'emoji': '🔧', 'label': 'Amaliy'},
    'family_oriented': {'emoji': '👨‍👩‍👧', 'label': 'Oilaga moyil'},
}


class PortraitService:
    def __init__(self):
        self.client = OpenAI(api_key=core.OPENAI_API_KEY)
        self.model = 'gpt-4o-mini'

    def generate(self, ai_profile, user) -> dict:
        try:
            profile = getattr(user, 'profile', None)

            core_values_uz = [CORE_VALUES_MAP.get(v, v) for v in (ai_profile.core_values or [])]
            personality_uz = PERSONALITY_MAP.get(ai_profile.personality_type, ai_profile.personality_type)
            goal_uz = RELATIONSHIP_GOAL_MAP.get(ai_profile.relationship_goal, ai_profile.relationship_goal)

            available_tags_str = '\n'.join([
                f"- {tag_id}: {tag['label']}"
                for tag_id, tag in AVAILABLE_TAGS.items()
            ])

            prompt = PORTRAIT_PROMPT.format(
                name=user.first_name or 'Foydalanuvchi',
                age=self._calculate_age(user.date_of_birth),
                city=profile.city if profile else '',
                occupation=profile.occupation if profile else '',
                relationship_goal=goal_uz,
                core_values=', '.join(core_values_uz),
                personality_type=personality_uz,
                ideal_partner_qualities=', '.join(ai_profile.ideal_partner_qualities or []),
                interests=', '.join(profile.interests if profile else []),
                available_tags=available_tags_str
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=500,
                temperature=0.7
            )

            result = json.loads(response.choices[0].message.content)

            portrait_text = result.get("portrait_text", "")
            raw_tags = result.get("portrait_tags", [])

            portrait_tags = []
            for tag in raw_tags[:4]:
                tag_id = tag.get("id", "")
                if tag_id in AVAILABLE_TAGS:
                    portrait_tags.append({
                        "emoji": AVAILABLE_TAGS[tag_id]["emoji"],
                        "label": AVAILABLE_TAGS[tag_id]["label"],
                        "description": tag.get("description", "")
                    })

            return {
                "portrait_text": portrait_text,
                "portrait_tags": portrait_tags
            }

        except Exception as e:
            logger.error(f"Portrait generation failed for user {user.id}: {e}")
            return {"portrait_text": "", "portrait_tags": []}

    def _calculate_age(self, date_of_birth):
        if not date_of_birth:
            return ''
        from datetime import date
        today = date.today()
        return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))


class FaceVerificationService:
    SIMILARITY_THRESHOLD = 70
    MATCH_THRESHOLD = 80
    AUTO_APPROVE_THRESHOLD = 85

    def __init__(self):
        self.rekognition = client(
            'rekognition',
            aws_access_key_id=core.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=core.AWS_SECRET_ACCESS_KEY,
            region_name=core.AWS_REGION
        )

    def compare_faces(self, source_path: str, target_path: str) -> Tuple[bool, float]:
        try:
            with open(source_path, 'rb') as f:
                source_bytes = f.read()
            with open(target_path, 'rb') as f:
                target_bytes = f.read()

            response = self.rekognition.compare_faces(
                SourceImage={'Bytes': source_bytes},
                TargetImage={'Bytes': target_bytes},
                SimilarityThreshold=self.SIMILARITY_THRESHOLD,
                QualityFilter='AUTO'
            )

            if response['FaceMatches']:
                confidence = response['FaceMatches'][0]['Similarity']
                is_match = confidence >= self.MATCH_THRESHOLD
                logger.info(f"Face compare: match={is_match}, confidence={confidence:.1f}%")
                return is_match, confidence

            logger.info("Face compare: no matches found")
            return False, 0.0

        except Exception as e:
            logger.error(f"Face compare error: {str(e)}")
            raise

    def detect_faces(self, image_path: str) -> dict:
        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()

            response = self.rekognition.detect_faces(
                Image={'Bytes': image_bytes},
                Attributes=['DEFAULT']
            )

            face_count = len(response['FaceDetails'])

            if face_count == 0:
                return {
                    'face_count': 0,
                    'has_single_face': False,
                    'confidence': 0,
                    'error_code': 'no_face_detected'
                }

            if face_count > 1:
                return {
                    'face_count': face_count,
                    'has_single_face': False,
                    'confidence': 0,
                    'error_code': 'multiple_faces_detected'
                }

            confidence = response['FaceDetails'][0].get('Confidence', 0)
            return {
                'face_count': 1,
                'has_single_face': True,
                'confidence': confidence,
                'error_code': None
            }

        except Exception as e:
            logger.error(f"Face detect error: {str(e)}")
            return {
                'face_count': 0,
                'has_single_face': False,
                'confidence': 0,
                'error_code': 'detection_failed'
            }

    def verify_selfie_against_photos(self, selfie_path: str, photo_paths: list) -> dict:
        selfie_check = self.detect_faces(selfie_path)
        if not selfie_check['has_single_face']:
            return {
                'success': False,
                'best_match_confidence': 0,
                'matched_photo_index': None,
                'error_code': f"selfie_{selfie_check['error_code']}",
                'photo_results': []
            }

        if not photo_paths:
            return {
                'success': False,
                'best_match_confidence': 0,
                'matched_photo_index': None,
                'error_code': 'no_photos',
                'photo_results': []
            }

        best_confidence = 0.0
        best_match_index = None
        photo_results = []

        for i, photo_path in enumerate(photo_paths):
            try:

                photo_check = self.detect_faces(photo_path)
                if not photo_check['has_single_face']:
                    photo_results.append({
                        'index': i,
                        'match': False,
                        'confidence': 0,
                        'error_code': photo_check['error_code']
                    })
                    continue

                is_match, confidence = self.compare_faces(photo_path, selfie_path)

                photo_results.append({
                    'index': i,
                    'match': is_match,
                    'confidence': confidence,
                    'error_code': None
                })

                if confidence > best_confidence:
                    best_confidence = confidence
                    if is_match:
                        best_match_index = i

            except Exception as e:
                logger.error(f"Error verifying photo {i}: {str(e)}")
                photo_results.append({
                    'index': i,
                    'match': False,
                    'confidence': 0,
                    'error_code': 'comparison_failed'
                })

        success = best_match_index is not None

        return {
            'success': success,
            'best_match_confidence': best_confidence,
            'matched_photo_index': best_match_index,
            'error_code': None if success else 'no_matching_face',
            'photo_results': photo_results
        }
