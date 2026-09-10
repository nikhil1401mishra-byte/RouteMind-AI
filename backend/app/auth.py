"""Server-side identity, roles and authorization.

Four roles, one permission matrix, enforced in the API layer before any state
change happens. The frontend never decides what an operator may do - it only
reflects what the server already allows. A forged `role` field from the browser
changes nothing, because the role is read from the session, not the request body.

Two modes, selected with ROUTEMIND_AUTH:

  demo   (default) Unauthenticated requests resolve to the seeded dispatcher so
         the control room opens without a login screen. Role checks are STILL
         enforced; the X-RouteMind-Role header switches the acting role so you
         can demonstrate a real 403 during a review.
  strict Every mutating request requires a session token from
         POST /api/auth/login. Passwords must be supplied through environment
         variables; nothing is hardcoded.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from . import config
from .db import new_id, repo

ROLES = ("admin", "dispatcher", "field_officer", "logistics_manager")

ROLE_LABEL = {
    "admin": "Admin",
    "dispatcher": "Dispatcher",
    "field_officer": "Field Officer",
    "logistics_manager": "Logistics Manager",
}

# The whole authorization policy, in one readable place.
PERMISSIONS: Dict[str, Tuple[str, ...]] = {
    "incident.create":        ("admin", "dispatcher", "field_officer", "logistics_manager"),
    "incident.set_status":    ("admin", "dispatcher", "field_officer"),
    "alert.action":           ("admin", "dispatcher", "logistics_manager"),
    "alert.acknowledge_all":  ("admin", "dispatcher"),
    "route.plan":             ("admin", "dispatcher", "logistics_manager"),
    "simulation.start":       ("admin", "dispatcher", "logistics_manager"),
    "simulation.accept":      ("admin", "dispatcher"),
    "simulation.decline":     ("admin", "dispatcher"),
    "simulation.reset":       ("admin", "dispatcher"),
    "inventory.transfer":     ("admin", "logistics_manager"),
    "user.manage":            ("admin",),
}

PBKDF2_ROUNDS = 200_000
ANONYMOUS = {"user_id": None, "username": "anonymous", "full_name": "Anonymous",
             "role": None, "authenticated": False, "mode": "strict"}

# Seeded operator accounts. Passwords are NEVER stored in source: each account
# only accepts a password login when the matching environment variable is set.
SEED_USERS = (
    ("USR-ADMIN", "admin", "A. Baruah", "admin", "ROUTEMIND_PASSWORD_ADMIN"),
    ("USR-DISPATCH", "dispatcher", "K. Lalrinawma", "dispatcher", "ROUTEMIND_PASSWORD_DISPATCHER"),
    ("USR-FIELD", "field", "S. Debbarma", "field_officer", "ROUTEMIND_PASSWORD_FIELD"),
    ("USR-LOGISTICS", "logistics", "M. Sangma", "logistics_manager", "ROUTEMIND_PASSWORD_LOGISTICS"),
)


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------------ passwords
def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), PBKDF2_ROUNDS)
    return digest.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    if not stored_hash or not salt:
        return False
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored_hash)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- users
def ensure_seed_users() -> None:
    """Create the four operator accounts if they do not exist yet."""
    users = repo("users")
    for user_id, username, full_name, role, env_var in SEED_USERS:
        password = os.environ.get(env_var, "").strip()
        existing = users.get(user_id)
        record: Dict[str, Any] = {
            "id": user_id,
            "username": username,
            "full_name": full_name,
            "email": username + "@routemind.local",
            "role": role,
            "active": True,
        }
        if password:
            pw_hash, salt = hash_password(password)
            record["password_hash"] = pw_hash
            record["password_salt"] = salt
            record["login_enabled"] = True
        elif existing:
            continue                      # leave an existing account untouched
        else:
            record["login_enabled"] = False
        users.upsert(record)


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    return repo("users").get(user_id)


def user_by_username(username: str) -> Optional[Dict[str, Any]]:
    rows = repo("users").all("username = ?", (username,))
    return rows[0] if rows else None


def login_available() -> bool:
    """True when at least one account has a password configured."""
    return repo("users").count("login_enabled = ?", (True,)) > 0


# ------------------------------------------------------------------- sessions
def authenticate(username: str, password: str) -> Dict[str, Any]:
    user = user_by_username((username or "").strip())
    if not user or not user.get("active"):
        raise AuthError(401, "Unknown or inactive account")
    if not user.get("login_enabled"):
        raise AuthError(
            403,
            "Password login is not configured for '" + username + "'. Set the "
            "matching ROUTEMIND_PASSWORD_* environment variable and restart.",
        )
    if not verify_password(password or "", user.get("password_hash") or "",
                           user.get("password_salt") or ""):
        raise AuthError(401, "Incorrect password")
    return user


def create_session(user_id: str, user_agent: str = "") -> Tuple[str, float]:
    token = secrets.token_urlsafe(32)
    expires = time.time() + config.SESSION_TTL
    repo("sessions").insert({
        "token_hash": _token_hash(token),
        "user_id": user_id,
        "created_at": time.time(),
        "expires_at": expires,
        "user_agent": (user_agent or "")[:200],
    })
    return token, expires


def destroy_session(token: str) -> bool:
    if not token:
        return False
    return repo("sessions").delete(_token_hash(token))


def purge_expired_sessions() -> int:
    sessions = repo("sessions")
    stale = sessions.all("expires_at < ?", (time.time(),))
    for row in stale:
        sessions.delete(row["token_hash"])
    return len(stale)


def resolve_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    row = repo("sessions").get(_token_hash(token))
    if not row:
        return None
    if float(row.get("expires_at") or 0) < time.time():
        repo("sessions").delete(row["token_hash"])
        return None
    user = get_user(row["user_id"])
    if not user or not user.get("active"):
        return None
    principal = _principal(user, True, config.AUTH_MODE)
    principal["session_expires_at"] = row.get("expires_at")
    return principal


# ------------------------------------------------------------------ principal
def _principal(user: Dict[str, Any], authenticated: bool, mode: str) -> Dict[str, Any]:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "role_label": ROLE_LABEL.get(user["role"], user["role"]),
        "authenticated": authenticated,
        "mode": mode,
    }


def principal_from_headers(headers: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Resolve who is making this request. Never trusts a role from the body."""
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    mode = config.AUTH_MODE

    token = ""
    raw = headers.get("authorization") or ""
    if raw.lower().startswith("bearer "):
        token = raw[7:].strip()
    token = token or headers.get("x-routemind-token", "").strip()

    if token:
        principal = resolve_token(token)
        if principal:
            return principal
        raise AuthError(401, "Session expired or invalid. Sign in again.")

    if mode == "strict":
        return dict(ANONYMOUS)

    # Demo mode: act as the dispatcher unless a role is explicitly requested.
    requested = (headers.get("x-routemind-role") or "").strip().lower()
    role = requested if requested in ROLES else "dispatcher"
    match = [u for u in repo("users").all("role = ?", (role,))]
    if not match:
        ensure_seed_users()
        match = [u for u in repo("users").all("role = ?", (role,))]
    if not match:                                            # pragma: no cover
        raise AuthError(500, "No operator account exists for role " + role)
    return _principal(match[0], False, mode)


