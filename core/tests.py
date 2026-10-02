from django.test import TestCase
from .models import UserProfile

# TODO: Make an actual test - the spec says we need to actually test something, but this was nice to see the passing pipeline for now
class BasicTests(TestCase):
    def test_example(self):
        self.assertTrue(True)

# Unit test to show that the model is storing the data it should
class UserProfileModelTest(TestCase):
    def test_create_user_profile(self):
        profile = UserProfile.objects.create(username="testuser", age = 22, weight = 222.22)
        self.assertEqual(profile.username , "testuser")
        self.assertEqual(profile.age , 22)
        self.assertEqual(profile.weight , 222.22)