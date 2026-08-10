from utils.core import core
from rest_framework.permissions import BasePermission


class HasServiceToken(BasePermission):
    message = "Invalid or missing service token."

    def has_permission(self, request, view):
        auth = request.headers.get("Authorization", "")

        if not auth.startswith("Bearer "):
            return False

        token = auth.removeprefix("Bearer ").strip()
        expected = core.LOGS_API_TOKEN

        if not expected:
            return False

        return token == expected