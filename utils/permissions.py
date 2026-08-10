from rest_framework.permissions import BasePermission

from admin_panel.models import PERMISSION_FULL, PERMISSION_READ


class IsSuperUser(BasePermission):
    message = "Only superuser admins can access this endpoint."

    def has_permission(self, request, view):
        return (
                request.user and
                request.user.is_authenticated and
                request.user.is_superuser
        )


class IsAdminPanelUser(BasePermission):
    message = "admin_panel_access_required"

    def has_permission(self, request, view):
        return hasattr(request, 'admin_user') and bool(request.admin_user)


class AdminPermission(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False

        if not admin_user.is_active:
            self.message = "account_deactivated"
            return False

        area = getattr(view, 'permission_area', None)
        level = getattr(view, 'permission_level', PERMISSION_READ)

        if not area:
            return True

        if not admin_user.has_permission(area, level):
            self.message = "permission_denied"
            return False

        return True


def require_permission(area, level=PERMISSION_READ):
    class AreaPermission(BasePermission):
        message = "permission_denied"

        def has_permission(self, request, view):
            admin_user = getattr(request, 'admin_user', None)
            if not admin_user:
                self.message = "not_authenticated"
                return False

            if not admin_user.is_active:
                self.message = "account_deactivated"
                return False
            return admin_user.has_permission(area, level)

    return AreaPermission


class CanViewFinancials(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('financials', PERMISSION_READ)


class CanManageFinancials(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('financials', PERMISSION_FULL)


class CanViewAnalytics(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return (
                admin_user.has_permission('user_funnel', PERMISSION_READ) or
                admin_user.has_permission('drop_off_analytics', PERMISSION_READ) or
                admin_user.has_permission('marketing_distribution', PERMISSION_READ)
        )


class CanViewVerification(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('verification_queue', PERMISSION_READ)


class CanManageVerification(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('verification_queue', PERMISSION_FULL)


class CanViewUsers(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('user_management', PERMISSION_READ)


class CanManageUsers(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('user_management', PERMISSION_FULL)


class CanViewChats(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('chats', PERMISSION_READ)


class CanManageChats(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('chats', PERMISSION_FULL)


class CanViewSupport(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('support', PERMISSION_READ)


class CanManageSupport(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('support', PERMISSION_FULL)


class CanViewBroadcast(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('broadcast', PERMISSION_READ)


class CanManageBroadcast(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('broadcast', PERMISSION_FULL)


class CanAccessAdminAI(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        if not admin_user.is_active:
            self.message = "account_deactivated"
            return False
        return admin_user.role in ['founder', 'dev_tech_ops']


class CanViewCommunity(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('community', PERMISSION_READ)


class CanManageCommunity(BasePermission):
    message = "permission_denied"

    def has_permission(self, request, view):
        admin_user = getattr(request, 'admin_user', None)
        if not admin_user:
            self.message = "not_authenticated"
            return False
        return admin_user.has_permission('community', PERMISSION_FULL)
