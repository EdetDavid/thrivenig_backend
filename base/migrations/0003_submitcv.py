# Generated by Django 5.0 on 2024-06-19 20:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0002_newslettersubscription"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubmitCv",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254)),
                ("cv", models.FileField(upload_to="cvs/")),
                ("cover_letter", models.TextField()),
            ],
        ),
    ]
