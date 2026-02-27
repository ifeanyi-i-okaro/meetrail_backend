from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_chatmessage_media_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="reply_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replies", to="accounts.chatmessage"),
        ),
    ]
