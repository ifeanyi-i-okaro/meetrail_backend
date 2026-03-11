from django.urls import path

from . import views


urlpatterns = [
    path("share/options/", views.TrailBookShareOptionsView.as_view()),
    path(
        "playback-requests/<int:request_id>/",
        views.TrailBookPlaybackShareRequestStatusView.as_view(),
    ),
    path("start/", views.TrailBookStartView.as_view()),
    path("", views.TrailBookListView.as_view()),
    path("<int:trail_id>/", views.TrailBookDetailView.as_view()),
    path("<int:trail_id>/shares/", views.TrailBookShareStatusView.as_view()),
    path("<int:trail_id>/shares/revoke/", views.TrailBookShareRevokeView.as_view()),
    path("<int:trail_id>/replay/", views.TrailBookReplayView.as_view()),
    path("<int:trail_id>/share/", views.TrailBookShareView.as_view()),
    path("<int:trail_id>/share-playback/", views.TrailBookPlaybackShareView.as_view()),
    path("<int:trail_id>/points/bulk/", views.TrailBookPointBulkView.as_view()),
    path("<int:trail_id>/moments/", views.TrailBookMomentCreateView.as_view()),
    path("moments/<int:moment_id>/like/", views.TrailBookMomentLikeView.as_view()),
    path("moments/<int:moment_id>/comments/", views.TrailBookMomentCommentsView.as_view()),
    path("<int:trail_id>/stop/", views.TrailBookStopView.as_view()),
]
