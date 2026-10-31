"""End-to-end tests for onboarding and the Meal Plan page in a real browser (Playwright + Chromium).

Skipped unless E2E=1, because they need a browser: `uv run playwright install chromium` once, then
    E2E=1 uv run python manage.py test e2e
They run against Django's live test server with FitPro's recipe catalog (loaded into the test database after
migrations; see nutrition/apps.py). Nothing calls the network.
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
        self.new_page()

    def new_page(self, **context_options):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900}, **context_options)
        self.page = self.context.new_page()
        self.addCleanup(self.context.close)

    def log_in(self, budget='50.00', meals=('breakfast', 'lunch', 'dinner'), onboarded=True):
        user = User.objects.create_user('e2e', 'e2e@example.com', PASSWORD)
        UserProfile.objects.create(
            user=user,
            onboarding_completed=onboarded,
            weekly_food_budget=Decimal(budget) if onboarded else None,
            planned_meals=list(meals) if onboarded else [],
        )
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.get_by_label('Email or username').fill('e2e@example.com')
        self.page.get_by_label('Password').fill(PASSWORD)
        self.page.get_by_role('button', name='Log in').click()
        self.page.wait_for_url('**/onboarding/' if not onboarded else '**/dashboard/')

    def open_meal_plan(self):
        self.page.get_by_role('navigation', name='Main').get_by_role('link', name='Meal plan').click()
        self.page.wait_for_url('**/meal-plan/**')

    def visible_day(self):
        return self.page.locator('[data-day-panel]:visible')

    def visible_cards(self):
        return self.visible_day().locator('.meal-card')

    def scroll_y(self):
        return self.page.evaluate('window.scrollY')

    def test_onboarding_meal_checkboxes_shape_the_plan(self):
        self.log_in(onboarded=False)
        for meal in ('Breakfast', 'Lunch', 'Dinner'):
            self.assertTrue(self.page.get_by_label(meal, exact=True).is_checked())
        self.page.get_by_label('Your goal').select_option('build_muscle')
        self.page.get_by_label('Height (inches)').fill('70')
        self.page.get_by_label('Weight (lb)').fill('180')
        self.page.get_by_label('Experience level').select_option('beginner')
        self.page.get_by_label('Weekly food budget ($)').fill('40')
        self.page.get_by_label('Lunch', exact=True).uncheck()
        self.page.get_by_label('Dumbbells').check()
        self.page.get_by_role('button', name='Finish').click()
        self.page.wait_for_url('**/dashboard/')
        self.open_meal_plan()
        eyebrows = self.visible_cards().locator('.eyebrow').evaluate_all('els => els.map(e => e.textContent)')
        self.assertEqual([text.split()[0] for text in eyebrows], ['Breakfast', 'Dinner'])

    def test_one_day_at_a_time_with_the_fallback_note(self):
        self.log_in()
        self.open_meal_plan()
        self.assertEqual(self.visible_day().count(), 1)
        self.assertEqual(self.visible_cards().count(), 3)
        note = self.page.get_by_role('note').inner_text()
        self.assertIn('FDA Daily Values', note)
        self.assertIn("Grocery prices aren't available yet", note)

    def test_days_switch_in_place_without_reloading_or_scrolling(self):
        self.log_in()
        self.open_meal_plan()
        self.page.evaluate('window.__noReload = true')
        self.page.get_by_role('link', name='Friday').scroll_into_view_if_needed()
        before = self.scroll_y()
        self.page.get_by_role('link', name='Friday').click()
        self.assertEqual(self.visible_day().get_attribute('data-day-panel'), 'friday')
        self.assertEqual(self.page.locator('[data-day-current]').inner_text(), 'Friday')
        self.assertIn('day=friday', self.page.url)
        self.assertEqual(self.scroll_y(), before)
        self.page.get_by_role('link', name='Next day').click()
        self.assertEqual(self.visible_day().get_attribute('data-day-panel'), 'saturday')
        self.assertTrue(self.page.evaluate('window.__noReload === true'))

    def test_a_recipe_opens_in_place_with_the_keyboard(self):
        self.log_in()
        self.open_meal_plan()
        card = self.visible_cards().nth(1)
        summary = card.locator('summary')
        summary.scroll_into_view_if_needed()
        top = card.bounding_box()
        before = self.scroll_y()
        summary.focus()
        self.page.keyboard.press('Enter')
        self.assertTrue(card.locator('.ingredient-grid').is_visible())
        self.assertTrue(card.locator('.steps').is_visible())
        self.assertEqual(self.scroll_y(), before)  # the page doesn't move; the recipe opens under the meal
        assert top is not None
        after = card.bounding_box()
        assert after is not None
        self.assertEqual(round(after['y']), round(top['y']))

    def test_everything_works_without_javascript(self):
        self.new_page(java_script_enabled=False)
        self.log_in()
        self.open_meal_plan()
        self.page.get_by_role('link', name='Sunday').click()
        self.page.wait_for_url('**day=sunday**')
        self.assertEqual(self.visible_day().get_attribute('data-day-panel'), 'sunday')
        self.visible_cards().first.locator('summary').click()
        self.assertTrue(self.visible_cards().first.locator('.steps').is_visible())
        self.page.get_by_role('button', name='Generate a new meal plan').click()
        self.page.wait_for_url('**day=sunday**')
        self.assertTrue(self.page.get_by_text('Here is a new meal plan for this week.').is_visible())

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE='nutrition.testing.FlatGroceryPrices')
    def test_budget_too_low_shows_the_over_budget_notice(self):
        self.log_in(budget='10.00')
        self.open_meal_plan()
        self.assertTrue(self.page.get_by_text('over your $10.00 budget.').is_visible())
        self.assertTrue(self.page.locator('.stat__value', has_text='Est. $').is_visible())

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_recipe_service_down_still_lets_you_get_back_to_workouts(self):
        self.log_in()
        self.open_meal_plan()
        self.assertTrue(self.page.get_by_text('Meal suggestions are temporarily unavailable.').is_visible())
        self.page.get_by_role('link', name='Go to your dashboard').click()
        self.page.wait_for_url('**/dashboard/')

    def test_skip_link_is_the_first_tab_stop_and_moves_focus_to_main(self):
        self.log_in()
        self.open_meal_plan()
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.textContent.trim()'), 'Skip to main content')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'main')

    def test_phone_width_puts_totals_above_meals_without_horizontal_scroll(self):
        self.log_in()
        self.page.set_viewport_size({'width': 375, 'height': 800})
        self.open_meal_plan()
        overflow = self.page.evaluate('document.scrollingElement.scrollWidth - window.innerWidth')
        self.assertLessEqual(overflow, 0)
        meals = self.visible_day().locator('.meal-stack').bounding_box()
        totals = self.visible_day().locator('aside').bounding_box()
        assert meals is not None and totals is not None
        self.assertLess(totals['y'] + totals['height'], meals['y'] + 1)  # totals above the meals

    def test_wide_screens_put_the_totals_beside_the_meals(self):
        self.log_in()
        self.page.set_viewport_size({'width': 1440, 'height': 900})
        self.open_meal_plan()
        meals = self.visible_day().locator('.meal-stack').bounding_box()
        totals = self.visible_day().locator('aside').bounding_box()
        assert meals is not None and totals is not None
        self.assertGreater(totals['x'], meals['x'] + meals['width'] - 1)
