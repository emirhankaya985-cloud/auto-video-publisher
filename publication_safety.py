"""Emergency route hold with narrowly-scoped, one-shot batch exception."""
import os
PAUSED_ROUTES = frozenset({"tarladaki", "penguen"})
NEW_YOUTUBE_ROUTES = frozenset({"gonle_youtube", "daily_laugh_youtube"})
NEW_META_ROUTES = frozenset({"film", "toonzone", "daily_laugh_instagram"})


def controlled_gonle_ig_test_enabled():
    return (
        os.getenv("GONLE_IG_CONTROLLED_TEST", "false").lower() == "true"
        and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.getenv("FORCE_ROUTE", "").strip().lower() == "gonle_ig"
    )


def route_paused(route):
    # Gönle and Daily are enabled per channel.  A global existing-routes
    # switch must never wake a half-configured fan-out route.
    if route == "gonle_ig":
        if controlled_gonle_ig_test_enabled():
            return False
        return os.getenv("ENABLE_GONLE_INSTAGRAM_ROUTES", "false").lower() != "true"
    if route in NEW_YOUTUBE_ROUTES:
        return os.getenv("ENABLE_NEW_YOUTUBE_ROUTES", "false").lower() != "true"
    # Daily Laugh Lab has its own Meta switch. Never let this route's
    # activation open Film/ToonZone or any other future Meta route.
    if route == "daily_laugh_instagram":
        return os.getenv("ENABLE_DAILY_LAUGH_INSTAGRAM_ROUTES", "false").lower() != "true"
    if route == "film":
        # Film stays fail-closed until both the explicit route switch and
        # rights approval are present.  This is independent of other Meta
        # routes and cannot be opened by a global existing-routes flag.
        return not (
            os.getenv("ENABLE_FILM_ROUTES", "false").lower() == "true"
            and os.getenv("FILM_RIGHTS_APPROVED", "false").lower() == "true"
        )
    if route == "toonzone":
        return not (
            os.getenv("ENABLE_TOONZONE_ROUTES", "false").lower() == "true"
            and os.getenv("ENABLE_NEW_META_ROUTES", "false").lower() == "true"
            and os.getenv("META_NEW_ROUTES_RIGHTS_APPROVED", "false").lower() == "true"
        )
    if route in NEW_META_ROUTES:
        return True
    base = route.removesuffix("_ig").removesuffix("_fb")
    if base == "gonle":
        return os.getenv("ENABLE_GONLE_NORMAL_ROUTES", "false").lower() != "true"
    if base == "daily_laugh":
        return os.getenv("ENABLE_DAILY_LAUGH_NORMAL_ROUTES", "false").lower() != "true"
    # Shared-humor routes have their own switch.  This deliberately avoids
    # ENABLE_EXISTING_ROUTES waking unrelated existing accounts.
    if base in PAUSED_ROUTES:
        return os.getenv("ENABLE_TP_NORMAL_ROUTES", "false").lower() != "true"
    # Existing routes can be re-enabled centrally after the owner confirms
    # the source-folder audit.  The Gönle Instagram hard stop above remains
    # unconditional until its Meta 400 is live-tested.
    if os.getenv("ENABLE_EXISTING_ROUTES", "false").lower() == "true":
        return False
    return False


def require_route_enabled(route):
    if route_paused(route):
        raise RuntimeError(f"Yayın rotası içerik denetimi için duraklatıldı: {route}")

def batch_exception_allowed(route):
    """Allow only an explicitly configured batch target; never normal cron/force."""
    if route in NEW_YOUTUBE_ROUTES or route == "gonle_ig":
        return False
    base = route.removesuffix("_ig").removesuffix("_fb")
    allowed = {x.strip() for x in os.getenv("BATCH_ALLOWED_ROUTES", "").split(",") if x.strip()}
    return bool(os.getenv("BATCH_ID") and os.getenv("BATCH_API_URL") and os.getenv("BATCH_API_TOKEN") and base in allowed)


def platform_allowed(account, platform):
    return True


def new_meta_route_enabled(route):
    """Whether a new Meta route may leave dry-run mode."""
    return route in NEW_META_ROUTES and not route_paused(route)
