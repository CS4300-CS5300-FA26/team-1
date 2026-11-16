"""Tests for week-to-week workout variety: split styles, weekly rotation, and switching (ADR-013).

The Gherkin scenarios for this story are in features/workout_variety.feature.
"""

from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from . import generator
from .generator import PlanGenerationError, available_splits, generate_plan, next_split, split_of
from .models import WeeklyPlan
from .services import MAX_SPLIT_SWITCHES, NEXT_SPLIT, SwitchResult, get_weekly_plan, switch_split, week_start_for
from .tests import PlanTestBase, make_profile, training_days

WEEK_1 = date(2026, 10, 27)  # a Tuesday; its week starts Monday 26 October
WEEK_2 = date(2026, 11, 3)
WEEK_3 = date(2026, 11, 10)
BODYWEIGHT_NAMES = {
    name for options in generator.EXERCISES.values() for required, name in options if required == 'none'
}

DEFAULT_SPLITS = {'beginner': 'full_body', 'intermediate': 'upper_lower', 'advanced': 'upper_lower'}


def last_week():
    """A day in the week before the current one, for tests that go through the views."""
    return week_start_for(timezone.localdate()) - timedelta(days=7)


class SplitStyleTests(SimpleTestCase):
    def test_default_split_is_unchanged_for_each_level(self):
        for level, expected in DEFAULT_SPLITS.items():
            self.assertEqual(generate_plan(make_profile(experience_level=level))['split'], expected, level)

    def test_every_style_gives_the_same_number_of_training_days_and_macros(self):
        for level, days in generator.TRAINING_DAYS.items():
            default = generate_plan(make_profile(experience_level=level))
            for style in available_splits(days):
                plan = generate_plan(make_profile(experience_level=level), split=style)
                self.assertEqual(len(plan['days']), 7)
                self.assertEqual(len(training_days(plan)), days, (level, style))
                self.assertEqual(plan['macros'], default['macros'], (level, style))
                self.assertEqual(plan['split'], style)

    def test_push_pull_legs_names_its_workouts(self):
        plan = generate_plan(make_profile(), split='push_pull_legs')
        self.assertEqual([d['name'] for d in training_days(plan)], ['Push', 'Pull', 'Legs'])

    def test_every_style_works_with_bodyweight_only(self):
        for level, days in generator.TRAINING_DAYS.items():
            for style in available_splits(days):
                plan = generate_plan(make_profile(experience_level=level, equipment=['none']), split=style)
                names = {e['name'] for d in plan['days'] for e in d['exercises']}
                self.assertLessEqual(names, BODYWEIGHT_NAMES, (level, style))

    def test_every_training_day_has_enough_exercises(self):
        for level, days in generator.TRAINING_DAYS.items():
            for style in available_splits(days):
                plan = generate_plan(make_profile(experience_level=level), split=style)
                for day in training_days(plan):
                    self.assertGreaterEqual(len(day['exercises']), 3, (level, style, day['name']))

    def test_a_split_that_is_not_available_for_the_training_days_raises(self):
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(experience_level='intermediate'), split='full_body')
        with self.assertRaises(PlanGenerationError):
            generate_plan(make_profile(), split='not-a-split')

    def test_explicit_split_wins_over_after(self):
        plan = generate_plan(make_profile(experience_level='intermediate'), split='upper_lower', after='upper_lower')
        self.assertEqual(plan['split'], 'upper_lower')


