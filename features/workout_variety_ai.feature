Feature: AI trainer chooses my exercises
  As a gym-goer who wants fresh workouts, I want an AI trainer to choose my exercises each week,
  so that my plan stays interesting and fits my equipment, and still works when the AI trainer is not available.

  Scenario: The AI trainer builds my new week
    Given I am logged in with a completed profile
    And the AI trainer is available and suggests a valid plan
    When I open This Week from the dashboard
    Then I see the plan the AI trainer suggested

  Scenario: The AI trainer suggests something invalid
    Given I am logged in with a completed profile
    And the AI trainer suggests a plan that fails validation
    When I open This Week from the dashboard
    Then I see a full week of workouts with exercises, sets, and reps
    And the invalid AI plan was not saved

  Scenario: The AI trainer is unavailable
    Given I am logged in with a completed profile
    And the AI trainer is unavailable
    When I open This Week from the dashboard
    Then I see a full week of workouts with exercises, sets, and reps

  Scenario: The AI trainer is told nothing personal
    Given I am logged in with a completed profile
    And the AI trainer is available and suggests a valid plan
    When I open This Week from the dashboard
    Then the request to the AI trainer holds no name, email, weight, or height