def can(principal: Optional[Dict[str, Any]], action: str) -> bool:
    if not principal or not principal.get("role"):
        return False
    allowed = PERMISSIONS.get(action)
    if allowed is None:
        return True                       # unlisted actions are reads
    return principal["role"] in allowed


def require(principal: Optional[Dict[str, Any]], action: str) -> None:
    """Raise AuthError unless the principal holds the permission."""
    if principal and principal.get("role") and can(principal, action):
        return
    if not principal or not principal.get("role"):
        audit(principal, action, allowed=False, detail={"reason": "unauthenticated"})
        raise AuthError(401, "Sign in to perform this action.")
    allowed = PERMISSIONS.get(action, ())
    audit(principal, action, allowed=False, detail={"reason": "role_denied"})
    raise AuthError(
        403,
        ROLE_LABEL.get(principal["role"], principal["role"])
        + " is not permitted to " + action.replace(".", " ")
        + ". Allowed roles: " + ", ".join(ROLE_LABEL.get(r, r) for r in allowed) + ".",
    )


def permissions_for(principal: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    return {action: can(principal, action) for action in sorted(PERMISSIONS)}


# ---------------------------------------------------------------------- audit
def audit(principal: Optional[Dict[str, Any]], action: str,
          entity_type: str = "", entity_id: str = "",
          detail: Optional[Dict[str, Any]] = None, allowed: bool = True) -> None:
    """Record who did what. Never raises - auditing must not break a request."""
    try:
        repo("audit_log").insert({
            "id": new_id("AUD"),
            "at": time.time(),
            "actor_id": (principal or {}).get("user_id"),
            "actor_role": (principal or {}).get("role"),
            "action": action,
            "entity_type": entity_type or None,
            "entity_id": entity_id or None,
            "detail_json": json.dumps(detail or {}),
            "allowed": allowed,
        })
    except Exception:                                        # pragma: no cover
        pass


def describe() -> Dict[str, Any]:
    """Auth configuration summary for /api/system/status."""
    return {
        "mode": config.AUTH_MODE,
        "enforced": True,
        "login_available": login_available(),
        "roles": list(ROLES),
        "note": (
            "Role permissions are enforced server-side in every mode. In demo "
            "mode an unauthenticated request acts as the dispatcher account."
            if config.AUTH_MODE == "demo" else
            "Strict mode: a session token is required for every state change."
        ),
    }