class RotationTests(SimpleTestCase):
    def test_available_splits_by_training_days(self):
        self.assertEqual(available_splits(3), ['full_body', 'upper_lower', 'push_pull_legs'])
        self.assertEqual(available_splits(4), ['upper_lower', 'push_pull_legs'])
        self.assertEqual(available_splits(5), ['upper_lower', 'push_pull_legs'])
        self.assertEqual(available_splits(6), [])

    def test_next_split_never_repeats_and_cycles_through_every_style(self):
        for days in (3, 4, 5):
            current = available_splits(days)[0]
            seen = []
            for _ in range(len(available_splits(days)) * 2):
                following = next_split(current, days)
                self.assertNotEqual(following, current)
                seen.append(following)
                current = following
            self.assertEqual(set(seen), set(available_splits(days)))

    def test_next_split_starts_at_the_first_style_when_previous_is_unknown_or_unavailable(self):
        self.assertEqual(next_split(None, 4), 'upper_lower')
        self.assertEqual(next_split('full_body', 4), 'upper_lower')  # full body isn't offered at 4 days

    def test_after_picks_the_next_style(self):
        plan = generate_plan(make_profile(experience_level='intermediate'), after='upper_lower')
        self.assertEqual(plan['split'], 'push_pull_legs')

    def test_split_of_reads_the_saved_style(self):
        self.assertEqual(split_of({'split': 'push_pull_legs', 'days': []}), 'push_pull_legs')

    def test_split_of_infers_the_style_of_plans_saved_before_splits_existed(self):
        for level, expected in DEFAULT_SPLITS.items():
            plan = generate_plan(make_profile(experience_level=level))
            del plan['split']
            self.assertEqual(split_of(plan), expected, level)

    def test_split_of_returns_none_when_it_cannot_tell(self):
        self.assertIsNone(split_of({'days': []}))
        self.assertIsNone(split_of({'split': 'bogus', 'days': []}))


class WeeklyRotationTests(PlanTestBase):
    def test_first_ever_plan_uses_the_default_split(self):
        user = self.make_user()
        plan, _ = get_weekly_plan(user.userprofile, WEEK_1)
        self.assertEqual(plan['split'], 'upper_lower')

    def test_each_new_week_moves_to_a_different_split(self):
        profile = self.make_user().userprofile
        splits = [get_weekly_plan(profile, week)[0]['split'] for week in (WEEK_1, WEEK_2, WEEK_3)]
        self.assertEqual(splits, ['upper_lower', 'push_pull_legs', 'upper_lower'])

    def test_a_plan_saved_before_splits_existed_still_rotates(self):
        user = self.make_user()
        legacy = generate_plan(user.userprofile)
        del legacy['split']
        WeeklyPlan.objects.create(user=user, week_start=date(2026, 10, 26), data=legacy)
        plan, _ = get_weekly_plan(user.userprofile, WEEK_2)
        self.assertEqual(plan['split'], 'push_pull_legs')

    def test_rotation_follows_the_most_recent_earlier_plan_after_a_skipped_week(self):
        profile = self.make_user().userprofile
        get_weekly_plan(profile, WEEK_1)  # upper_lower; the user skips the next week entirely
        plan, _ = get_weekly_plan(profile, WEEK_3)
        self.assertEqual(plan['split'], 'push_pull_legs')

    def test_rotation_ignores_other_users_plans(self):
        alice = self.make_user('alice').userprofile
        bob = self.make_user('bob').userprofile
        get_weekly_plan(alice, WEEK_1)
        plan, _ = get_weekly_plan(bob, WEEK_2)
        self.assertEqual(plan['split'], 'upper_lower')  # bob has no history, so he gets the default

    def test_the_plan_stays_the_same_all_week(self):
        profile = self.make_user().userprofile
        first, _ = get_weekly_plan(profile, WEEK_1)
        second, _ = get_weekly_plan(profile, date(2026, 10, 30))
        self.assertEqual(first, second)


