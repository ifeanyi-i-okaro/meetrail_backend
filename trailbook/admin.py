from django.contrib import admin

from .models import (
    TrailEntry,
    TrailPoint,
    TrailMoment,
    TrailMomentComment,
    TrailMomentLike,
    TrailShare,
    TrailPlaybackShareRequest,
)


@admin.register(TrailEntry)
class TrailEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "visibility",
        "share_scope",
        "start_time",
        "end_time",
    )
    list_filter = ("status", "visibility", "share_scope")
    search_fields = ("user__email", "user__username", "title")


@admin.register(TrailPoint)
class TrailPointAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "trail",
        "lat",
        "lng",
        "mno",
        "network_type",
        "rsrp",
        "rssi_dbm",
        "recorded_at",
    )
    list_filter = ("network_type", "mno")
    search_fields = ("trail__id", "trail__user__email", "trail__user__username")
    ordering = ("-recorded_at", "-id")


@admin.register(TrailMoment)
class TrailMomentAdmin(admin.ModelAdmin):
    list_display = ("id", "trail", "moment_type", "caption", "recorded_at")
    list_filter = ("moment_type",)
    search_fields = ("trail__id", "trail__user__email", "trail__user__username")


@admin.register(TrailMomentComment)
class TrailMomentCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "moment", "user", "parent", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "moment__id",
        "moment__trail__id",
        "user__email",
        "user__username",
        "text",
    )
    ordering = ("-created_at", "-id")


@admin.register(TrailMomentLike)
class TrailMomentLikeAdmin(admin.ModelAdmin):
    list_display = ("id", "moment", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "moment__id",
        "moment__trail__id",
        "user__email",
        "user__username",
    )
    ordering = ("-created_at", "-id")


@admin.register(TrailShare)
class TrailShareAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "trail",
        "shared_by",
        "target_user",
        "target_group",
        "share_scope",
        "created_at",
    )
    list_filter = ("share_scope",)
    search_fields = (
        "trail__id",
        "trail__user__email",
        "shared_by__email",
        "target_user__email",
        "target_group__name",
    )


@admin.register(TrailPlaybackShareRequest)
class TrailPlaybackShareRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "trail",
        "requested_by",
        "status",
        "progress_percent",
        "started_at",
        "finished_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("trail__id", "trail__user__email", "requested_by__email")
    readonly_fields = (
        "output_video",
        "progress_percent",
        "started_at",
        "finished_at",
        "error_message",
    )
