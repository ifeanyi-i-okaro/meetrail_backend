from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from datetime import date
import random


class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, dob=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        if not username:
            raise ValueError("Username is required")
        if not dob:
            raise ValueError("Date of birth is required")

        # ✅ Age restriction: must be 13+
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 13:
            raise ValueError("User must be at least 13 years old")

        email = self.normalize_email(email)
        user = self.model(email=email, username=username, dob=dob, **extra_fields)
        user.set_password(password)
        user.is_active = False  # wait for OTP verification
        user.save()
        return user

    def create_superuser(self, email, username, password=None, dob=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, username, password, dob or date(2000, 1, 1), **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=30, unique=True)
    dob = models.DateField()
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "dob"]

    def __str__(self):
        return self.email






class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(
        max_length=10,
        choices=[("male", "Male"), ("female", "Female"), ("other", "Other")],
        blank=True
    )
    bio = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to="profiles/", blank=True, null=True)
    cover_photo = models.ImageField(upload_to="covers/", blank=True, null=True)  # ✅ Added

    followers = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="following",
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s profile"

    def follow(self, profile):
        if profile != self:
            profile.followers.add(self)

    def unfollow(self, profile):
        if self in profile.followers.all():
            profile.followers.remove(self)

    def is_following(self, profile):
        return self in profile.followers.all()

    def followers_count(self):
        return self.followers.count()

    def following_count(self):
        return self.following.count()


class OTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_valid(self):
        return (timezone.now() - self.created_at).seconds < 600 and not self.is_used

    @staticmethod
    def generate_otp():
        return str(random.randint(100000, 999999))






class ChatThread(models.Model):
    is_group = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    direct_key = models.CharField(max_length=64, blank=True, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    group_image = models.ImageField(upload_to="groups/", blank=True, null=True)
    participants = models.ManyToManyField(
        User,
        related_name="chat_threads",
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        related_name="created_chat_threads",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or f"Thread {self.id}"


class ChatMessage(models.Model):
    thread = models.ForeignKey(
        ChatThread,
        related_name="messages",
        on_delete=models.CASCADE,
    )
    sender = models.ForeignKey(
        User,
        related_name="sent_messages",
        on_delete=models.CASCADE,
    )
    body = models.TextField()
    message_type = models.CharField(
        max_length=20,
        default="text",
    )
    file = models.FileField(upload_to="chat/", blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    reply_to = models.ForeignKey(
        "self",
        related_name="replies",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    is_forwarded = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        related_name="deleted_messages",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender} → {self.thread_id}: {self.body[:30]}"


class ChatMessageDeletion(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        related_name="deletions",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="message_deletions",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")


class ChatMessageRead(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        related_name="reads",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="message_reads",
        on_delete=models.CASCADE,
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")


class ChatMessageReaction(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        related_name="reactions",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="message_reactions",
        on_delete=models.CASCADE,
    )
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")


class ChatThreadClear(models.Model):
    thread = models.ForeignKey(
        ChatThread,
        related_name="clears",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="thread_clears",
        on_delete=models.CASCADE,
    )
    cleared_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("thread", "user")


class ChatThreadUserSetting(models.Model):
    thread = models.ForeignKey(
        ChatThread,
        related_name="user_settings",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="chat_settings",
        on_delete=models.CASCADE,
    )
    is_hidden = models.BooleanField(default=False)
    is_paused = models.BooleanField(default=False)
    hidden_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("thread", "user")


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ("follow", "Follow"),
        ("like", "Like"),
        ("comment", "Comment"),
        ("message", "Message"),
    )

    recipient = models.ForeignKey(
        User,
        related_name="notifications",
        on_delete=models.CASCADE
    )
    actor = models.ForeignKey(
        User,
        related_name="actor_notifications",
        on_delete=models.CASCADE
    )
    thread = models.ForeignKey(
        "ChatThread",
        related_name="notifications",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)

  
    message = models.CharField(max_length=255)

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.actor} → {self.recipient}: {self.message}"

class PushToken(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="push_tokens",
    )
    token = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} → {self.token[:20]}"
