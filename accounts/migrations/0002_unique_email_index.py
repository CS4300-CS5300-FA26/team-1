from django.db import migrations


class Migration(migrations.Migration):
    """Enforce case-insensitive email uniqueness on the built-in User table.

    `auth.User.email` can't be made unique without a custom user model, so this adds a unique
    index on LOWER(email) directly. Blank emails (for example from `createsuperuser`) are
    excluded. Fails if existing rows already share an email; resolve those first.
    """

    dependencies = [
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX auth_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> ''",
            reverse_sql='DROP INDEX auth_user_email_lower_uniq',
        ),
    ]
