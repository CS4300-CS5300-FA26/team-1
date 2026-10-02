# Create your models here.
from django.db import models

class UserProfile(models.Model):
    # username etup with a max length of 100 until we set actual limits
    username = models.CharField(max_length=100)

    # Age/weight setup to allow empty age/weight fields in the database for now, can adjust later if needed
    age = models.PositiveIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} (Age: {self.age}, Weight: {self.weight})"