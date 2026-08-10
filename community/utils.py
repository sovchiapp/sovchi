from django.db.models import Q

from community.models import CommunityBlock


def hidden_author_ids(profile):
    pairs = CommunityBlock.objects.filter(
        Q(blocker=profile) | Q(blocked=profile)
    ).values_list('blocker_id', 'blocked_id')

    result = set()
    for blocker_id, blocked_id in pairs:
        result.add(blocked_id if blocker_id == profile.id else blocker_id)
    return result