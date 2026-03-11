from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import ChatThread, Notification, User

from .models import (
    TrailEntry,
    TrailMoment,
    TrailMomentComment,
    TrailPlaybackShareRequest,
    TrailShare,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    TRAILBOOK_PLAYBACK_AUTORUN=False,
)
class TrailBookApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@trailbook.test",
            username="owner",
            password="StrongPass123!",
            dob=date(1994, 1, 1),
        )
        self.owner.is_active = True
        self.owner.save(update_fields=["is_active"])

        self.follower = User.objects.create_user(
            email="follower@trailbook.test",
            username="follower",
            password="StrongPass123!",
            dob=date(1995, 1, 1),
        )
        self.follower.is_active = True
        self.follower.save(update_fields=["is_active"])

        self.stranger = User.objects.create_user(
            email="stranger@trailbook.test",
            username="stranger",
            password="StrongPass123!",
            dob=date(1996, 1, 1),
        )
        self.stranger.is_active = True
        self.stranger.save(update_fields=["is_active"])

        # follower follows owner -> can view followers-only content
        self.follower.profile.follow(self.owner.profile)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def test_start_points_moment_stop_flow(self):
        self._auth(self.owner)

        start_res = self.client.post(
            "/api/trailbook/start/",
            {
                "title": "Evening Walk",
                "start_lat": 52.52,
                "start_lng": 13.405,
            },
            format="json",
        )
        self.assertEqual(start_res.status_code, status.HTTP_201_CREATED)
        trail_id = start_res.data["id"]
        self.assertEqual(start_res.data["status"], TrailEntry.STATUS_RECORDING)

        points_res = self.client.post(
            f"/api/trailbook/{trail_id}/points/bulk/",
            {
                "points": [
                    {
                        "lat": 52.52,
                        "lng": 13.405,
                        "accuracy": 4.2,
                        "mno": "Vodafone",
                        "mcc_mnc": "26202",
                        "network_type": "lte",
                        "rsrp": -98,
                        "rsrq": -12.5,
                        "sinr": 7.1,
                        "rssi_dbm": -82,
                        "cell_id": "262-02-1234567",
                        "tac": "14567",
                    },
                    {
                        "lat": 52.5205,
                        "lng": 13.4062,
                        "accuracy": 5.1,
                        "mno": "Vodafone",
                        "network_type": "lte",
                        "rssi_dbm": -84,
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(points_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(points_res.data["created"], 2)

        note_res = self.client.post(
            f"/api/trailbook/{trail_id}/moments/",
            {"moment_type": "note", "text": "Found a great viewpoint"},
            format="json",
        )
        self.assertEqual(note_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(note_res.data["moment_type"], "note")

        photo_file = SimpleUploadedFile(
            "photo.jpg",
            b"fake-image-bytes",
            content_type="image/jpeg",
        )
        photo_res = self.client.post(
            f"/api/trailbook/{trail_id}/moments/",
            {
                "moment_type": "photo",
                "caption": "Nice light",
                "media_file": photo_file,
            },
            format="multipart",
        )
        self.assertEqual(photo_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(photo_res.data["moment_type"], "photo")
        self.assertEqual(photo_res.data["caption"], "Nice light")

        stop_res = self.client.post(
            f"/api/trailbook/{trail_id}/stop/",
            {
                "final_comment": "Solid session.",
                "visibility": "followers",
                "share_scope": "moments",
            },
            format="json",
        )
        self.assertEqual(stop_res.status_code, status.HTTP_200_OK)
        self.assertEqual(stop_res.data["status"], TrailEntry.STATUS_COMPLETED)
        self.assertEqual(stop_res.data["visibility"], TrailEntry.VISIBILITY_FOLLOWERS)
        self.assertEqual(stop_res.data["share_scope"], TrailEntry.SHARE_SCOPE_MOMENTS)
        self.assertGreaterEqual(stop_res.data["distance_m"], 0)
        self.assertEqual(len(stop_res.data["points"]), 2)
        self.assertEqual(len(stop_res.data["moments"]), 2)
        first_point = stop_res.data["points"][0]
        self.assertEqual(first_point["mno"], "Vodafone")
        self.assertEqual(first_point["network_type"], "lte")
        self.assertEqual(first_point["rsrp"], -98)
        self.assertEqual(first_point["cell_id"], "262-02-1234567")
        geometry = stop_res.data.get("path_geometry") or {}
        self.assertEqual(geometry.get("type"), "LineString")
        self.assertEqual(len(geometry.get("coordinates") or []), 2)

    def test_visibility_permissions_for_detail(self):
        followers_trail = TrailEntry.objects.create(
            user=self.owner,
            title="Followers Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_FOLLOWERS,
        )
        moments_only_trail = TrailEntry.objects.create(
            user=self.owner,
            title="Followers Moments-only Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_FOLLOWERS,
            share_scope=TrailEntry.SHARE_SCOPE_MOMENTS,
            path_geometry={"type": "LineString", "coordinates": [[13.4, 52.5], [13.5, 52.6]]},
        )
        TrailMoment.objects.create(
            trail=moments_only_trail,
            moment_type=TrailMoment.TYPE_NOTE,
            text="Shared note",
            lat=52.5,
            lng=13.4,
        )
        private_trail = TrailEntry.objects.create(
            user=self.owner,
            title="Private Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
        )
        public_trail = TrailEntry.objects.create(
            user=self.owner,
            title="Public Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PUBLIC,
        )

        self._auth(self.follower)
        follower_ok = self.client.get(f"/api/trailbook/{followers_trail.id}/")
        self.assertEqual(follower_ok.status_code, status.HTTP_200_OK)
        follower_moments_only = self.client.get(f"/api/trailbook/{moments_only_trail.id}/")
        self.assertEqual(follower_moments_only.status_code, status.HTTP_200_OK)
        self.assertEqual(follower_moments_only.data["share_scope"], TrailEntry.SHARE_SCOPE_MOMENTS)
        self.assertFalse(follower_moments_only.data["can_view_full_trail"])
        self.assertNotIn("points", follower_moments_only.data)
        self.assertNotIn("path_geometry", follower_moments_only.data)
        self.assertEqual(len(follower_moments_only.data.get("moments", [])), 1)
        follower_private = self.client.get(f"/api/trailbook/{private_trail.id}/")
        self.assertEqual(follower_private.status_code, status.HTTP_403_FORBIDDEN)
        follower_replay_denied = self.client.get(
            f"/api/trailbook/{moments_only_trail.id}/replay/",
        )
        self.assertEqual(follower_replay_denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Playback is unavailable", follower_replay_denied.data["error"])

        self._auth(self.stranger)
        stranger_followers = self.client.get(f"/api/trailbook/{followers_trail.id}/")
        self.assertEqual(stranger_followers.status_code, status.HTTP_403_FORBIDDEN)
        stranger_public = self.client.get(f"/api/trailbook/{public_trail.id}/")
        self.assertEqual(stranger_public.status_code, status.HTTP_200_OK)

    def test_followers_scope_lists_only_followed_users_shared_trails(self):
        followed_public = TrailEntry.objects.create(
            user=self.owner,
            title="Followed Public",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PUBLIC,
        )
        followed_followers = TrailEntry.objects.create(
            user=self.owner,
            title="Followed Followers",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_FOLLOWERS,
        )
        stranger_public = TrailEntry.objects.create(
            user=self.stranger,
            title="Stranger Public",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PUBLIC,
        )

        self._auth(self.follower)
        res = self.client.get("/api/trailbook/?scope=followers")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in res.data["results"]]
        self.assertIn(followed_public.id, ids)
        self.assertIn(followed_followers.id, ids)
        self.assertNotIn(stranger_public.id, ids)

    def test_list_filters_by_moment_type(self):
        trail_photo = TrailEntry.objects.create(
            user=self.owner,
            title="Photo Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PUBLIC,
        )
        trail_note = TrailEntry.objects.create(
            user=self.owner,
            title="Note Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PUBLIC,
        )
        TrailMoment.objects.create(
            trail=trail_photo,
            moment_type=TrailMoment.TYPE_PHOTO,
        )
        TrailMoment.objects.create(
            trail=trail_note,
            moment_type=TrailMoment.TYPE_NOTE,
            text="Text-only moment",
        )

        self._auth(self.stranger)
        list_res = self.client.get("/api/trailbook/?type=photo")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in list_res.data["results"]]
        self.assertIn(trail_photo.id, ids)
        self.assertNotIn(trail_note.id, ids)

    def test_share_options_share_to_group_and_shared_scope(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Direct Share Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
            share_scope=TrailEntry.SHARE_SCOPE_FULL,
            path_geometry={"type": "LineString", "coordinates": [[13.4, 52.5], [13.5, 52.6]]},
        )
        TrailMoment.objects.create(
            trail=trail,
            moment_type=TrailMoment.TYPE_NOTE,
            text="Shared note",
            lat=52.5,
            lng=13.4,
        )
        group = ChatThread.objects.create(
            is_group=True,
            name="Trail Share Group",
            created_by=self.owner,
        )
        group.participants.set([self.owner, self.follower, self.stranger])

        self._auth(self.owner)
        options_res = self.client.get("/api/trailbook/share/options/")
        self.assertEqual(options_res.status_code, status.HTTP_200_OK)
        follower_ids = [item["id"] for item in options_res.data["followers"]]
        self.assertIn(self.follower.id, follower_ids)
        group_ids = [item["id"] for item in options_res.data["groups"]]
        self.assertIn(group.id, group_ids)

        share_res = self.client.post(
            f"/api/trailbook/{trail.id}/share/",
            {
                "user_ids": [self.follower.id],
                "group_ids": [group.id],
                "share_scope": "moments",
            },
            format="json",
        )
        self.assertEqual(share_res.status_code, status.HTTP_200_OK)
        self.assertEqual(share_res.data["share_scope"], TrailEntry.SHARE_SCOPE_MOMENTS)
        self.assertEqual(TrailShare.objects.filter(trail=trail).count(), 2)

        self._auth(self.stranger)
        shared_list_res = self.client.get("/api/trailbook/?scope=shared")
        self.assertEqual(shared_list_res.status_code, status.HTTP_200_OK)
        shared_ids = [item["id"] for item in shared_list_res.data["results"]]
        self.assertIn(trail.id, shared_ids)
        shared_entry = [item for item in shared_list_res.data["results"] if item["id"] == trail.id][0]
        self.assertFalse(shared_entry["can_view_full_trail"])

        shared_detail_res = self.client.get(f"/api/trailbook/{trail.id}/")
        self.assertEqual(shared_detail_res.status_code, status.HTTP_200_OK)
        self.assertNotIn("points", shared_detail_res.data)
        self.assertIn("moments", shared_detail_res.data)
        replay_res = self.client.get(f"/api/trailbook/{trail.id}/replay/")
        self.assertEqual(replay_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_share_playback_request_endpoint(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Playback Share Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
        )
        group = ChatThread.objects.create(
            is_group=True,
            name="Playback Group",
            created_by=self.owner,
        )
        group.participants.set([self.owner, self.follower])

        self._auth(self.owner)
        response = self.client.post(
            f"/api/trailbook/{trail.id}/share-playback/",
            {
                "user_ids": [self.follower.id],
                "group_ids": [group.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["status"], TrailPlaybackShareRequest.STATUS_PENDING)
        self.assertEqual(TrailPlaybackShareRequest.objects.filter(trail=trail).count(), 1)

    def test_share_playback_request_allows_empty_targets(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Playback Export Only Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
        )

        self._auth(self.owner)
        response = self.client.post(
            f"/api/trailbook/{trail.id}/share-playback/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(response.data["success"])
        request_id = response.data["request_id"]
        created = TrailPlaybackShareRequest.objects.get(id=request_id)
        self.assertEqual(created.user_ids, [])
        self.assertEqual(created.group_ids, [])

    def test_playback_request_status_endpoint_permissions(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Playback Status Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
        )
        group = ChatThread.objects.create(
            is_group=True,
            name="Playback Status Group",
            created_by=self.owner,
        )
        group.participants.set([self.owner, self.follower])

        self._auth(self.owner)
        create_res = self.client.post(
            f"/api/trailbook/{trail.id}/share-playback/",
            {
                "user_ids": [self.follower.id],
                "group_ids": [group.id],
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_202_ACCEPTED)
        request_id = create_res.data["request_id"]

        owner_status = self.client.get(f"/api/trailbook/playback-requests/{request_id}/")
        self.assertEqual(owner_status.status_code, status.HTTP_200_OK)
        self.assertEqual(owner_status.data["status"], TrailPlaybackShareRequest.STATUS_PENDING)
        self.assertEqual(owner_status.data["progress_percent"], 0)
        self.assertIsNone(owner_status.data["output_video_url"])

        self._auth(self.follower)
        follower_status = self.client.get(f"/api/trailbook/playback-requests/{request_id}/")
        self.assertEqual(follower_status.status_code, status.HTTP_200_OK)

        self._auth(self.stranger)
        stranger_status = self.client.get(f"/api/trailbook/playback-requests/{request_id}/")
        self.assertEqual(stranger_status.status_code, status.HTTP_403_FORBIDDEN)

    def test_start_trail_notifies_followers(self):
        self._auth(self.owner)
        res = self.client.post(
            "/api/trailbook/start/",
            {
                "title": "Morning Route",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        follower_notifications = Notification.objects.filter(
            recipient=self.follower,
            actor=self.owner,
            type="trail_start",
        )
        self.assertEqual(follower_notifications.count(), 1)
        self.assertIn("started a new trail", follower_notifications.first().message)

    def test_share_trail_notifies_recipients(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Shared Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_PRIVATE,
        )
        group = ChatThread.objects.create(
            is_group=True,
            name="Trail Notify Group",
            created_by=self.owner,
        )
        group.participants.set([self.owner, self.follower, self.stranger])

        self._auth(self.owner)
        res = self.client.post(
            f"/api/trailbook/{trail.id}/share/",
            {
                "user_ids": [self.follower.id],
                "group_ids": [group.id],
                "share_scope": TrailEntry.SHARE_SCOPE_FULL,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.follower,
                actor=self.owner,
                type="trail_share",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.stranger,
                actor=self.owner,
                type="trail_share",
            ).exists()
        )

    def test_moment_comments_and_replies_with_notifications(self):
        trail = TrailEntry.objects.create(
            user=self.owner,
            title="Comments Trail",
            status=TrailEntry.STATUS_COMPLETED,
            visibility=TrailEntry.VISIBILITY_FOLLOWERS,
        )
        moment = TrailMoment.objects.create(
            trail=trail,
            moment_type=TrailMoment.TYPE_NOTE,
            text="A note moment",
            lat=51.0,
            lng=7.0,
        )

        self._auth(self.follower)
        comment_res = self.client.post(
            f"/api/trailbook/moments/{moment.id}/comments/",
            {"text": "Nice moment!"},
            format="json",
        )
        self.assertEqual(comment_res.status_code, status.HTTP_201_CREATED)
        comment_id = comment_res.data["id"]
        self.assertTrue(
            TrailMomentComment.objects.filter(
                id=comment_id,
                moment=moment,
                user=self.follower,
                parent__isnull=True,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.owner,
                actor=self.follower,
                type="trail_comment",
            ).exists()
        )

        self._auth(self.owner)
        reply_file = SimpleUploadedFile(
            "reply.jpg",
            b"fake-image-content",
            content_type="image/jpeg",
        )
        reply_res = self.client.post(
            f"/api/trailbook/moments/{moment.id}/comments/",
            {
                "parent_id": comment_id,
                "text": "Thanks!",
                "media_file": reply_file,
            },
            format="multipart",
        )
        self.assertEqual(reply_res.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(reply_res.data.get("media_url"))

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.follower,
                actor=self.owner,
                type="trail_reply",
            ).exists()
        )

        self._auth(self.follower)
        list_res = self.client.get(f"/api/trailbook/moments/{moment.id}/comments/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(list_res.data["count"], 2)
        self.assertEqual(len(list_res.data["results"]), 1)
        self.assertEqual(len(list_res.data["results"][0]["replies"]), 1)
