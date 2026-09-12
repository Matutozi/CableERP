from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """Session auth that answers unauthenticated requests with 401 instead of DRF's default 403.

    That lets the frontend tell "your session expired" apart from "you may not do that".
    """

    def authenticate_header(self, request):
        return "Session"
