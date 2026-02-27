from django.urls import re_path
from .consumers import NotificationsConsumer, ChatConsumer

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", NotificationsConsumer.as_asgi()),
    re_path(r"ws/chat/$", ChatConsumer.as_asgi()),
]
