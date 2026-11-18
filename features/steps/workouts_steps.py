"""Step definitions for features/workouts.feature (exercise tracking for the plans app's weekly plan)."""

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import UserProfile
from plans.models import WeeklyPlan
from workouts import services
from workouts.domain import MINUTES, SECONDS
from workouts.models import WorkoutSession

User = get_user_model()
EQUIPMENT = {'only dumbbells': ['dumbbells'], 'no equipment': ['none']}


def make_member(username, equipment):
    user = User.objects.create_user(username=username)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=True,
        goal='build_muscle',
        experience_level='beginner',
        equipment=equipment,
        height_inches=70,
        weight=180,
        weekly_food_budget=50,
    )
    return user


def training_days(user):
    days = WeeklyPlan.objects.get(user=user).data['days']
    return [index for index, day in enumerate(days) if day['exercises']]


@given('I have finished onboarding with {equipment}')
def step_onboarded(context, equipment):
    context.user = make_member('lifter', EQUIPMENT[equipment])
    context.test.client.force_login(context.user)


@given('I have opened This Week')
def step_open_this_week(context):
    context.response = context.test.client.get(reverse('this_week'))
    context.test.assertEqual(context.response.status_code, 200)


@then('each training day has a Start workout button')
def step_start_buttons(context):
    for day in training_days(context.user):
        context.test.assertContains(context.response, f'action="{reverse("workouts_start", args=[day])}"')


@then('rest days do not')
def step_no_rest_buttons(context):
    trained = training_days(context.user)
    for day in (index for index in range(7) if index not in trained):
        context.test.assertNotContains(context.response, f'action="{reverse("workouts_start", args=[day])}"')


@given('I have started the first workout of the week')
def step_started(context):
    day = training_days(context.user)[0]
    context.test.client.post(reverse('workouts_start', args=[day]))
    context.session = WorkoutSession.objects.get(user=context.user, day=day)


@when('I log reps and weight for the first set of each exercise and finish')
def step_log_and_finish(context):
    data = {'action': 'finish'}
    for log in services.session_log(context.session):
        if log.target.kind == MINUTES:
            data[f'minutes_{log.position}_1'] = '20'
        elif log.target.kind == SECONDS:
            data[f'seconds_{log.position}_1'] = '40'
        else:
            data[f'reps_{log.position}_1'] = '10'
            data[f'weight_{log.position}_1'] = '25'
    context.response = context.test.client.post(
        reverse('workouts_session', args=[context.session.pk]), data, follow=True
    )


@then('the workout is marked done')
def step_done(context):
    context.session.refresh_from_db()
    context.test.assertTrue(context.session.is_complete)


@then('it appears in my progress history')
def step_in_history(context):
    context.test.assertRedirects(context.response, reverse('workouts_history'))
    context.test.assertContains(context.response, context.session.title)


@then('This Week shows it as done')
def step_this_week_done(context):
    response = context.test.client.get(reverse('this_week'))
    context.test.assertContains(response, 'View workout')
    context.test.assertContains(response, reverse('workouts_session', args=[context.session.pk]))


@when('I finish without logging anything')
def step_finish_empty(context):
    context.response = context.test.client.post(
        reverse('workouts_session', args=[context.session.pk]), {'action': 'finish'}
    )


@then('I am asked to log at least one set')
def step_asked_to_log(context):
    context.test.assertContains(context.response, 'Log at least one set before finishing the workout.')
    context.session.refresh_from_db()
    context.test.assertFalse(context.session.is_complete)


@given('another member has started a workout')
def step_other_started(context):
    other = make_member('stranger', ['dumbbells'])
    context.test.client.force_login(other)
    context.test.client.get(reverse('this_week'))
    day = training_days(other)[0]
    context.test.client.post(reverse('workouts_start', args=[day]))
    context.other_session = WorkoutSession.objects.get(user=other)
    context.test.client.force_login(context.user)


@when('I try to open their workout')
def step_open_theirs(context):
    context.response = context.test.client.get(reverse('workouts_session', args=[context.other_session.pk]))


@then('I get a not found response')
def step_not_found(context):
    context.test.assertEqual(context.response.status_code, 404)