class SwitchSplitServiceTests(PlanTestBase):
    def setUp(self):
        self.user = self.make_user()
        self.profile = self.user.userprofile

    def saved(self):
        """The plan for the week of WEEK_1."""
        return WeeklyPlan.objects.get(user=self.user, week_start=week_start_for(WEEK_1))

    def test_choosing_a_split_before_a_plan_exists_creates_the_plan_without_using_a_switch(self):
        self.assertEqual(switch_split(self.profile, 'push_pull_legs', WEEK_1), SwitchResult.CHANGED)
        data = self.saved().data
        self.assertEqual(data['split'], 'push_pull_legs')
        self.assertNotIn('switches', data)

    def test_next_before_a_plan_exists_follows_the_rotation(self):
        get_weekly_plan(self.profile, date(2026, 10, 19))  # the week before WEEK_1: upper_lower
        self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_1), SwitchResult.CHANGED)
        self.assertEqual(self.saved().data['split'], 'push_pull_legs')

    def test_switching_replaces_the_workouts_but_keeps_the_macros_and_counts_the_switch(self):
        before, _ = get_weekly_plan(self.profile, WEEK_1)
        # Pretend the profile changed since: macros are meant to stay as saved for the whole week (ADR-012).
        stored = WeeklyPlan.objects.get(user=self.user)
        stored.data['macros'] = {'calories': 2100, 'protein': 150, 'carbs': 220, 'fat': 58}
        stored.save()
        self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_1), SwitchResult.CHANGED)
        after = self.saved().data
        self.assertNotEqual(after['split'], before['split'])
        self.assertEqual(after['macros'], {'calories': 2100, 'protein': 150, 'carbs': 220, 'fat': 58})
        self.assertEqual(after['switches'], 1)
        self.assertEqual(len(training_days(after)), len(training_days(before)))
        self.assertEqual(WeeklyPlan.objects.filter(user=self.user).count(), 1)

    def test_choosing_the_current_split_changes_nothing_and_uses_no_switch(self):
        before, _ = get_weekly_plan(self.profile, WEEK_1)
        self.assertEqual(switch_split(self.profile, before['split'], WEEK_1), SwitchResult.UNCHANGED)
        self.assertEqual(self.saved().data, before)

    def test_switches_stop_at_the_weekly_limit_and_leave_the_plan_alone(self):
        get_weekly_plan(self.profile, WEEK_1)
        for _ in range(MAX_SPLIT_SWITCHES):
            self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_1), SwitchResult.CHANGED)
        at_limit = self.saved().data
        self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_1), SwitchResult.LIMIT)
        self.assertEqual(self.saved().data, at_limit)

    def test_the_limit_resets_each_week(self):
        get_weekly_plan(self.profile, WEEK_1)
        for _ in range(MAX_SPLIT_SWITCHES):
            switch_split(self.profile, NEXT_SPLIT, WEEK_1)
        self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_1), SwitchResult.LIMIT)
        get_weekly_plan(self.profile, WEEK_2)  # a new week gets a new plan, with no switches used
        self.assertEqual(switch_split(self.profile, NEXT_SPLIT, WEEK_2), SwitchResult.CHANGED)

    def test_a_split_that_does_not_fit_the_training_days_is_unavailable(self):
        before, _ = get_weekly_plan(self.profile, WEEK_1)  # intermediate: 4 days, so no full body
        self.assertEqual(switch_split(self.profile, 'full_body', WEEK_1), SwitchResult.UNAVAILABLE)
        self.assertEqual(self.saved().data, before)

    def test_generator_failure_leaves_the_plan_as_it_was(self):
        before, _ = get_weekly_plan(self.profile, WEEK_1)
        with (
            mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')),
            self.assertLogs('plans.services', level='ERROR'),
        ):
            result = switch_split(self.profile, NEXT_SPLIT, WEEK_1)
        self.assertEqual(result, SwitchResult.UNAVAILABLE)
        self.assertEqual(self.saved().data, before)


