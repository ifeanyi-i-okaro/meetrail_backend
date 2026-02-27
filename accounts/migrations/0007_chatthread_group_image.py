from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatthread",
            name="group_image",
            field=models.ImageField(blank=True, null=True, upload_to="groups/"),
        ),
    ]
