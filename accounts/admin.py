from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import (
    User,
    Profile,
    OTP,
    PushToken,
    ChatThread,
    ChatMessage,
    ChatMessageDeletion,
    ChatMessageRead,
    ChatMessageReaction,
    ChatThreadClear,
    ChatThreadUserSetting,
    Notification,
)


# ==========================
# 🧩 Custom User Admin
# ==========================
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom admin configuration for User model with email as login field"""
    model = User
    ordering = ("email",)
    search_fields = ("email", "username")
    list_display = ("email", "username", "dob", "is_active", "is_staff", "is_superuser")
    list_filter = ("is_active", "is_staff", "is_superuser")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal Info"), {"fields": ("username", "dob")}),
        (_("Permissions"), {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        }),

    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "dob", "password1", "password2", "is_staff", "is_active"),
        }),
    )


# ==========================
# 👤 Profile Admin
# ==========================
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Admin for user profiles"""
    list_display = (
        "user",
        "name",
        "gender",
        "followers_count",
        "following_count",
        "created_at",
    )
    search_fields = ("user__email", "user__username", "name")
    list_filter = ("gender", "created_at")
    readonly_fields = ("created_at",)
    filter_horizontal = ("followers",)

    fieldsets = (
        (None, {
            "fields": ("user", "name", "gender", "bio", "profile_picture")
        }),
        ("Social", {
            "fields": ("followers",)
        }),
        ("Metadata", {
            "fields": ("created_at",)
        }),
    )

    def followers_count(self, obj):
        return obj.followers.count()
    followers_count.short_description = "Followers"

    def following_count(self, obj):
        return obj.following.count()
    following_count.short_description = "Following"


# ==========================
# 🔢 OTP Admin
# ==========================
@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    """Admin for OTP management"""
    list_display = ("user", "code", "is_used", "created_at")
    list_filter = ("is_used", "created_at")
    search_fields = ("user__email", "code")
    readonly_fields = ("created_at",)
@admin.register(PushToken)
class PushTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "short_token",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__username", "token")
    ordering = ("-created_at",)

    def short_token(self, obj):
        return obj.token[:30] + "..."
    short_token.short_description = "Token"


@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "is_group",
        "is_private",
        "name",
        "created_by",
        "updated_at",
    )
    list_filter = ("is_group", "is_private", "updated_at")
    search_fields = ("name", "created_by__email", "created_by__username")
    filter_horizontal = ("participants",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "thread",
        "sender",
        "message_type",
        "short_body",
        "is_deleted",
        "is_forwarded",
        "created_at",
    )
    list_filter = ("message_type", "is_deleted", "is_forwarded", "created_at")
    search_fields = ("body", "sender__email", "sender__username")
    readonly_fields = ("created_at",)

    def short_body(self, obj):
        return (obj.body or "")[:50]

    short_body.short_description = "Body"


@admin.register(ChatMessageDeletion)
class ChatMessageDeletionAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__username")


@admin.register(ChatMessageRead)
class ChatMessageReadAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "user")
    search_fields = ("user__email", "user__username")


@admin.register(ChatMessageReaction)
class ChatMessageReactionAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "user", "emoji", "created_at")
    list_filter = ("emoji", "created_at")
    search_fields = ("user__email", "user__username", "emoji")


@admin.register(ChatThreadClear)
class ChatThreadClearAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "user", "cleared_at")
    list_filter = ("cleared_at",)
    search_fields = ("user__email", "user__username")


@admin.register(ChatThreadUserSetting)
class ChatThreadUserSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "thread",
        "user",
        "is_hidden",
        "is_paused",
        "hidden_at",
        "paused_at",
    )
    list_filter = ("is_hidden", "is_paused", "hidden_at", "paused_at")
    search_fields = ("user__email", "user__username")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient",
        "type",
        "thread",
        "is_read",
        "created_at",
    )
    list_filter = ("type", "is_read", "created_at")
    search_fields = ("recipient__email", "recipient__username", "message")
