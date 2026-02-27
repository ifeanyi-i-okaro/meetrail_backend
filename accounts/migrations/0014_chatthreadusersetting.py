from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_chatthreadclear"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatThreadUserSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_hidden", models.BooleanField(default=False)),
                ("is_paused", models.BooleanField(default=False)),
                ("hidden_at", models.DateTimeField(blank=True, null=True)),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="user_settings", to="accounts.chatthread")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_settings", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("thread", "user")}},
        ),
    ]
