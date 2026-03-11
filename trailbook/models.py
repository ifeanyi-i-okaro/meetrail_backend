from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TrailEntry(models.Model):
    STATUS_RECORDING = "recording"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_RECORDING, "Recording"),
        (STATUS_COMPLETED, "Completed"),
    )

    VISIBILITY_PUBLIC = "public"
    VISIBILITY_FOLLOWERS = "followers"
    VISIBILITY_PRIVATE = "private"
    VISIBILITY_CHOICES = (
        (VISIBILITY_PUBLIC, "Public"),
        (VISIBILITY_FOLLOWERS, "Followers-only"),
        (VISIBILITY_PRIVATE, "Private"),
    )
    SHARE_SCOPE_FULL = "full"
    SHARE_SCOPE_MOMENTS = "moments"
    SHARE_SCOPE_CHOICES = (
        (SHARE_SCOPE_FULL, "Entire trail"),
        (SHARE_SCOPE_MOMENTS, "Moments only"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_entries",
    )
    title = models.CharField(max_length=140, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECORDING,
    )
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_PRIVATE,
    )
    share_scope = models.CharField(
        max_length=20,
        choices=SHARE_SCOPE_CHOICES,
        default=SHARE_SCOPE_FULL,
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    start_lat = models.FloatField(null=True, blank=True)
    start_lng = models.FloatField(null=True, blank=True)
    end_lat = models.FloatField(null=True, blank=True)
    end_lng = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(default=0)
    path_geometry = models.JSONField(null=True, blank=True)
    final_comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time", "-id"]
        indexes = [
            models.Index(
                fields=["user", "status", "-start_time"],
                name="trailbook_t_user_st_ebec07_idx",
            ),
            models.Index(
                fields=["status", "visibility", "-start_time"],
                name="trailbook_t_status_6be5a3_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} Trail {self.id} ({self.status})"


class TrailPoint(models.Model):
    trail = models.ForeignKey(
        TrailEntry,
        on_delete=models.CASCADE,
        related_name="points",
    )
    lat = models.FloatField()
    lng = models.FloatField()
    recorded_at = models.DateTimeField(default=timezone.now)
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    mno = models.CharField(max_length=120, null=True, blank=True)
    mcc_mnc = models.CharField(max_length=16, null=True, blank=True)
    network_type = models.CharField(max_length=32, null=True, blank=True)
    rsrp = models.IntegerField(null=True, blank=True)
    rsrq = models.FloatField(null=True, blank=True)
    sinr = models.FloatField(null=True, blank=True)
    rssi_dbm = models.IntegerField(null=True, blank=True)
    cell_id = models.CharField(max_length=64, null=True, blank=True)
    tac = models.CharField(max_length=64, null=True, blank=True)
    signal_sampled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [
            models.Index(
                fields=["trail", "recorded_at"],
                name="trailbook_t_trail_i_295e4f_idx",
            ),
        ]

    def __str__(self):
        return f"Trail {self.trail_id} Point {self.id}"


class TrailMoment(models.Model):
    TYPE_PHOTO = "photo"
    TYPE_VIDEO = "video"
    TYPE_NOTE = "note"
    TYPE_COMMENT = "comment"
    TYPE_CHOICES = (
        (TYPE_PHOTO, "Photo"),
        (TYPE_VIDEO, "Video"),
        (TYPE_NOTE, "Note"),
        (TYPE_COMMENT, "Comment"),
    )

    trail = models.ForeignKey(
        TrailEntry,
        on_delete=models.CASCADE,
        related_name="moments",
    )
    moment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    caption = models.CharField(max_length=240, blank=True, null=True)
    text = models.TextField(blank=True, null=True)
    media_file = models.FileField(upload_to="trailbook/", blank=True, null=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [
            models.Index(
                fields=["trail", "recorded_at"],
                name="trailbook_t_trail_i_9385a4_idx",
            ),
            models.Index(
                fields=["moment_type"],
                name="trailbook_t_moment__5f5115_idx",
            ),
        ]

    def __str__(self):
        return f"Trail {self.trail_id} Moment {self.id} ({self.moment_type})"


class TrailMomentComment(models.Model):
    moment = models.ForeignKey(
        TrailMoment,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_moment_comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    text = models.TextField(blank=True, null=True)
    media_file = models.FileField(
        upload_to="trailbook/comment_media/",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["moment", "created_at"],
                name="trailbook_c_moment_9e0c61_idx",
            ),
            models.Index(
                fields=["parent", "created_at"],
                name="trailbook_c_parent_5de1f4_idx",
            ),
        ]

    def __str__(self):
        return f"Moment {self.moment_id} Comment {self.id}"


class TrailMomentLike(models.Model):
    moment = models.ForeignKey(
        TrailMoment,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_moment_likes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["moment", "created_at"],
                name="trailbook_l_moment_59b2b4_idx",
            ),
            models.Index(
                fields=["user", "created_at"],
                name="trailbook_l_user_9e2f13_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["moment", "user"],
                name="trailbook_like_moment_user_uniq",
            ),
        ]

    def __str__(self):
        return f"Moment {self.moment_id} liked by {self.user_id}"


class TrailShare(models.Model):
    trail = models.ForeignKey(
        TrailEntry,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_shares_sent",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_shares_received",
        null=True,
        blank=True,
    )
    target_group = models.ForeignKey(
        "accounts.ChatThread",
        on_delete=models.CASCADE,
        related_name="trail_shares",
        null=True,
        blank=True,
    )
    share_scope = models.CharField(
        max_length=20,
        choices=TrailEntry.SHARE_SCOPE_CHOICES,
        default=TrailEntry.SHARE_SCOPE_FULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["trail", "target_user"],
                name="trailbook_s_trail_u_8aa3f1_idx",
            ),
            models.Index(
                fields=["trail", "target_group"],
                name="trailbook_s_trail_g_3a11c2_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    (Q(target_user__isnull=False) & Q(target_group__isnull=True))
                    | (Q(target_user__isnull=True) & Q(target_group__isnull=False))
                ),
                name="trailbook_share_single_target_ck",
            ),
            models.UniqueConstraint(
                fields=["trail", "target_user"],
                condition=Q(target_user__isnull=False),
                name="trailbook_share_trail_user_uniq",
            ),
            models.UniqueConstraint(
                fields=["trail", "target_group"],
                condition=Q(target_group__isnull=False),
                name="trailbook_share_trail_group_uniq",
            ),
        ]

    def __str__(self):
        if self.target_user_id:
            return f"Trail {self.trail_id} -> user {self.target_user_id}"
        return f"Trail {self.trail_id} -> group {self.target_group_id}"


class TrailPlaybackShareRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    )

    trail = models.ForeignKey(
        TrailEntry,
        on_delete=models.CASCADE,
        related_name="playback_share_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trail_playback_share_requests",
    )
    user_ids = models.JSONField(default=list, blank=True)
    group_ids = models.JSONField(default=list, blank=True)
    output_video = models.FileField(
        upload_to="trailbook/playback_exports/",
        null=True,
        blank=True,
    )
    progress_percent = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    status_note = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["trail", "status", "-created_at"],
                name="trailbook_p_trail_s_b0d4a8_idx",
            ),
        ]

    def __str__(self):
        return f"Playback share request {self.id} for trail {self.trail_id}"
