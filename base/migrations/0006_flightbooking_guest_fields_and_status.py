import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0005_flightbooking_hotelbooking_userprofile'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='flightbooking',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='flight_bookings',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='flightbooking',
            name='guest_email',
            field=models.EmailField(blank=True, db_index=True, max_length=254),
        ),
        migrations.AddField(
            model_name='flightbooking',
            name='guest_name',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='flightbooking',
            name='guest_phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='flightbooking',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending confirmation'),
                    ('confirmed', 'Confirmed'),
                    ('cancelled', 'Cancelled'),
                ],
                db_index=True,
                default='pending',
                max_length=20,
            ),
        ),
    ]
