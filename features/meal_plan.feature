Feature: D-5 Weekly budget meal plan
  As a cash-strapped student, I want a week of cheap recipes that hit my macro targets,
  so that I can eat well without overspending.

  Scenario: Plan within budget
    Given my weekly food budget is $50 and my macro targets are set
    When I open Meal Plan
    Then I see recipes for each day of the week
    And the estimated weekly cost is $50 or less

  Scenario: Budget too low
    Given my weekly food budget is $10
    When I open Meal Plan
    Then I see the lowest-cost plan available
    And a notice showing how far it is over my budget

  Scenario: Recipe service unavailable
    Given the recipe service is unavailable
    When I open Meal Plan
    Then I see that meal suggestions are temporarily unavailable
    And I can still open This Week and start a workout
