from django.core.exceptions import ValidationError

# AI Onboarding field validators
VALID_CORE_VALUES = {'family', 'faith', 'respect', 'stability', 'freedom', 'career', 'kindness'}
VALID_DEALBREAKERS = {'smoking', 'drinking', 'not_serious', 'no_children'}


def validate_core_values(value):
    if not isinstance(value, list):
        raise ValidationError("Core values must be a list.")
    if len(value) > 3:
        raise ValidationError("Maximum 3 core values allowed.")
    for item in value:
        if item not in VALID_CORE_VALUES:
            raise ValidationError(f"Invalid core value: {item}. Valid options: {', '.join(VALID_CORE_VALUES)}")


def validate_dealbreakers(value):
    if not isinstance(value, list):
        raise ValidationError("Dealbreakers must be a list.")
    if len(value) > 4:
        raise ValidationError("Maximum 4 dealbreakers allowed.")
    for item in value:
        if item not in VALID_DEALBREAKERS:
            raise ValidationError(f"Invalid dealbreaker: {item}. Valid options: {', '.join(VALID_DEALBREAKERS)}")


def validate_file_size(file):
    max_size = 15 * 1024 * 1024

    if file.size > max_size:
        raise ValidationError("File size must not exceed 15 MB.")


def validate_image_type(file):
    allowed_types = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif"
    )

    if hasattr(file, 'content_type') and file.content_type not in allowed_types:
        raise ValidationError(f"Only {', '.join(allowed_types)} formats are allowed.")

    magic_bytes = {
        b'\xff\xd8\xff': 'jpeg',
        b'\x89PNG': 'png',
        b'RIFF': 'webp',
        b'\x00\x00\x00': 'heic/heif',
    }

    file.seek(0)
    header = file.read(12)
    file.seek(0)

    is_valid = False
    for magic, _ in magic_bytes.items():
        if header.startswith(magic):
            is_valid = True
            break

    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        is_valid = True

    if b'ftyp' in header:
        is_valid = True

    if not is_valid:
        raise ValidationError("Invalid image file. File content does not match allowed image formats.")


def validate_audio_file(file, max_duration_seconds=120):
    max_size = 10 * 1024 * 1024
    allowed_types = (
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
    )

    if file.size > max_size:
        raise ValidationError("Audio file size must not exceed 10 MB.")

    if hasattr(file, 'content_type') and file.content_type not in allowed_types:
        raise ValidationError("Only MP3, M4A, OGG, WAV formats are allowed.")


def validate_audio_duration(file, max_duration_seconds=120):
    import tempfile
    import os

    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.audio') as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        file.seek(0)

        audio = MutagenFile(tmp_path)
        if audio and hasattr(audio, 'info') and hasattr(audio.info, 'length'):
            duration = audio.info.length
            if duration > max_duration_seconds:
                os.unlink(tmp_path)
                raise ValidationError(f"Audio duration cannot exceed {max_duration_seconds // 60} minutes.")

        os.unlink(tmp_path)
    except ValidationError:
        raise
    except Exception:
        pass


def validate_daily_media_limit(user, media_type, max_per_day=10):
    from django.utils import timezone
    from chat.models import Message

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    count = Message.objects.filter(
        sender=user,
        message_type=media_type,
        created_at__gte=today_start
    ).count()

    if count >= max_per_day:
        raise ValidationError(f"Daily {media_type} limit reached. Maximum {max_per_day} per day.")


def validate_video_file(file):
    max_size = 50 * 1024 * 1024
    allowed_types = (
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-msvideo",
    )

    if file.size > max_size:
        raise ValidationError("Video file size must not exceed 50 MB.")

    if hasattr(file, 'content_type') and file.content_type not in allowed_types:
        raise ValidationError("Only MP4, MOV, WEBM formats are allowed.")
