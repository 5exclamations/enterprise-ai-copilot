"""API-key authentication, role checks and rate limiting.

API keys are high-entropy random strings, so a plain SHA-256 digest is sufficient for
storage (no salt/slow hash needed, unlike passwords). Keys are never logged.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

ROLE_RANK = {"viewer": 0, "manager": 1, "admin": 2}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: int
    tenant_id: int
    role: str
    name: str
    email: str

    def can(self, min_role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[min_role]


class RateLimiter:
    """Sliding-window limiter. Uses Redis when REDIS_URL is set (shared across workers),
    otherwise an in-process window (fine for a single worker / tests)."""

    def __init__(self):
        self._local: dict[int, deque] = defaultdict(deque)
        self._redis = None
        url = get_settings().redis_url
        if url:
            try:
                import redis

                self._redis = redis.Redis.from_url(url, socket_timeout=0.5)
                self._redis.ping()
            except Exception:  # Redis is optional: degrade to in-process limiting
                self._redis = None

    def allow(self, user_id: int, limit: int) -> bool:
        now = time.time()
        if self._redis is not None:
            try:
                key = f"rl:{user_id}:{int(now // 60)}"
                n = self._redis.incr(key)
                if n == 1:
                    self._redis.expire(key, 70)
                return n <= limit
            except Exception:
                pass
        window = self._local[user_id]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def reset_limiter() -> None:
    global _limiter
    _limiter = None


def current_principal(x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    user = db.scalar(select(User).where(User.api_key_hash == hash_key(x_api_key), User.is_active.is_(True)))
    if user is None:
        raise HTTPException(401, "Invalid API key")
    if not get_limiter().allow(user.id, get_settings().rate_limit_per_minute):
        raise HTTPException(429, "Rate limit exceeded")
    return Principal(user.id, user.tenant_id, user.role, user.name, user.email)


def require_role(min_role: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.can(min_role):
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return p

    return dep
