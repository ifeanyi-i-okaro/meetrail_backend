from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_chatthread_group_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="message_type",
            field=models.CharField(default="text", max_length=20),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="reply_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replies", to="accounts.chatmessage"),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="file",
            field=models.FileField(blank=True, null=True, upload_to="chat/"),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="file_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="file_size",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="deleted_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="deleted_messages", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="ChatMessageDeletion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deletions", to="accounts.chatmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="message_deletions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("message", "user")}},
        ),
    ]
