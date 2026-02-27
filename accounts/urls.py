from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import RegisterView, VerifyOTPView, LoginView, ProfileView
from . import views

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("resend-otp/", views.ResendOTPView.as_view()),

    path("login/", LoginView.as_view(), name="login"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/update/", views.ProfileUpdateView.as_view(), name="profile-update"),
    path("search/", views.ProfileSearchView.as_view(), name="profile-search"),
    path("profile/<int:pk>/", views.ProfileDetailView.as_view(), name="profile-detail"), 

    path("profile/<int:pk>/follow-toggle/", views.ProfileFollowToggleView.as_view(), name="profile-follow-toggle",),
    path("profile/<int:pk>/followers/",views.ProfileFollowersListView.as_view(),name="profile-followers",),
    path("profile/<int:pk>/following/",views.ProfileFollowingListView.as_view(),name="profile-following",),
    path("password-reset/", views.PasswordResetView.as_view()),
    path("password-reset-confirm/", views.PasswordResetConfirmView.as_view()),
    path(
        "notifications/",
        views.notifications_list,
        name="notifications-list",
    ),
    path(
        "notifications/unread-count/",
        views.unread_notifications_count,
        name="notifications-unread-count",
    ),
    path(
        "notifications/mark-all-read/",
        views.mark_all_notifications_read,
        name="notifications-mark-all-read",
    ),
    path(
        "chat/unread-counts/",
        views.chat_unread_counts,
        name="chat-unread-counts",
    ),
    path(
    "push/register/",
    views.register_push_token,
    ),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("verify-password/", views.verify_password, name="verify_password"),

    # Chat
    path("chat/threads/", views.ChatThreadListCreateView.as_view()),
    path("chat/threads/self/", views.ChatSelfThreadView.as_view()),
    path(
        "chat/threads/<int:thread_id>/",
        views.ChatThreadDetailView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/messages/",
        views.ChatMessageListCreateView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/delete/",
        views.ChatThreadDeleteView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/leave/",
        views.ChatThreadLeaveView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/messages/<int:message_id>/delete/",
        views.ChatMessageDeleteView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/messages/<int:message_id>/reactions/",
        views.ChatMessageReactionView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/update/",
        views.ChatThreadUpdateView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/members/",
        views.ChatThreadMembersView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/read/",
        views.mark_thread_messages_read,
    ),
    path(
        "chat/threads/<int:thread_id>/privacy/",
        views.ChatThreadPrivacyView.as_view(),
    ),
    path(
        "chat/threads/<int:thread_id>/media/",
        views.ChatThreadMediaView.as_view(),
    ),

  
]
