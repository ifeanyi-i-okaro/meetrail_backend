from rest_framework import serializers

from .models import (
    TrailEntry,
    TrailPoint,
    TrailMoment,
    TrailMomentComment,
    TrailMomentLike,
    TrailShare,
    TrailPlaybackShareRequest,
)


class TrailEntryStartSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=140, required=False, allow_blank=True)
    start_lat = serializers.FloatField(required=False)
    start_lng = serializers.FloatField(required=False)


class TrailEntryStopSerializer(serializers.Serializer):
    final_comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    visibility = serializers.ChoiceField(
        choices=[c[0] for c in TrailEntry.VISIBILITY_CHOICES],
        required=False,
    )
    share_scope = serializers.ChoiceField(
        choices=[c[0] for c in TrailEntry.SHARE_SCOPE_CHOICES],
        required=False,
    )
    title = serializers.CharField(max_length=140, required=False, allow_blank=True)
    end_lat = serializers.FloatField(required=False)
    end_lng = serializers.FloatField(required=False)


class TrailEntryUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=140, required=False, allow_blank=True)
    final_comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    visibility = serializers.ChoiceField(
        choices=[c[0] for c in TrailEntry.VISIBILITY_CHOICES],
        required=False,
    )
    share_scope = serializers.ChoiceField(
        choices=[c[0] for c in TrailEntry.SHARE_SCOPE_CHOICES],
        required=False,
    )


class TrailPointInputSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    recorded_at = serializers.DateTimeField(required=False)
    accuracy = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    mno = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    mcc_mnc = serializers.CharField(max_length=16, required=False, allow_blank=True, allow_null=True)
    network_type = serializers.CharField(max_length=32, required=False, allow_blank=True, allow_null=True)
    rsrp = serializers.IntegerField(required=False, allow_null=True)
    rsrq = serializers.FloatField(required=False, allow_null=True)
    sinr = serializers.FloatField(required=False, allow_null=True)
    rssi_dbm = serializers.IntegerField(required=False, allow_null=True)
    cell_id = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)
    tac = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)
    signal_sampled_at = serializers.DateTimeField(required=False, allow_null=True)


class TrailPointBulkSerializer(serializers.Serializer):
    points = TrailPointInputSerializer(many=True)

    def validate_points(self, points):
        if not points:
            raise serializers.ValidationError("At least one point is required.")
        if len(points) > 1000:
            raise serializers.ValidationError("Maximum 1000 points per request.")
        return points


class TrailMomentCreateSerializer(serializers.Serializer):
    moment_type = serializers.ChoiceField(choices=[c[0] for c in TrailMoment.TYPE_CHOICES])
    caption = serializers.CharField(max_length=240, required=False, allow_blank=True, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    media_file = serializers.FileField(required=False, allow_null=True)
    lat = serializers.FloatField(required=False)
    lng = serializers.FloatField(required=False)
    recorded_at = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        moment_type = attrs.get("moment_type")
        text = attrs.get("text")
        media_file = attrs.get("media_file")

        if moment_type in {TrailMoment.TYPE_PHOTO, TrailMoment.TYPE_VIDEO} and not media_file:
            raise serializers.ValidationError({"media_file": "Media file is required for photo/video moments."})
        if moment_type in {TrailMoment.TYPE_NOTE, TrailMoment.TYPE_COMMENT} and not (text or "").strip():
            raise serializers.ValidationError({"text": "Text is required for note/comment moments."})
        return attrs


class TrailMomentCommentCreateSerializer(serializers.Serializer):
    parent_id = serializers.IntegerField(
        required=False,
        min_value=1,
        allow_null=True,
    )
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    media_file = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("parent_id") is None:
            attrs.pop("parent_id", None)
        text = (attrs.get("text") or "").strip()
        media_file = attrs.get("media_file")
        if not text and not media_file:
            raise serializers.ValidationError(
                "Add text or attach a photo/video before posting.",
            )
        attrs["text"] = text
        return attrs


class TrailShareCreateSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    share_scope = serializers.ChoiceField(
        choices=[c[0] for c in TrailEntry.SHARE_SCOPE_CHOICES],
        required=False,
        default=TrailEntry.SHARE_SCOPE_FULL,
    )
    share_public = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        user_ids = attrs.get("user_ids", []) or []
        group_ids = attrs.get("group_ids", []) or []
        share_public = bool(attrs.get("share_public"))
        if not user_ids and not group_ids and not share_public:
            raise serializers.ValidationError(
                "Select at least one follower/group or enable public share.",
            )
        attrs["user_ids"] = list(dict.fromkeys(user_ids))
        attrs["group_ids"] = list(dict.fromkeys(group_ids))
        attrs["share_public"] = share_public
        return attrs


class TrailShareRevokeSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    revoke_public = serializers.BooleanField(required=False, default=False)
    revoke_all = serializers.BooleanField(required=False, default=False)
    set_private = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        user_ids = attrs.get("user_ids", []) or []
        group_ids = attrs.get("group_ids", []) or []
        revoke_public = bool(attrs.get("revoke_public"))
        revoke_all = bool(attrs.get("revoke_all"))
        if not user_ids and not group_ids and not revoke_public and not revoke_all:
            raise serializers.ValidationError(
                "Select users/groups to revoke, or enable revoke_public/revoke_all.",
            )
        attrs["user_ids"] = list(dict.fromkeys(user_ids))
        attrs["group_ids"] = list(dict.fromkeys(group_ids))
        attrs["revoke_public"] = revoke_public
        attrs["revoke_all"] = revoke_all
        attrs["set_private"] = bool(attrs.get("set_private", True))
        return attrs


class TrailPlaybackShareRequestSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs):
        user_ids = attrs.get("user_ids", []) or []
        group_ids = attrs.get("group_ids", []) or []
        attrs["user_ids"] = list(dict.fromkeys(user_ids))
        attrs["group_ids"] = list(dict.fromkeys(group_ids))
        return attrs


class TrailPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrailPoint
        fields = [
            "id",
            "lat",
            "lng",
            "recorded_at",
            "accuracy",
            "speed",
            "mno",
            "mcc_mnc",
            "network_type",
            "rsrp",
            "rsrq",
            "sinr",
            "rssi_dbm",
            "cell_id",
            "tac",
            "signal_sampled_at",
        ]


class TrailMomentSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    owner_profile_id = serializers.SerializerMethodField()
    owner_avatar = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = TrailMoment
        fields = [
            "id",
            "moment_type",
            "caption",
            "text",
            "media_url",
            "comments_count",
            "lat",
            "lng",
            "recorded_at",
            "created_at",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
            "likes_count",
            "is_liked",
        ]

    def get_media_url(self, obj):
        request = self.context.get("request")
        if obj.media_file and request:
            return request.build_absolute_uri(obj.media_file.url)
        return None

    def get_comments_count(self, obj):
        annotated = getattr(obj, "comments_count", None)
        if annotated is not None:
            return int(annotated)
        try:
            return int(obj.comments.count())
        except Exception:
            return 0

    def get_owner_profile_id(self, obj):
        profile = getattr(obj.trail.user, "profile", None)
        return profile.id if profile else None

    def get_owner_avatar(self, obj):
        request = self.context.get("request")
        profile = getattr(obj.trail.user, "profile", None)
        if request and profile and profile.profile_picture:
            return request.build_absolute_uri(profile.profile_picture.url)
        return None

    def get_owner_username(self, obj):
        return getattr(obj.trail.user, "username", "")

    def get_owner_name(self, obj):
        profile = getattr(obj.trail.user, "profile", None)
        if profile and profile.name:
            return profile.name
        return getattr(obj.trail.user, "username", "")

    def get_likes_count(self, obj):
        annotated = getattr(obj, "likes_count", None)
        if annotated is not None:
            return int(annotated)
        try:
            return int(obj.likes.count())
        except Exception:
            return 0

    def get_is_liked(self, obj):
        liked_ids = self.context.get("liked_moment_ids")
        if isinstance(liked_ids, (set, list, tuple)):
            return obj.id in liked_ids
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        return TrailMomentLike.objects.filter(moment_id=obj.id, user_id=user.id).exists()


class TrailMomentCommentSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()
    media_kind = serializers.SerializerMethodField()
    owner_profile_id = serializers.SerializerMethodField()
    owner_avatar = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = TrailMomentComment
        fields = [
            "id",
            "moment",
            "parent",
            "text",
            "media_url",
            "media_kind",
            "created_at",
            "updated_at",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
        ]

    def get_media_url(self, obj):
        request = self.context.get("request")
        if obj.media_file and request:
            return request.build_absolute_uri(obj.media_file.url)
        return None

    def get_media_kind(self, obj):
        media_name = str(getattr(obj.media_file, "name", "") or "").lower()
        if not media_name:
            return None
        video_exts = (".mp4", ".mov", ".m4v", ".webm", ".3gp", ".avi", ".mkv")
        if media_name.endswith(video_exts):
            return "video"
        return "photo"

    def get_owner_profile_id(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.id if profile else None

    def get_owner_avatar(self, obj):
        request = self.context.get("request")
        profile = getattr(obj.user, "profile", None)
        if request and profile and profile.profile_picture:
            return request.build_absolute_uri(profile.profile_picture.url)
        return None

    def get_owner_username(self, obj):
        return getattr(obj.user, "username", "")

    def get_owner_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        if profile and profile.name:
            return profile.name
        return getattr(obj.user, "username", "")


class TrailEntryOwnershipMixin(serializers.Serializer):
    owner_profile_id = serializers.SerializerMethodField()
    owner_avatar = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    can_view_full_trail = serializers.SerializerMethodField()

    def get_owner_profile_id(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.id if profile else None

    def get_owner_avatar(self, obj):
        request = self.context.get("request")
        profile = getattr(obj.user, "profile", None)
        if request and profile and profile.profile_picture:
            return request.build_absolute_uri(profile.profile_picture.url)
        return None

    def get_owner_username(self, obj):
        return getattr(obj.user, "username", "")

    def get_owner_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        if profile and profile.name:
            return profile.name
        return getattr(obj.user, "username", "")

    def get_can_view_full_trail(self, obj):
        explicit = getattr(obj, "_viewer_can_view_full", None)
        if explicit is not None:
            return bool(explicit)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.id == obj.user_id:
            return True
        return obj.share_scope == TrailEntry.SHARE_SCOPE_FULL


class TrailEntryListSerializer(TrailEntryOwnershipMixin, serializers.ModelSerializer):
    moments_count = serializers.IntegerField(read_only=True)
    points_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TrailEntry
        fields = [
            "id",
            "title",
            "status",
            "visibility",
            "share_scope",
            "can_view_full_trail",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
            "start_time",
            "end_time",
            "start_lat",
            "start_lng",
            "end_lat",
            "end_lng",
            "distance_m",
            "path_geometry",
            "final_comment",
            "moments_count",
            "points_count",
            "created_at",
            "updated_at",
        ]


class TrailEntryDetailSerializer(TrailEntryOwnershipMixin, serializers.ModelSerializer):
    points = TrailPointSerializer(many=True, read_only=True)
    moments = TrailMomentSerializer(many=True, read_only=True)

    class Meta:
        model = TrailEntry
        fields = [
            "id",
            "user",
            "title",
            "status",
            "visibility",
            "share_scope",
            "can_view_full_trail",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
            "start_time",
            "end_time",
            "start_lat",
            "start_lng",
            "end_lat",
            "end_lng",
            "distance_m",
            "path_geometry",
            "final_comment",
            "points",
            "moments",
            "created_at",
            "updated_at",
        ]


class TrailEntryMomentsOnlyDetailSerializer(TrailEntryOwnershipMixin, serializers.ModelSerializer):
    moments = TrailMomentSerializer(many=True, read_only=True)

    class Meta:
        model = TrailEntry
        fields = [
            "id",
            "user",
            "title",
            "status",
            "visibility",
            "share_scope",
            "can_view_full_trail",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
            "start_time",
            "end_time",
            "final_comment",
            "moments",
            "created_at",
            "updated_at",
        ]


class TrailEntryMomentsMapSerializer(TrailEntryOwnershipMixin, serializers.ModelSerializer):
    moments = TrailMomentSerializer(many=True, read_only=True)

    class Meta:
        model = TrailEntry
        fields = [
            "id",
            "title",
            "status",
            "visibility",
            "share_scope",
            "can_view_full_trail",
            "owner_profile_id",
            "owner_avatar",
            "owner_username",
            "owner_name",
            "moments",
            "updated_at",
        ]


class TrailReplaySerializer(TrailEntryOwnershipMixin, serializers.ModelSerializer):
    points = TrailPointSerializer(many=True, read_only=True)
    moments = TrailMomentSerializer(many=True, read_only=True)

    class Meta:
        model = TrailEntry
        fields = [
            "id",
            "title",
            "share_scope",
            "can_view_full_trail",
            "start_time",
            "end_time",
            "distance_m",
            "path_geometry",
            "points",
            "moments",
        ]


class TrailPlaybackShareRequestStatusSerializer(serializers.ModelSerializer):
    output_video_url = serializers.SerializerMethodField()

    class Meta:
        model = TrailPlaybackShareRequest
        fields = [
            "id",
            "trail",
            "requested_by",
            "user_ids",
            "group_ids",
            "status",
            "status_note",
            "progress_percent",
            "output_video_url",
            "started_at",
            "finished_at",
            "error_message",
            "created_at",
            "updated_at",
        ]

    def get_output_video_url(self, obj):
        request = self.context.get("request")
        if obj.output_video and request:
            return request.build_absolute_uri(obj.output_video.url)
        return None
