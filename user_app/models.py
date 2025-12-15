from django.db import models

from django.db import models
from django.contrib.auth.models import User

class GalaxyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    galaxy_api_key = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}"
