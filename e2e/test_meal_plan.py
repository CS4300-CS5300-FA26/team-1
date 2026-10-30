"""End-to-end tests for onboarding and the Meal Plan page in a real browser (Playwright + Chromium).

Skipped unless E2E=1, because they need a browser: `uv run playwright install chromium` once, then
    E2E=1 uv run python manage.py test e2e
They run against Django's live test server with the starter recipe catalog (tests never call the
recipe API; see TESTING in settings).
"""

import os
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings, tag
from django.utils import timezone
from playwright.sync_api import Browser, Playwright, sync_playwright

from core.models import UserProfile
from nutrition.planner import DAY_NAMES

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'


@tag('e2e')
@skipUnless(os.environ.get('E2E') == '1', 'Set E2E=1 to run browser tests.')
class MealPlanBrowserTests(StaticLiveServerTestCase):
    playwright: Playwright
    browser: Browser

    @classmethod
    def setUpClass(cls):
        # Playwright's sync API runs an event loop in this thread; the ORM calls the tests make
        # between browser steps are still synchronous, so Django's async guard can be relaxed here.
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)

    def setUp(self):
        self.new_page()

    def new_page(self, **context_options):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900}, **context_options)
        self.page = self.context.new_page()
        self.addCleanup(self.context.close)

    def log_in(self, budget='50.00', meal_pattern='three', onboarded=True):
        user = User.objects.create_user('e2e', 'e2e@example.com', PASSWORD)
        UserProfile.objects.create(
            user=user,
            onboarding_completed=onboarded,
            weekly_food_budget=Decimal(budget) if onboarded else None,
            meal_pattern=meal_pattern if onboarded else '',
        )
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.get_by_label('Email or username').fill('e2e@example.com')
        self.page.get_by_label('Password').fill(PASSWORD)
        self.page.get_by_role('button', name='Log in').click()
        self.page.wait_for_url('**/onboarding/' if not onboarded else '**/dashboard/')

    def open_meal_plan(self):
        self.page.get_by_role('navigation', name='Main').get_by_role('link', name='Meal plan').click()
        self.page.wait_for_url('**/meal-plan/**')

    def visible_panel(self):
        return self.page.locator('[data-day-panel]:visible')

    def mark_page(self):
        """Tag the window so we can tell whether a later step reloaded the page."""
        self.page.evaluate('window.__noReload = true')

    def assert_not_reloaded(self):
        self.assertTrue(self.page.evaluate('window.__noReload === true'))

    def test_onboarding_meal_choice_shapes_the_plan(self):
        self.log_in(onboarded=False)
        self.page.get_by_label('Your goal').select_option('build_muscle')
        self.page.get_by_label('Height (inches)').fill('70')
        self.page.get_by_label('Weight (lb)').fill('180')
        self.page.get_by_label('Experience level').select_option('beginner')
        self.page.get_by_label('Weekly food budget ($)').fill('40')
        self.page.get_by_label('Breakfast and dinner').check()
        self.page.get_by_label('Dumbbells').check()
        self.page.get_by_role('button', name='Finish').click()
        self.page.wait_for_url('**/dashboard/')
        self.open_meal_plan()
        eyebrows = self.visible_panel().locator('.media__eyebrow').all_inner_texts()
        self.assertEqual([text.lower() for text in eyebrows], ['breakfast', 'dinner'])

    def test_plan_within_budget_opens_on_today_with_three_meals(self):
        self.log_in('50.00')
        self.open_meal_plan()
        today = DAY_NAMES[timezone.localdate().weekday()]
        self.assertEqual(self.page.locator('[data-day-current]').inner_text(), today)
        self.assertEqual(self.visible_panel().count(), 1)
        self.assertEqual(self.visible_panel().get_by_role('heading', level=2).inner_text(), today)
        self.assertEqual(self.visible_panel().locator('[data-meal-link]').count(), 3)
        estimate = Decimal(self.page.locator('.stat__value').inner_text().removeprefix('Est. $'))
        self.assertLessEqual(estimate, Decimal('50.00'))

    def test_every_meal_in_the_week_is_different(self):
        self.log_in()
        self.open_meal_plan()
        titles = self.page.locator('[data-day-panel] .media__title').all_text_contents()
        self.assertEqual(len(titles), 21)
        self.assertEqual(len(set(titles)), 21)

    def test_day_picker_switches_days_in_place(self):
        self.log_in()
        self.open_meal_plan()
        self.mark_page()
        self.page.get_by_role('link', name='Friday').click()
        self.assertEqual(self.page.locator('[data-day-current]').inner_text(), 'Friday')
        self.assertEqual(self.visible_panel().get_attribute('data-day-panel'), 'friday')
        self.assertEqual(self.page.get_by_role('link', name='Friday').get_attribute('aria-current'), 'true')
        self.assertIn('day=friday', self.page.url)
        self.page.get_by_role('link', name='Next day').click()
        self.assertEqual(self.page.locator('[data-day-current]').inner_text(), 'Saturday')
        self.page.get_by_role('link', name='Previous day').click()
        self.page.get_by_role('link', name='Previous day').click()
        self.assertEqual(self.page.locator('[data-day-current]').inner_text(), 'Thursday')
        # The details panel follows the day: it shows that day's first meal.
        self.page.wait_for_function("document.querySelector('[data-meal-details]').textContent.includes('Thursday')")
        self.assert_not_reloaded()

    def test_selecting_a_meal_shows_its_details_beside_the_list(self):
        self.log_in()
        self.open_meal_plan()
        self.mark_page()
        dinner = self.visible_panel().locator('[data-meal="dinner"]')
        title = dinner.locator('.media__title').inner_text()
        dinner.click()
        details = self.page.get_by_role('complementary', name='Selected meal')
        self.page.wait_for_function(
            "title => document.querySelector('#meal-details-title').textContent === title", arg=title
        )
        self.assertIn('Ingredients', details.inner_text())
        self.assertIn('Instructions', details.inner_text())
        self.assertGreater(details.locator('.ingredient-list li').count(), 0)
        self.assertEqual(dinner.get_attribute('aria-current'), 'true')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'meal-details-title')
        self.assertIn('meal=dinner', self.page.url)
        self.assert_not_reloaded()

    def test_everything_works_without_javascript(self):
        self.new_page(java_script_enabled=False)
        self.log_in()
        self.open_meal_plan()
        self.page.get_by_role('link', name='Sunday').click()
        self.page.wait_for_url('**day=sunday**')
        self.assertEqual(self.visible_panel().get_attribute('data-day-panel'), 'sunday')
        lunch = self.visible_panel().locator('[data-meal="lunch"]')
        title = lunch.locator('.media__title').inner_text()
        lunch.click()
        self.page.wait_for_url('**meal=lunch**')
        self.assertEqual(self.page.locator('#meal-details-title').inner_text(), title)

    def test_budget_too_low_shows_the_over_budget_notice(self):
        self.log_in('10.00')
        self.open_meal_plan()
        self.assertIn('over your $10.00 budget', self.page.get_by_role('status').inner_text())
        self.assertEqual(self.page.locator('[data-day-panel] [data-meal-link]').count(), 21)

    def test_zero_budget_still_gets_a_plan_with_the_whole_cost_as_shortfall(self):
        self.log_in('0.00')
        self.open_meal_plan()
        estimate = self.page.locator('.stat__value').inner_text().removeprefix('Est. ')
        self.assertIn(f'{estimate} over your $0.00 budget', self.page.get_by_role('status').inner_text())

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_recipe_service_down_still_lets_you_get_back_to_workouts(self):
        self.log_in()
        self.open_meal_plan()
        self.assertIn('temporarily unavailable', self.page.get_by_role('status').inner_text())
        self.page.get_by_role('link', name='Go to your dashboard').click()
        self.page.wait_for_url('**/dashboard/')
        self.assertEqual(self.page.get_by_role('heading', level=1).inner_text(), 'Dashboard')

    def test_skip_link_is_the_first_tab_stop_and_moves_focus_to_main(self):
        self.log_in()
        self.open_meal_plan()
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.textContent.trim()'), 'Skip to main content')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'main')

    def test_dark_mode_toggle_switches_and_persists(self):
        self.log_in()
        self.open_meal_plan()
        toggle = self.page.get_by_role('button', name='Dark mode')
        after = 'false' if toggle.get_attribute('aria-pressed') == 'true' else 'true'
        toggle.click()
        self.assertEqual(toggle.get_attribute('aria-pressed'), after)
        self.page.reload()
        self.assertEqual(self.page.get_by_role('button', name='Dark mode').get_attribute('aria-pressed'), after)

    def test_phone_width_has_no_horizontal_scroll(self):
        self.log_in()
        self.page.set_viewport_size({'width': 375, 'height': 800})
        self.open_meal_plan()
        overflow = self.page.evaluate('document.scrollingElement.scrollWidth - window.innerWidth')
        self.assertLessEqual(overflow, 0)
