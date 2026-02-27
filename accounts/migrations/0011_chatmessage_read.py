from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_chatmessage_is_forwarded"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatMessageRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reads", to="accounts.chatmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="message_reads", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("message", "user")}},
        ),
    ]
