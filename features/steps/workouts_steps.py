"""Step definitions for features/workouts.feature (D-3 workout split and exercise tracking)."""

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import UserProfile
from workouts import services
from workouts.models import PlannedExercise, WorkoutSession

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


def current_week(context):
    return services.current_plan(context.user, UserProfile.objects.get(user=context.user))


@given('I have finished onboarding with {equipment}')
def step_onboarded(context, equipment):
    context.user = make_member('lifter', EQUIPMENT[equipment])
    context.test.client.force_login(context.user)


@when('I open This Week')
def step_open_this_week(context):
    context.response = context.test.client.get(reverse('workouts_this_week'))
    context.test.assertEqual(context.response.status_code, 200)


@then('I see a workout for each of my training days and rest days between them')
def step_workouts_and_rest(context):
    statuses = [day.status for day in context.response.context['days']]
    context.test.assertEqual(statuses.count('planned'), 3)  # a beginner's default
    context.test.assertEqual(statuses.count('rest'), 4)
    context.test.assertNotIn(['planned', 'planned', 'planned'], [statuses[i : i + 3] for i in range(5)])
    context.test.assertContains(context.response, 'Rest day')


def exercise_classes(context):
    return set(
        PlannedExercise.objects.filter(workout__plan=current_week(context)).values_list(
            'exercise__equipment_class', flat=True
        )
    )


@then('every exercise uses dumbbells or my body weight')
def step_dumbbells_or_bodyweight(context):
    context.test.assertLessEqual(exercise_classes(context), {'dumbbells', 'none'})
    context.test.assertIn('dumbbells', exercise_classes(context))


@then('every exercise uses my body weight')
def step_bodyweight_only(context):
    context.test.assertEqual(exercise_classes(context), {'none'})


@when('I choose to train {days:d} days a week')
def step_choose_days(context, days):
    context.response = context.test.client.post(
        reverse('workouts_preferences'), {'days_per_week': str(days)}, follow=True
    )


@then('my week has {count:d} workouts')
def step_week_has_workouts(context, count):
    context.test.assertEqual(current_week(context).workouts.count(), count)


@given('I have started the first workout of the week')
def step_started_first_workout(context):
    workout = current_week(context).workouts.order_by('day')[0]
    context.test.client.post(reverse('workouts_start', args=[workout.pk]))
    context.session = WorkoutSession.objects.get(user=context.user)


@when('I log reps and weight for the first set of each exercise and finish')
def step_log_and_finish(context):
    data = {'action': 'finish'}
    for log in services.session_log(context.session):
        if not log.planned.is_timed:
            data[f'reps_{log.planned.pk}_1'] = '10'
            data[f'weight_{log.planned.pk}_1'] = '25'
    context.response = context.test.client.post(reverse('workouts_session', args=[context.session.pk]), data)


@then('the workout is marked done')
def step_marked_done(context):
    context.test.assertRedirects(context.response, reverse('workouts_history'))
    context.session.refresh_from_db()
    context.test.assertIsNotNone(context.session.completed_at)


@then('it appears in my progress history')
def step_in_history(context):
    page = context.test.client.get(reverse('workouts_history'))
    context.test.assertContains(page, context.session.title)
    context.test.assertEqual(page.context['weeks'][0].completed, 1)


@when('I finish without logging anything')
def step_finish_empty(context):
    context.response = context.test.client.post(
        reverse('workouts_session', args=[context.session.pk]), {'action': 'finish'}
    )


@then('I am asked to log at least one set')
def step_asked_to_log(context):
    context.test.assertContains(context.response, 'Log at least one set')
    context.session.refresh_from_db()
    context.test.assertIsNone(context.session.completed_at)


@given('another member has started a workout')
def step_other_member_started(context):
    other = make_member('stranger', ['dumbbells'])
    plan = services.current_plan(other, UserProfile.objects.get(user=other))
    context.other_session = services.start_session(other, plan.workouts.order_by('day')[0])


@when('I try to open their workout')
def step_open_their_workout(context):
    context.response = context.test.client.get(reverse('workouts_session', args=[context.other_session.pk]))


@then('I get a not found response')
def step_not_found(context):
    context.test.assertEqual(context.response.status_code, 404)
