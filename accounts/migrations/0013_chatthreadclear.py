from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_chatmessage_reaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatThreadClear",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cleared_at", models.DateTimeField(auto_now=True)),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="clears", to="accounts.chatthread")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="thread_clears", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("thread", "user")}},
        ),
    ]
