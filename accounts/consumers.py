import jwt
from django.conf import settings
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import UntypedToken
from urllib.parse import parse_qs
from .models import ChatThread

User = get_user_model()

class NotificationsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        query = parse_qs(self.scope["query_string"].decode())
        token = query.get("token")

        if not token:
            await self.close()
            return

        try:
            UntypedToken(token[0])
            decoded = jwt.decode(
                token[0],
                settings.SECRET_KEY,
                algorithms=["HS256"],
            )
            self.user = await User.objects.aget(id=decoded["user_id"])
        except Exception:
            await self.close()
            return

        self.group_name = f"user_{self.user.id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

    async def notify(self, event):
        await self.send_json(event["data"])


class ChatConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = None
        self.user = None

    @database_sync_to_async
    def _get_user(self, user_id):
        return User.objects.select_related("profile").get(id=user_id)

    async def connect(self):
        query = parse_qs(self.scope["query_string"].decode())
        token = query.get("token")

        if not token:
            await self.close()
            return

        try:
            UntypedToken(token[0])
            decoded = jwt.decode(
                token[0],
                settings.SECRET_KEY,
                algorithms=["HS256"],
            )
            self.user = await self._get_user(decoded["user_id"])
        except Exception:
            await self.close()
            return

        self.group_name = f"chat_user_{self.user.id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    async def chat_message(self, event):
        await self.send_json(event["data"])

    @database_sync_to_async
    def _get_thread_participants(self, thread_id):
        thread = ChatThread.objects.prefetch_related("participants").get(
            id=thread_id
        )
        return thread, list(thread.participants.all())

    async def receive_json(self, content, **kwargs):
        if content.get("event") != "typing":
            return

        thread_id = content.get("thread_id")
        if not thread_id:
            return

        try:
            thread, participants = await self._get_thread_participants(thread_id)
        except ChatThread.DoesNotExist:
            return

        if self.user not in participants:
            return

        is_typing = bool(content.get("is_typing", True))
        display_name = (
            self.user.profile.name
            if hasattr(self.user, "profile") and self.user.profile.name
            else self.user.username
        )

        payload = {
            "event": "typing",
            "thread_id": thread.id,
            "user_id": self.user.id,
            "user_name": display_name,
            "is_typing": is_typing,
        }

        for user in participants:
            await self.channel_layer.group_send(
                f"chat_user_{user.id}",
                {"type": "chat_message", "data": payload},
            )
