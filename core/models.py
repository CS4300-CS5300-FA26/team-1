# Create your models here.
from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    # username etup with a max length of 100 until we set actual limits
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Age/weight setup to allow empty age/weight fields in the database for now, can adjust later if needed
    age = models.PositiveIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} (Age: {self.age}, Weight: {self.weight})"