"""Rate limiting middleware via slowapi.

Provides a shared Limiter instance with key_func=get_remote_address.
Attached to the FastAPI app in main.py via app.state.limiter + SlowAPIMiddleware.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
