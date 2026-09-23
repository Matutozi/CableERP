"""Rate limits that key on something other than the caller's IP address."""

from rest_framework.throttling import SimpleRateThrottle


class LoginUsernameThrottle(SimpleRateThrottle):
    """Limit sign-in attempts per username, alongside the per-IP limit on the same view.

    The IP throttle caps how fast one address can guess. It does nothing about the
    opposite shape of attack: many addresses, each trying a handful of passwords
    against one account. Keying on the username being attempted closes that.

    Deliberately a throttle and not a lockout. Locking an account after N failures
    hands an attacker a denial-of-service primitive — anyone who knows a username
    could keep the owner out indefinitely. Slowing attempts costs an attacker far
    more than it costs the real user, and cannot be weaponised against them.
    """

    scope = "login_username"

    def get_cache_key(self, request, view):
        username = str(request.data.get("username") or "").strip().lower()
        if not username:
            # Nothing to key on. The per-IP throttle on the same view still applies.
            return None
        return self.cache_format % {"scope": self.scope, "ident": username}