class ChangeSplitViewTests(PlanTestBase):
    def post(self, split):
        return self.client.post(reverse('change_split'), {'split': split}, follow=True)

    def test_login_required(self):
        response = self.client.post(reverse('change_split'), {'split': 'next'})
        self.assertRedirects(
            response, f'{reverse("login")}?next={reverse("change_split")}', fetch_redirect_response=False
        )
        self.assertEqual(WeeklyPlan.objects.count(), 0)

    def test_only_post_is_allowed(self):
        self.log_in(self.make_user())
        self.assertEqual(self.client.get(reverse('change_split')).status_code, 405)

    def test_user_who_has_not_onboarded_is_sent_to_onboarding(self):
        self.log_in(self.make_user(completed=False))
        response = self.client.post(reverse('change_split'), {'split': 'next'})
        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)
        self.assertEqual(WeeklyPlan.objects.count(), 0)

    def test_switch_it_up_changes_the_split_and_confirms(self):
        self.log_in(self.make_user())
        before = self.client.get(reverse('this_week')).context
        response = self.post('next')
        self.assertContains(response, 'Your workout split is updated')
        self.assertNotEqual(response.context['split_key'], before['split_key'])
        self.assertEqual(response.context['macros'], before['macros'])

    def test_choosing_a_split_from_the_list(self):
        self.log_in(self.make_user())
        response = self.post('push_pull_legs')
        self.assertEqual(response.context['split_key'], 'push_pull_legs')
        self.assertContains(response, 'Push / Pull / Legs')

    def test_choosing_the_current_split_says_so(self):
        self.log_in(self.make_user())
        current = self.client.get(reverse('this_week')).context['split_key']
        self.assertContains(self.post(current), 'You are already on that split')

    def test_unknown_split_is_rejected_and_nothing_is_saved(self):
        self.log_in(self.make_user())
        response = self.client.post(reverse('change_split'), {'split': '<script>alert(1)</script>'})
        self.assertRedirects(response, reverse('this_week'), fetch_redirect_response=False)
        self.assertEqual(WeeklyPlan.objects.count(), 0)  # checked before the page can create a plan
        page = self.client.get(reverse('this_week'))
        self.assertContains(page, 'Choose one of the listed workout splits')
        self.assertNotContains(page, '<script>alert(1)</script>')

    def test_limit_message_after_too_many_switches(self):
        self.log_in(self.make_user())
        self.client.get(reverse('this_week'))
        for _ in range(MAX_SPLIT_SWITCHES):
            self.post('next')
        response = self.post('next')
        self.assertContains(response, f'reached the limit of {MAX_SPLIT_SWITCHES} split switches')
        self.assertEqual(response.context['switches_left'], 0)

    def test_users_only_change_their_own_plan(self):
        alice = self.make_user('alice')
        bob = self.make_user('bob')
        self.log_in(bob)
        self.client.get(reverse('this_week'))
        bobs_plan = WeeklyPlan.objects.get(user=bob).data
        self.client.logout()
        self.log_in(alice)
        self.client.get(reverse('this_week'))
        self.post('next')
        self.assertEqual(WeeklyPlan.objects.get(user=bob).data, bobs_plan)
        self.assertEqual(WeeklyPlan.objects.get(user=alice).data['switches'], 1)


class ThisWeekSplitDisplayTests(PlanTestBase):
    def test_shows_the_split_and_the_controls(self):
        self.log_in(self.make_user())
        response = self.client.get(reverse('this_week'))
        self.assertContains(response, 'Split this week:')
        self.assertContains(response, 'Upper / Lower')
        self.assertContains(response, 'Switch it up')
        self.assertContains(response, reverse('change_split'))
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertEqual(response.context['switches_left'], MAX_SPLIT_SWITCHES)

    def test_only_offers_splits_that_fit_the_training_days(self):
        self.log_in(self.make_user())  # intermediate: 4 days
        keys = [key for key, _ in self.client.get(reverse('this_week')).context['split_choices']]
        self.assertEqual(keys, ['upper_lower', 'push_pull_legs'])

    def test_starter_plan_hides_the_split_controls(self):
        self.log_in(self.make_user())
        with (
            mock.patch('plans.services.generate_plan', side_effect=RuntimeError('down')),
            self.assertLogs('plans.services', level='ERROR'),
        ):
            response = self.client.get(reverse('this_week'))
        self.assertContains(response, 'starter plan')
        self.assertNotContains(response, 'Switch it up')
        self.assertNotContains(response, 'Split this week:')

    def test_a_week_two_visit_shows_a_new_split_in_the_page(self):
        user = self.make_user()
        get_weekly_plan(user.userprofile, last_week())  # last week: upper_lower
        self.log_in(user)
        response = self.client.get(reverse('this_week'))
        self.assertEqual(response.context['split_key'], 'push_pull_legs')
        self.assertContains(response, 'Push / Pull / Legs')
