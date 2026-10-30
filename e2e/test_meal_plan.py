"""End-to-end tests for the Meal Plan page in a real browser (Playwright + Chromium).

Skipped unless E2E=1, because they need a browser: `uv run playwright install chromium` once, then
    E2E=1 uv run python manage.py test e2e
They run against Django's live test server with the real starter recipe catalog.
"""

import os
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings, tag
from playwright.sync_api import Browser, Playwright, sync_playwright

from core.models import UserProfile

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
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.addCleanup(self.context.close)

    def log_in(self, budget='50.00'):
        user = User.objects.create_user('e2e', 'e2e@example.com', PASSWORD)
        UserProfile.objects.create(user=user, onboarding_completed=True, weekly_food_budget=Decimal(budget))
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.get_by_label('Email or username').fill('e2e@example.com')
        self.page.get_by_label('Password').fill(PASSWORD)
        self.page.get_by_role('button', name='Log in').click()
        self.page.wait_for_url('**/dashboard/')

    def open_meal_plan(self):
        self.page.get_by_role('navigation', name='Main').get_by_role('link', name='Meal plan').click()
        self.page.wait_for_url('**/meal-plan/')

    def test_plan_within_budget_from_the_navigation(self):
        self.log_in('50.00')
        self.open_meal_plan()
        self.assertEqual(self.page.get_by_role('heading', level=1).inner_text(), 'Weekly meal plan')
        days = self.page.locator('ol.media-list > li')
        self.assertEqual(days.count(), 7)
        self.assertTrue(days.first.get_by_role('heading').inner_text().startswith('Monday:'))
        estimate = Decimal(self.page.locator('.stat__value').inner_text().removeprefix('Est. $'))
        self.assertLessEqual(estimate, Decimal('50.00'))
        self.assertEqual(self.page.get_by_role('status').count(), 0)

    def test_budget_too_low_shows_the_over_budget_notice(self):
        self.log_in('10.00')
        self.open_meal_plan()
        notice = self.page.get_by_role('status')
        self.assertIn('over your $10.00 budget', notice.inner_text())
        self.assertEqual(self.page.locator('ol.media-list > li').count(), 7)

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
        focused = self.page.evaluate('document.activeElement.textContent.trim()')
        self.assertEqual(focused, 'Skip to main content')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'main')

    def test_dark_mode_toggle_switches_and_persists(self):
        self.log_in()
        self.open_meal_plan()
        toggle = self.page.get_by_role('button', name='Dark mode')
        before = toggle.get_attribute('aria-pressed')
        toggle.click()
        after = 'false' if before == 'true' else 'true'
        self.assertEqual(toggle.get_attribute('aria-pressed'), after)
        self.page.reload()
        self.assertEqual(self.page.get_by_role('button', name='Dark mode').get_attribute('aria-pressed'), after)

    def test_phone_width_has_no_horizontal_scroll(self):
        self.log_in()
        self.page.set_viewport_size({'width': 375, 'height': 800})
        self.open_meal_plan()
        overflow = self.page.evaluate('document.scrollingElement.scrollWidth - window.innerWidth')
        self.assertLessEqual(overflow, 0)
