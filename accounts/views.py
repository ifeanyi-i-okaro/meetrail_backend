from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Profile, OTP
from .serializers import RegisterSerializer, OTPVerifySerializer, ProfileSerializer
# accounts/views.py
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, permission_classes
User = get_user_model()


@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

@method_decorator(csrf_exempt, name='dispatch')
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            return Response({"message": "Account verified successfully!"}, status=200)
        return Response(serializer.errors, status=400)

from django.core.mail import send_mail
from django.conf import settings

class ResendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"email": "User not found"},
                status=400
            )

        OTP.objects.filter(user=user, is_used=False).update(is_used=True)

        otp = OTP.generate_otp()
        OTP.objects.create(user=user, code=otp)
        
        send_mail(
            subject="Your MeeTrail Verification Code",
            message=f"Your OTP code is {otp}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )

        return Response(
            {"message": "OTP resent successfully"},
            status=200
        )



@method_decorator(csrf_exempt, name='dispatch')
class LoginView(generics.GenericAPIView):
    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        user = authenticate(request, email=email, password=password)
        if not user:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({"error": "Account not verified"}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "email": user.email,
        })




from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Profile
from .serializers import ProfileSerializer

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # ✅ Get the currently logged-in user's profile
            profile = request.user.profile  
            
            # ✅ Pass context so URLs are built correctly
            serializer = ProfileSerializer(profile, context={"request": request})

            #print("Serialized Profile Data:", serializer.data) 
            return Response(serializer.data, status=200)
        
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=404)




from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import ProfileSerializer

class ProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def put(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(
            profile,
            data=request.data,
            partial=True,
            context={"request": request},  # ✅ this is the fix
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)



from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Profile
from .serializers import ProfileSerializer


class ProfileSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response({"results": []}, status=200)

        profiles = (
            Profile.objects
            .select_related("user")
            .filter(
                Q(name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
            )
            #.exclude(user=request.user)   # optional: don’t show yourself
        )[:30]

        serializer = ProfileSerializer(
            profiles, many=True, context={"request": request}
        )
        return Response({"results": serializer.data}, status=200)


from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Profile
from .serializers import ProfileSerializer


from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Profile
from .serializers import ProfileSerializer

class ProfileDetailView(generics.RetrieveAPIView):
    """
    Return a single profile by ID (used for viewing other users' profiles).
    """
    queryset = Profile.objects.select_related("user").prefetch_related("followers", "following")
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]   # or [AllowAny] if public profiles

    def get_serializer_context(self):
        # make sure `request` is present for is_me, is_following, URLs, etc.
        context = super().get_serializer_context()
        context["request"] = self.request
        return context



# accounts/views.py

from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Profile
from .serializers import ProfileSerializer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Notification


from .utils import send_push_notification
from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PushToken


from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PushToken


from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PushToken

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_password(request):
    password = request.data.get("password") or ""
    if request.user.check_password(password):
        return Response({"success": True})
    return Response({"success": False, "error": "Invalid password"}, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    token = request.data.get("token")

    print("📥 PUSH REGISTER REQUEST")
    print("👤 User:", request.user)
    print("📲 Token:", token)

    if not token:
        print("❌ NO TOKEN RECEIVED")
        return Response({"error": "No token"}, status=400)

    with transaction.atomic():
        obj = PushToken.objects.filter(token=token).first()
        obj.delete()
        #PushToken.objects.filter(token=token).delete()

        # Token does not exist → safe insert
        obj = PushToken.objects.create(
            user=request.user,
            token=token,
        )

        print("✅ New token created:", obj.id)
        return Response({"status": "ok", "action": "created"})






from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Profile, Notification
from .serializers import ProfileSerializer



class ProfileFollowToggleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        print("\n================ FOLLOW TOGGLE =================")
        print("➡️ Follow toggle request received")

        target = get_object_or_404(Profile, pk=pk)
        me = request.user.profile
        actor = request.user
        actor_profile = actor.profile

        print("👤 Actor user:", actor)
        print("🎯 Target user:", target.user)

        if me == target:
            print("⛔ User tried to follow themselves")
            return Response(
                {"detail": "You cannot follow yourself."},
                status=400,
            )

        # ───────── UNFOLLOW ─────────
        if me.is_following(target):
            me.unfollow(target)
            status_str = "unfollowed"
            print("🔁 UNFOLLOW action")

        # ───────── FOLLOW ─────────
        else:
            me.follow(target)
            status_str = "followed"
            print("➕ FOLLOW action")

            # Display name logic (IMPORTANT)
            display_name = (
                actor_profile.name
                if actor_profile.name
                else actor.username
            )

            avatar_url = (
                request.build_absolute_uri(
                    actor_profile.profile_picture.url
                )
                if actor_profile.profile_picture
                else None
            )
            print("avatar_url:", avatar_url)

            # ───────── Create DB notification ─────────
            notification = Notification.objects.create(
                recipient=target.user,
                actor=actor,
                type="follow",
                message="started following you",
            )

            print("🔔 Notification created:", notification.id)

            # ───────── WebSocket notify ─────────
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{target.user.id}",
                {
                    "type": "notify",
                    "data": {
                        "id": notification.id,
                        "type": "follow",
                        "message": notification.message,
                        "actor_name": display_name,
                        "actor_profile_id": actor_profile.id,
                        "actor_avatar": avatar_url,
                        "created_at": notification.created_at.isoformat(),
                    },
                },
            )

            print(f"📡 WebSocket event sent to user_{target.user.id}")

            # ───────── Push notifications ─────────
            tokens = list(
                target.user.push_tokens.values_list("token", flat=True)
            )

            print("📲 Push tokens found:", tokens)

            if tokens:
                print("🚀 Sending push notification")
                send_push_notification(
                    tokens=tokens,
                    title=display_name,
                    body="started following you",
                    data={
                        "type": "follow",
                        "profile_id": actor_profile.id,
                        "actor_name": display_name,
                        "actor_avatar": avatar_url,
                    },
                    image=avatar_url,
                )


            else:
                print("⚠️ No push tokens found")

        print("✅ Follow toggle completed")
        print("===============================================\n")

        serializer = ProfileSerializer(
            target,
            context={"request": request},
        )

        return Response(
            {"status": status_str, "profile": serializer.data},
            status=200,
        )


class ProfileFollowersListView(generics.ListAPIView):
    """
    GET /accounts/profile/<pk>/followers/
    List profiles that follow this profile.
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        profile = get_object_or_404(Profile, pk=self.kwargs["pk"])
        return profile.followers.select_related("user").prefetch_related("followers", "following")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


class ProfileFollowingListView(generics.ListAPIView):
    """
    GET /accounts/profile/<pk>/following/
    List profiles that this profile follows.
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        profile = get_object_or_404(Profile, pk=self.kwargs["pk"])
        return profile.following.select_related("user").prefetch_related("followers", "following")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


from .serializers import PasswordResetSerializer, PasswordResetConfirmSerializer

class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {"message": "Reset code sent"},
            status=200
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {"message": "Password reset successful"},
            status=200
        )




from .models import Notification
from .serializers import NotificationSerializer


