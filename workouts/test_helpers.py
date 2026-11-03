from django.contrib.auth.models import User

from core.models import UserProfile


def onboarded_user(username='lifter', equipment=None, goal='build_muscle', experience='beginner') -> User:
    """A user who has finished onboarding, so workout pages don't send them to the questionnaire."""
    # No password: these tests sign in with force_login, and hashing a password is the slowest part of a test.
    user = User.objects.create_user(username=username)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=True,
        goal=goal,
        experience_level=experience,
        equipment=equipment if equipment is not None else ['none'],
        height_inches=70,
        weight=180,
        weekly_food_budget=50,
    )
    return user
