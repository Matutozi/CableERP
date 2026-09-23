"""Drop the old role column, now that 0011 has read it.

Split from 0010 so the data migration between them could still see the value it was mapping from.
Reversing restores the column; 0011's reverse then refills it.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_seed_templates_and_map_roles")]

    operations = [
        migrations.RemoveField(model_name="membership", name="role"),
    ]