from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_list(request):
    qs = Notification.objects.filter(
        recipient=request.user
    ).order_by("-created_at")
    n_type = request.query_params.get("type")
    exclude_type = request.query_params.get("exclude_type")
    if n_type:
        qs = qs.filter(type=n_type)
    if exclude_type:
        qs = qs.exclude(type=exclude_type)

    serializer = NotificationSerializer(
        qs,
        many=True,
        context={"request": request},  # ✅ THIS IS THE FIX
    )

    return Response(serializer.data)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unread_notifications_count(request):
    qs = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    )
    n_type = request.query_params.get("type")
    exclude_type = request.query_params.get("exclude_type")
    if n_type:
        qs = qs.filter(type=n_type)
    if exclude_type:
        qs = qs.exclude(type=exclude_type)
    count = qs.count()

    return Response({"count": count})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    qs = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    )
    n_type = request.query_params.get("type")
    exclude_type = request.query_params.get("exclude_type")
    if n_type:
        qs = qs.filter(type=n_type)
    if exclude_type:
        qs = qs.exclude(type=exclude_type)
    qs.update(is_read=True)

    return Response({"success": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chat_unread_counts(request):
    qs = (
        Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            type="message",
            thread__isnull=False,
            thread__is_private=False,
        )
        .values("thread_id")
        .annotate(count=Count("id"))
    )
    counts = {str(row["thread_id"]): row["count"] for row in qs}
    return Response({"counts": counts})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_thread_messages_read(request, thread_id):
    updated = Notification.objects.filter(
        recipient=request.user,
        is_read=False,
        type="message",
        thread_id=thread_id,
    ).update(is_read=True)
    thread = get_object_or_404(ChatThread, id=thread_id, participants=request.user)
    unread = ChatMessage.objects.filter(thread=thread).exclude(
        sender=request.user
    ).exclude(reads__user=request.user)
    unread_ids = list(unread.values_list("id", flat=True))
    ChatMessageRead.objects.bulk_create(
        [ChatMessageRead(message_id=m_id, user=request.user) for m_id in unread_ids],
        ignore_conflicts=True,
    )
    if unread_ids:
        channel_layer = get_channel_layer()
        payload = {
            "event": "message_read",
            "thread_id": thread.id,
            "message_ids": unread_ids,
            "reader_id": request.user.id,
        }
        for user in thread.participants.exclude(id=request.user.id):
            async_to_sync(channel_layer.group_send)(
                f"chat_user_{user.id}",
                {"type": "chat_message", "data": payload},
            )
    return Response({"success": True, "updated": updated})


# ─────────────────────────────────────────────
# Chat APIs
# ─────────────────────────────────────────────
from django.db.models import Count
from django.utils import timezone
from .models import (
    ChatThread,
    ChatMessage,
    ChatMessageDeletion,
    ChatMessageRead,
    ChatMessageReaction,
    ChatThreadClear,
    ChatThreadUserSetting,
)
from .serializers import ChatThreadSerializer, ChatMessageSerializer


class ChatThreadListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def _build_direct_key(self, user_a_id, user_b_id, is_private):
        try:
            a = int(user_a_id)
            b = int(user_b_id)
        except Exception:
            return ""
        first, second = sorted([a, b])
        return f"{first}:{second}:{1 if is_private else 0}"

    def _last_visible_message_time(self, thread, user):
        qs = thread.messages.all()
        clear = ChatThreadClear.objects.filter(thread=thread, user=user).first()
        if clear:
            qs = qs.filter(created_at__gt=clear.cleared_at)
        qs = qs.exclude(deletions__user=user)
        last = qs.order_by("-created_at").first()
        return last.created_at if last else None

    def get(self, request):
        threads = (
            ChatThread.objects.filter(participants=request.user, is_private=False)
            .prefetch_related("participants__profile")
            .order_by("-updated_at")
        )

        # De-duplicate direct threads by the other participant
        direct_map = {}
        unique_threads = []
        for t in threads:
            if t.is_group:
                # Hide cleared chats with no new messages
                clear = ChatThreadClear.objects.filter(
                    thread=t, user=request.user
                ).first()
                if clear:
                    has_new = t.messages.filter(
                        created_at__gt=clear.cleared_at
                    ).exclude(deletions__user=request.user).exists()
                    if not has_new:
                        continue
                unique_threads.append(t)
                continue
            other = t.participants.exclude(id=request.user.id).first()
            # Skip orphaned direct threads (only the current user)
            if not other:
                continue
            other_id = other.id
            clear = ChatThreadClear.objects.filter(
                thread=t, user=request.user
            ).first()
            if clear:
                has_new = t.messages.filter(
                    created_at__gt=clear.cleared_at
                ).exclude(deletions__user=request.user).exists()
                if not has_new:
                    continue

            last_time = self._last_visible_message_time(t, request.user)
            existing = direct_map.get(other_id)
            if not existing:
                direct_map[other_id] = (t, last_time)
                continue

            existing_thread, existing_last = existing
            # Prefer thread with latest visible message
            if existing_last and last_time:
                if last_time > existing_last:
                    direct_map[other_id] = (t, last_time)
            elif not existing_last and last_time:
                direct_map[other_id] = (t, last_time)
            elif not existing_last and not last_time:
                # Fall back to updated_at if no messages in either
                if t.updated_at > existing_thread.updated_at:
                    direct_map[other_id] = (t, last_time)

        unique_threads.extend([t for t, _ in direct_map.values()])

        serializer = ChatThreadSerializer(
            unique_threads, many=True, context={"request": request}
        )
        return Response(serializer.data, status=200)

    def post(self, request):
        user_id = request.data.get("user_id")
        user_ids = request.data.get("user_ids") or []
        name = (request.data.get("name") or "").strip()

        # Direct chat
        if user_id:
            other = get_object_or_404(User, id=user_id)
            is_private = bool(request.data.get("is_private"))
            direct_key = self._build_direct_key(request.user.id, other.id, is_private)
            if other.id == request.user.id:
                existing_self = (
                    ChatThread.objects.filter(
                        is_group=False,
                        is_private=is_private,
                        participants=request.user,
                    )
                    .annotate(p_count=Count("participants", distinct=True))
                    .filter(p_count=1)
                    .first()
                )
                if existing_self:
                    if direct_key and not existing_self.direct_key:
                        existing_self.direct_key = direct_key
                        existing_self.save(update_fields=["direct_key"])
                    serializer = ChatThreadSerializer(
                        existing_self, context={"request": request}
                    )
                    return Response(serializer.data, status=200)

                thread = ChatThread.objects.create(
                    is_group=False,
                    is_private=is_private,
                    created_by=request.user,
                    direct_key=direct_key,
                )
                thread.participants.set([request.user])
                serializer = ChatThreadSerializer(
                    thread, context={"request": request}
                )
                return Response(serializer.data, status=201)

            if direct_key:
                by_key = (
                    ChatThread.objects.filter(
                        is_group=False,
                        is_private=is_private,
                        direct_key=direct_key,
                        participants=request.user,
                    )
                    .filter(participants=other)
                    .distinct()
                    .first()
                )
                if by_key:
                    serializer = ChatThreadSerializer(
                        by_key, context={"request": request}
                    )
                    return Response(serializer.data, status=200)

            existing_qs = (
                ChatThread.objects.filter(
                    is_group=False,
                    is_private=is_private,
                    participants=request.user,
                )
                .filter(participants=other)
                .annotate(p_count=Count("participants", distinct=True))
                .filter(p_count=2)
                .distinct()
            )
            existing_threads = list(existing_qs)
            if existing_threads:
                best = None
                best_time = None
                for t in existing_threads:
                    if not t.direct_key and direct_key:
                        t.direct_key = direct_key
                        t.save(update_fields=["direct_key"])
                    last_time = self._last_visible_message_time(t, request.user)
                    if best is None:
                        best = t
                        best_time = last_time
                        continue
                    if best_time and last_time and last_time > best_time:
                        best = t
                        best_time = last_time
                    elif not best_time and last_time:
                        best = t
                        best_time = last_time
                    elif not best_time and not last_time:
                        if t.updated_at > best.updated_at:
                            best = t
                            best_time = last_time

                serializer = ChatThreadSerializer(
                    best, context={"request": request}
                )
                return Response(serializer.data, status=200)

        thread = ChatThread.objects.create(
            is_group=False,
            is_private=is_private,
            created_by=request.user,
            direct_key=direct_key,
        )
        thread.participants.set([request.user, other])
        serializer = ChatThreadSerializer(
            thread, context={"request": request}
        )
        return Response(serializer.data, status=201)

        # Group chat
        if isinstance(user_ids, str):
            try:
                import json as _json
                user_ids = _json.loads(user_ids)
            except Exception:
                user_ids = []

        if not user_ids or len(user_ids) < 2:
            return Response(
                {"error": "user_ids must include at least 2 users for group chat"},
                status=400,
            )

        if not name:
            return Response({"error": "Group name is required"}, status=400)

        # Only allow group members who follow the creator
        try:
            follower_ids = set(
                request.user.profile.followers.values_list("user_id", flat=True)
            )
        except Exception:
            follower_ids = set()

        normalized_ids = []
        for uid in user_ids:
            try:
                uid_int = int(uid)
            except Exception:
                continue
            if uid_int == request.user.id:
                continue
            normalized_ids.append(uid_int)

        invalid_ids = [uid for uid in normalized_ids if uid not in follower_ids]
        if invalid_ids:
            return Response(
                {"error": "You can only add followers to a group."},
                status=400,
            )

        participants = list(User.objects.filter(id__in=normalized_ids))
        if request.user not in participants:
            participants.append(request.user)

        thread = ChatThread.objects.create(
            is_group=True,
            is_private=False,
            name=name,
            created_by=request.user,
        )
        thread.participants.set(participants)
        serializer = ChatThreadSerializer(
            thread, context={"request": request}
        )
        return Response(serializer.data, status=201)


class ChatSelfThreadView(APIView):
    permission_classes = [IsAuthenticated]

    def _build_self_key(self, user_id, is_private):
        try:
            u = int(user_id)
        except Exception:
            return ""
        return f"{u}:{u}:{1 if is_private else 0}"

    def post(self, request):
        is_private = bool(request.data.get("is_private"))
        direct_key = self._build_self_key(request.user.id, is_private)

        if direct_key:
            by_key = (
                ChatThread.objects.filter(
                    is_group=False,
                    is_private=is_private,
                    direct_key=direct_key,
                    participants=request.user,
                    created_by=request.user,
                )
                .order_by("-updated_at")
                .first()
            )
            if by_key:
                serializer = ChatThreadSerializer(
                    by_key, context={"request": request}
                )
                return Response(serializer.data, status=200)

        existing = (
            ChatThread.objects.filter(
                is_group=False,
                is_private=is_private,
                participants=request.user,
                created_by=request.user,
            )
            .annotate(p_count=Count("participants", distinct=True))
            .filter(p_count=1)
            .order_by("-updated_at")
            .first()
        )
        if existing:
            if direct_key and not existing.direct_key:
                existing.direct_key = direct_key
                existing.save(update_fields=["direct_key"])
            serializer = ChatThreadSerializer(
                existing, context={"request": request}
            )
            return Response(serializer.data, status=200)

        thread = ChatThread.objects.create(
            is_group=False,
            is_private=is_private,
            created_by=request.user,
            direct_key=direct_key,
        )
        thread.participants.set([request.user])
        serializer = ChatThreadSerializer(thread, context={"request": request})
        return Response(serializer.data, status=201)


class ChatThreadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        serializer = ChatThreadSerializer(
            thread, context={"request": request}
        )
        return Response(serializer.data, status=200)


class ChatThreadDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )

        mode = request.data.get("mode", "for_me")

        if mode == "for_all":
            # For groups, only the creator can delete the group entirely
            if thread.is_group and thread.created_by_id != request.user.id:
                return Response({"error": "Not allowed"}, status=403)
            thread.delete()
            return Response({"success": True, "mode": "for_all"})

        # Default: clear chat for this user (WhatsApp-style delete chat)
        ChatThreadClear.objects.update_or_create(
            thread=thread,
            user=request.user,
            defaults={"cleared_at": timezone.now()},
        )
        Notification.objects.filter(
            recipient=request.user,
            type="message",
            thread=thread,
            is_read=False,
        ).update(is_read=True)
        return Response({"success": True, "mode": "for_me"})


class ChatThreadLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        if not thread.is_group:
            return Response({"error": "Only group chats can be left."}, status=400)

        thread.participants.remove(request.user)
        remaining = thread.participants.all()
        if not remaining.exists():
            thread.delete()
            return Response({"success": True, "mode": "left"})

        if thread.created_by_id == request.user.id:
            thread.created_by = remaining.first()
            thread.save(update_fields=["created_by"])

        return Response({"success": True, "mode": "left"})


class ChatThreadPrivacyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        if thread.is_group:
            return Response(
                {"error": "Privacy settings apply to direct chats only."},
                status=400,
            )

        is_hidden = request.data.get("is_hidden")
        is_paused = request.data.get("is_paused")

        settings, _ = ChatThreadUserSetting.objects.get_or_create(
            thread=thread, user=request.user
        )

        now = timezone.now()
        if is_hidden is not None:
            settings.is_hidden = bool(is_hidden)
            settings.hidden_at = now if settings.is_hidden else None

        if is_paused is not None:
            settings.is_paused = bool(is_paused)
            settings.paused_at = now if settings.is_paused else None

        settings.save()

        # Clear unread notifications when hiding or pausing
        if settings.is_hidden or settings.is_paused:
            Notification.objects.filter(
                recipient=request.user,
                type="message",
                thread=thread,
                is_read=False,
            ).update(is_read=True)

        return Response(
            {
                "success": True,
                "is_hidden": settings.is_hidden,
                "is_paused": settings.is_paused,
            },
            status=200,
        )


class ChatThreadUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )

        if not thread.is_group:
            return Response({"error": "Only group chats can be edited."}, status=400)

        if thread.created_by_id != request.user.id:
            return Response({"error": "Only the group creator can edit."}, status=403)

        name = request.data.get("name")
        image = request.FILES.get("image")

        if name is not None:
            thread.name = str(name).strip()
        if image is not None:
            thread.group_image = image

        thread.save()
        serializer = ChatThreadSerializer(thread, context={"request": request})
        return Response(serializer.data, status=200)


class ChatThreadMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )

        if not thread.is_group:
            return Response({"error": "Only group chats can be edited."}, status=400)

        if thread.created_by_id != request.user.id:
            return Response({"error": "Only the group creator can edit."}, status=403)

        add_ids = request.data.get("add_user_ids") or []
        remove_ids = request.data.get("remove_user_ids") or []

        if isinstance(add_ids, str):
            try:
                import json as _json
                add_ids = _json.loads(add_ids)
            except Exception:
                add_ids = []

        if isinstance(remove_ids, str):
            try:
                import json as _json
                remove_ids = _json.loads(remove_ids)
            except Exception:
                remove_ids = []

        # Only allow adding followers of the creator
        try:
            follower_ids = set(
                request.user.profile.followers.values_list("user_id", flat=True)
            )
        except Exception:
            follower_ids = set()

        normalized_add = []
        for uid in add_ids:
            try:
                uid_int = int(uid)
            except Exception:
                continue
            if uid_int == request.user.id:
                continue
            if uid_int in follower_ids:
                normalized_add.append(uid_int)

        if normalized_add:
            thread.participants.add(*normalized_add)

        normalized_remove = []
        for uid in remove_ids:
            try:
                uid_int = int(uid)
            except Exception:
                continue
            if uid_int == request.user.id:
                continue
            normalized_remove.append(uid_int)

        if normalized_remove:
            thread.participants.remove(*normalized_remove)

        thread.save()
        serializer = ChatThreadSerializer(thread, context={"request": request})
        return Response(serializer.data, status=200)


class ChatMessageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        messages = thread.messages.order_by("created_at")
        clear = ChatThreadClear.objects.filter(
            thread=thread, user=request.user
        ).first()
        if clear:
            messages = messages.filter(created_at__gt=clear.cleared_at)
        messages = messages.exclude(deletions__user=request.user)
        unread = messages.exclude(sender=request.user).exclude(
            reads__user=request.user
        )
        unread_ids = list(unread.values_list("id", flat=True))
        ChatMessageRead.objects.bulk_create(
            [ChatMessageRead(message_id=m_id, user=request.user) for m_id in unread_ids],
            ignore_conflicts=True,
        )
        if unread_ids:
            channel_layer = get_channel_layer()
            payload = {
                "event": "message_read",
                "thread_id": thread.id,
                "message_ids": unread_ids,
                "reader_id": request.user.id,
            }
            for user in thread.participants.exclude(id=request.user.id):
                async_to_sync(channel_layer.group_send)(
                    f"chat_user_{user.id}",
                    {"type": "chat_message", "data": payload},
                )
        serializer = ChatMessageSerializer(
            messages, many=True, context={"request": request}
        )
        return Response(serializer.data, status=200)

    def post(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        body = (request.data.get("body") or "").strip()
        message_type = (request.data.get("message_type") or "text").strip()
        reply_to_id = request.data.get("reply_to")
        file_obj = request.FILES.get("file")

        if message_type == "text" and not body:
            return Response({"error": "Message body is required"}, status=400)

        if message_type != "text" and not file_obj:
            return Response({"error": "File is required"}, status=400)

        if file_obj and file_obj.size > 200 * 1024 * 1024:
            return Response({"error": "File too large (max 200MB)"}, status=400)

        reply_to = None
        if reply_to_id:
          try:
              reply_to = ChatMessage.objects.get(id=reply_to_id, thread=thread)
          except ChatMessage.DoesNotExist:
              reply_to = None

        is_forwarded = bool(request.data.get("is_forwarded"))

        msg = ChatMessage.objects.create(
            thread=thread,
            sender=request.user,
            body=body,
            message_type=message_type,
            file=file_obj,
            file_name=getattr(file_obj, "name", "") if file_obj else "",
            file_size=getattr(file_obj, "size", None) if file_obj else None,
            reply_to=reply_to,
            is_forwarded=is_forwarded,
        )
        thread.updated_at = timezone.now()
        thread.save(update_fields=["updated_at"])

        msg_data = ChatMessageSerializer(
            msg, context={"request": request}
        ).data

        channel_layer = get_channel_layer()
        payload = {
            "event": "message",
            "thread_id": thread.id,
            "message": msg_data,
            "thread": {
                "id": thread.id,
                "is_group": thread.is_group,
                "is_private": thread.is_private,
                "name": thread.name,
                "updated_at": thread.updated_at.isoformat(),
            },
        }

        participants = list(thread.participants.all())
        for user in participants:
            async_to_sync(channel_layer.group_send)(
                f"chat_user_{user.id}",
                {"type": "chat_message", "data": payload},
            )

        # Notifications + push to other participants (skip for private chats)
        if not thread.is_private:
            recipients = [u for u in participants if u.id != request.user.id]
            if recipients:
                actor_profile = request.user.profile
                display_name = actor_profile.name or request.user.username
                avatar_url = (
                    request.build_absolute_uri(actor_profile.profile_picture.url)
                    if actor_profile.profile_picture
                    else None
                )

                for recipient in recipients:
                    notification = Notification.objects.create(
                        recipient=recipient,
                        actor=request.user,
                        type="message",
                        message=body[:255],
                        thread=thread,
                    )

                    async_to_sync(channel_layer.group_send)(
                        f"user_{recipient.id}",
                        {
                            "type": "notify",
                            "data": {
                                "id": notification.id,
                                "type": "message",
                                "message": notification.message,
                                "actor_name": display_name,
                                "actor_profile_id": actor_profile.id,
                                "actor_avatar": avatar_url,
                                "created_at": notification.created_at.isoformat(),
                                "thread_id": thread.id,
                            },
                        },
                    )

                tokens = list(
                    PushToken.objects.filter(user__in=recipients).values_list(
                        "token", flat=True
                    )
                )
                if tokens:
                    title = thread.name if thread.is_group else display_name
                    body_text = (
                        f"{display_name}: {body}"
                        if thread.is_group
                        else body
                    )
                    send_push_notification(
                        tokens=tokens,
                        title=title,
                        body=body_text,
                        data={
                            "type": "message",
                            "thread_id": thread.id,
                            "actor_name": display_name,
                            "actor_avatar": avatar_url,
                            "created_at": msg.created_at.isoformat(),
                        },
                        image=avatar_url,
                    )

        return Response(msg_data, status=201)


def build_reactions_for_user(message, user):
    reacted = set(
        ChatMessageReaction.objects.filter(
            message=message, user=user
        ).values_list("emoji", flat=True)
    )
    qs = (
        ChatMessageReaction.objects.filter(message=message)
        .values("emoji")
        .annotate(count=Count("id"))
    )
    return [
        {
            "emoji": row["emoji"],
            "count": row["count"],
            "reacted_by_me": row["emoji"] in reacted,
        }
        for row in qs
    ]


class ChatMessageReactionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id, message_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        message = get_object_or_404(ChatMessage, id=message_id, thread=thread)
        emoji = (request.data.get("emoji") or "").strip()
        if not emoji:
            return Response({"error": "Emoji is required"}, status=400)

        reaction = ChatMessageReaction.objects.filter(
            message=message, user=request.user
        ).first()
        if reaction:
            if reaction.emoji == emoji:
                reaction.delete()
            else:
                reaction.emoji = emoji
                reaction.save(update_fields=["emoji"])
        else:
            ChatMessageReaction.objects.create(
                message=message, user=request.user, emoji=emoji
            )

        channel_layer = get_channel_layer()
        for user in thread.participants.all():
            payload = {
                "event": "message_reaction",
                "thread_id": thread.id,
                "message_id": message.id,
                "reactions": build_reactions_for_user(message, user),
            }
            async_to_sync(channel_layer.group_send)(
                f"chat_user_{user.id}",
                {"type": "chat_message", "data": payload},
            )

        return Response(
            {
                "success": True,
                "reactions": build_reactions_for_user(message, request.user),
            },
            status=200,
        )


class ChatThreadMediaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, thread_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        messages = thread.messages.filter(
            message_type__in=["image", "video"]
        ).exclude(is_deleted=True)
        clear = ChatThreadClear.objects.filter(
            thread=thread, user=request.user
        ).first()
        if clear:
            messages = messages.filter(created_at__gt=clear.cleared_at)
        messages = messages.exclude(deletions__user=request.user).order_by(
            "-created_at"
        )
        serializer = ChatMessageSerializer(
            messages, many=True, context={"request": request}
        )
        return Response(serializer.data, status=200)


class ChatMessageDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id, message_id):
        thread = get_object_or_404(
            ChatThread, id=thread_id, participants=request.user
        )
        msg = get_object_or_404(ChatMessage, id=message_id, thread=thread)

        mode = request.data.get("mode", "for_me")
        if mode == "for_all":
            if msg.sender_id != request.user.id:
                return Response({"error": "Not allowed"}, status=403)
            msg.is_deleted = True
            msg.deleted_at = timezone.now()
            msg.deleted_by = request.user
            msg.body = "This message was deleted"
            msg.save()

            # Notify all participants
            payload = {
                "event": "message_deleted",
                "thread_id": thread.id,
                "message_id": msg.id,
            }
            channel_layer = get_channel_layer()
            for user in thread.participants.all():
                async_to_sync(channel_layer.group_send)(
                    f"chat_user_{user.id}",
                    {"type": "chat_message", "data": payload},
                )

            return Response({"success": True, "mode": "for_all"})

        # Default: delete for me only
        ChatMessageDeletion.objects.get_or_create(
            message=msg, user=request.user
        )
        return Response({"success": True, "mode": "for_me"})


from .models import PushToken

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    token = request.data.get("token")

    if not token:
        return Response({"error": "Missing token"}, status=400)

    # Keep only one active token per user (prevents duplicate pushes)
    PushToken.objects.filter(user=request.user).exclude(token=token).delete()

    # Ensure a token belongs to only one user to avoid self-push on shared devices
    PushToken.objects.filter(token=token).exclude(user=request.user).delete()

    PushToken.objects.get_or_create(user=request.user, token=token)

    return Response({"success": True})
