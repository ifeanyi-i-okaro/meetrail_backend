from rest_framework import serializers
from .models import User, Profile, OTP
from django.core.mail import send_mail
from django.conf import settings


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "username", "password", "dob"]
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        otp_code = OTP.generate_otp()
        OTP.objects.create(user=user, code=otp_code)

        send_mail(
            subject="Your MeeTrail Verification Code",
            message=f"Your OTP code is {otp_code}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )

        return user


from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate(self, data):
        email = data.get("email")
        code = data.get("code")

        try:
            user = User.objects.get(email=email)
            otp = OTP.objects.filter(
                user=user,
                code=code,
                is_used=False
            ).last()

            if not otp or not otp.is_valid():
                raise serializers.ValidationError(
                    {"code": "Invalid or expired OTP"}
                )

        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User not found"}
            )

        # ✅ Mark OTP as used and activate user
        otp.is_used = True
        otp.save()

        user.is_active = True
        user.save()

  
        return data



from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Profile
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Profile

User = get_user_model()

# ✅ Nested lightweight User serializer
class UserPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class ProfileSerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)
    profile_picture = serializers.SerializerMethodField()
    cover_photo = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()

    # 🆕 extra fields for frontend logic
    is_me = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "id",
            "user",
            "name",
            "gender",
            "bio",
            "profile_picture",
            "cover_photo",
            "followers_count",
            "following_count",
            "is_me",        # 🆕
            "is_following", # 🆕
        ]

    # ---------- read-only URL helpers ----------
    def get_profile_picture(self, obj):
        request = self.context.get("request")
        if obj.profile_picture and request is not None:
            return request.build_absolute_uri(obj.profile_picture.url)
        return None

    def get_cover_photo(self, obj):
        request = self.context.get("request")
        if obj.cover_photo and request is not None:
            return request.build_absolute_uri(obj.cover_photo.url)
        return None

    def get_followers_count(self, obj):
        return obj.followers.count()

    def get_following_count(self, obj):
        return obj.following.count()

    # ---------- NEW helper flags ----------
    def get_is_me(self, obj):
        """
        True if the serialized profile belongs to the requesting user.
        """
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.user_id == request.user.id

    def get_is_following(self, obj):
        """
        True if the requesting user's profile is following this profile.
        """
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        try:
            my_profile = request.user.profile
        except Profile.DoesNotExist:
            return False

        return my_profile.is_following(obj)

    # ---------- write logic for updates (UNCHANGED) ----------
    def update(self, instance, validated_data):
        # normal text fields
        instance.name = validated_data.get("name", instance.name)
        gender = validated_data.get("gender", instance.gender)
        if gender:
            instance.gender = gender
        instance.bio = validated_data.get("bio", instance.bio)

        # files come from request.FILES, not validated_data,
        # because profile_picture/cover_photo are SerializerMethodField
        request = self.context.get("request")
        if request is not None:
            profile_file = request.FILES.get("profile_picture")
            cover_file = request.FILES.get("cover_photo")

            if profile_file:
                instance.profile_picture = profile_file
            if cover_file:
                instance.cover_photo = cover_file

        instance.save()
        return instance



class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, data):
        email = data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User not found"}
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


        return data


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    password = serializers.CharField(min_length=8)

    def validate(self, data):
        email = data["email"]
        code = data["code"]
        password = data["password"]

        try:
            user = User.objects.get(email=email)
            otp = OTP.objects.filter(
                user=user, code=code, is_used=False
            ).last()

            if not otp or not otp.is_valid():
                raise serializers.ValidationError(
                    {"code": "Invalid or expired code"}
                )

        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User not found"}
            )

        user.set_password(password)
        user.save()

        otp.is_used = True
        otp.save()

        return data

# notifications/serializers.py
from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username")
    actor_profile_id = serializers.IntegerField(
        source="actor.profile.id",
        read_only=True,
    )
    actor_avatar = serializers.SerializerMethodField()
    message = serializers.CharField()
    thread_id = serializers.IntegerField(source="thread.id", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "message",
            "actor_name",
            "actor_profile_id",  # ✅ ADD THIS
            "actor_avatar",
            "thread_id",
            "is_read",
            "created_at",
        ]

    def get_actor_avatar(self, obj):
        request = self.context.get("request")

        if (
            request
            and hasattr(obj.actor, "profile")
            and obj.actor.profile.profile_picture
        ):
            return request.build_absolute_uri(
                obj.actor.profile.profile_picture.url
            )

        return None


# ─────────────────────────────────────────────
# Chat serializers
# ─────────────────────────────────────────────
import re
from django.db.models import Count
from .models import (
    ChatThread,
    ChatMessage,
    ChatMessageDeletion,
    ChatMessageRead,
    ChatMessageReaction,
    ChatThreadClear,
)


class ChatUserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    profile_id = serializers.IntegerField(source="profile.id", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "profile_id", "name", "avatar"]

    def get_name(self, obj):
        if hasattr(obj, "profile") and obj.profile.name:
            return obj.profile.name
        return obj.username

    def get_avatar(self, obj):
        request = self.context.get("request")
        if request and hasattr(obj, "profile") and obj.profile.profile_picture:
            return request.build_absolute_uri(obj.profile.profile_picture.url)
        return None


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(source="sender.id", read_only=True)
    sender_profile_id = serializers.IntegerField(
        source="sender.profile.id", read_only=True
    )
    sender_name = serializers.SerializerMethodField()
    sender_avatar = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    deleted_for_me = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    reply_to = serializers.SerializerMethodField()
    read_by_count = serializers.SerializerMethodField()
    is_read_by_me = serializers.SerializerMethodField()
    read_by_all = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    mentions = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "thread",
            "sender_id",
            "sender_profile_id",
            "sender_name",
            "sender_avatar",
            "body",
            "message_type",
            "file_url",
            "file_name",
            "file_size",
            "reply_to",
            "is_forwarded",
            "is_deleted",
            "created_at",
            "is_mine",
            "deleted_for_me",
            "read_by_count",
            "is_read_by_me",
            "read_by_all",
            "reactions",
            "mentions",
        ]

    def get_sender_name(self, obj):
        if hasattr(obj.sender, "profile") and obj.sender.profile.name:
            return obj.sender.profile.name
        return obj.sender.username

    def get_sender_avatar(self, obj):
        request = self.context.get("request")
        if request and hasattr(obj.sender, "profile") and obj.sender.profile.profile_picture:
            return request.build_absolute_uri(obj.sender.profile.profile_picture.url)
        return None

    def get_is_mine(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.sender_id == request.user.id

    def get_deleted_for_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return ChatMessageDeletion.objects.filter(
            message=obj, user=request.user
        ).exists()

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None

    def get_reply_to(self, obj):
        if not obj.reply_to_id:
            return None
        reply = obj.reply_to
        return {
            "id": reply.id,
            "sender_id": reply.sender_id,
            "sender_name": self.get_sender_name(reply),
            "body": reply.body,
            "message_type": reply.message_type,
            "is_deleted": reply.is_deleted,
        }

    def get_read_by_count(self, obj):
        return obj.reads.count()

    def get_is_read_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return ChatMessageRead.objects.filter(
            message=obj, user=request.user
        ).exists()

    def get_read_by_all(self, obj):
        try:
            total = obj.thread.participants.count() - 1
        except Exception:
            total = 0
        if total <= 0:
            return False
        return obj.reads.count() >= total

    def get_reactions(self, obj):
        request = self.context.get("request")
        reacted = set()
        if request and request.user.is_authenticated:
            reacted = set(
                ChatMessageReaction.objects.filter(
                    message=obj, user=request.user
                ).values_list("emoji", flat=True)
            )
        qs = (
            ChatMessageReaction.objects.filter(message=obj)
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

    def get_mentions(self, obj):
        if not obj.body:
            return []
        mentions = re.findall(
            r"@([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?)",
            obj.body,
        )
        # Preserve order but remove duplicates
        seen = set()
        unique = []
        for m in mentions:
            if m in seen:
                continue
            seen.add(m)
            unique.append(m)
        return unique


class ChatThreadSerializer(serializers.ModelSerializer):
    participants = ChatUserSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    display_avatar = serializers.SerializerMethodField()
    group_image = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    owner_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = ChatThread
        fields = [
            "id",
            "is_group",
            "is_private",
            "name",
            "display_name",
            "display_avatar",
            "group_image",
            "owner_id",
            "is_owner",
            "participants",
            "last_message",
            "updated_at",
        ]

    def get_last_message(self, obj):
        request = self.context.get("request")
        qs = obj.messages.order_by("-created_at")
        if request and request.user.is_authenticated:
            clear = ChatThreadClear.objects.filter(
                thread=obj, user=request.user
            ).first()
            if clear:
                qs = qs.filter(created_at__gt=clear.cleared_at)
            qs = qs.exclude(deletions__user=request.user)
        last = qs.first()
        if not last:
            return None
        return ChatMessageSerializer(last, context=self.context).data

    def get_display_name(self, obj):
        request = self.context.get("request")
        if obj.is_group:
            return obj.name or "Group Chat"
        if not request or not request.user.is_authenticated:
            return obj.name or "Chat"
        other = obj.participants.exclude(id=request.user.id).first()
        if not other:
            return obj.name or "Chat"
        if hasattr(other, "profile") and other.profile.name:
            return other.profile.name
        return other.username

    def get_display_avatar(self, obj):
        request = self.context.get("request")
        if obj.is_group:
            if obj.group_image and request:
                return request.build_absolute_uri(obj.group_image.url)
            return None
        if not request or not request.user.is_authenticated:
            return None
        other = obj.participants.exclude(id=request.user.id).first()
        if not other:
            return None
        if (
            request
            and hasattr(other, "profile")
            and other.profile.profile_picture
        ):
            return request.build_absolute_uri(other.profile.profile_picture.url)
        return None

    def get_group_image(self, obj):
        request = self.context.get("request")
        if obj.group_image and request:
            return request.build_absolute_uri(obj.group_image.url)
        return None

    def get_is_owner(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.created_by_id == request.user.id

