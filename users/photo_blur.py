def photo_blur_state(photo, privacy_blur, is_owner=False):
    if is_owner:
        return False, None
    if not photo.is_approved:
        return True, 'verification'
    if privacy_blur:
        return True, 'privacy'
    return False, None