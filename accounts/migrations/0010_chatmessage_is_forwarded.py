from django.db import migrations, models


def add_is_forwarded(apps, schema_editor):
    ChatMessage = apps.get_model("accounts", "ChatMessage")
    table = ChatMessage._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        columns = [
            col.name
            for col in schema_editor.connection.introspection.get_table_description(
                cursor, table
            )
        ]
    if "is_forwarded" in columns:
        return
    field = models.BooleanField(default=False)
    field.set_attributes_from_name("is_forwarded")
    schema_editor.add_field(ChatMessage, field)


def remove_is_forwarded(apps, schema_editor):
    # Optional: no-op to avoid accidental data loss on rollback
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_chatmessage_reply_to"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="chatmessage",
                    name="is_forwarded",
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_is_forwarded, remove_is_forwarded),
            ],
        ),
    ]
