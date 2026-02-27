# meetrail_backend/asgi.py

import os
import django

from django.core.asgi import get_asgi_application
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# ✅ THIS MUST COME FIRST
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "meetrail_backend.settings"
)

# ✅ Explicit Django setup (VERY IMPORTANT)
django.setup()

# ✅ Now it's safe to import routing
from accounts.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()
if settings.DEBUG:
    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

application = ProtocolTypeRouter({
    "http": django_asgi_app,

    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
