from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_chatthread_is_private"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatthread",
            name="direct_key",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
    ]
