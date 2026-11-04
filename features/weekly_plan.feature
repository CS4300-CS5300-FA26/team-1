Feature: Weekly workout plan and daily macro targets
  As a budget-conscious gym-goer, I want a weekly workout plan with matching daily macro targets
  generated for me, so that I get structured training and nutrition guidance without paying for
  a personal trainer.

  Scenario: See my generated plan
    Given I am logged in with a completed profile
    When I open This Week from the dashboard
    Then I see a full week of workouts with exercises, sets, and reps
    And I see today's macro targets

  Scenario: See my macro targets on the Nutrition page
    Given I am logged in with a completed profile
    When I open Nutrition from the dashboard
    Then I see my daily macro targets

  Scenario: Plan generator is down
    Given I am logged in with a completed profile
    And the plan generator is unavailable
    When I open This Week from the dashboard
    Then I see a starter plan with a full week of workouts
    And I see today's macro targets
