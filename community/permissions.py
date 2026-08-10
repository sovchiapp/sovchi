from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsCommunityMember(BasePermission):
    message = "community_membership_required"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            self.message = "not_authenticated"
            return False

        profile = getattr(user, 'community_profile', None)
        if profile is None:
            self.message = "community_membership_required"
            return False
        if not profile.is_active:
            self.message = "community_banned" if profile.deactivated_by_admin else "community_access_revoked"
            return False
        return True


class IsPostAuthor(BasePermission):
    message = "not_post_author"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.author.user_id == request.user.id


class IsCommentAuthor(BasePermission):
    message = "not_comment_author"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.author.user_id == request.user.id