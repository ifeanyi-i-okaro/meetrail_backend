from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_chatthreadusersetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatthread",
            name="is_private",
            field=models.BooleanField(default=False),
        ),
    ]
