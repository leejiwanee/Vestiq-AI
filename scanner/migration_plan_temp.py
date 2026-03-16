from django.db import models

def add_fields(apps, schema_editor):
    ScanRow = apps.get_model('scanner', 'ScanRow')
    # No op for data, schema migration is handled by Django's makemigrations usually,
    # but here we are just planning.
    pass

class Migration(models.Migration):
    dependencies = [
        ('scanner', '0001_initial'), # This will be detected automatically
    ]

    operations = [
        models.AddField(
            model_name='scanrow',
            name='rsi',
            field=models.FloatField(null=True, blank=True),
        ),
        models.AddField(
            model_name='scanrow',
            name='rvol',
            field=models.FloatField(null=True, blank=True),
        ),
        models.AddField(
            model_name='scanrow',
            name='ma20',
            field=models.FloatField(null=True, blank=True),
        ),
        models.AddField(
            model_name='scanrow',
            name='ma60',
            field=models.FloatField(null=True, blank=True),
        ),
        models.AddField(
            model_name='scanrow',
            name='score_details',
            field=models.JSONField(default=dict, blank=True),
        ),
    ]
