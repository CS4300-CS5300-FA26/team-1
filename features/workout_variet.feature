Feature: Week-to-week workout variety
  As a gym-goer who gets bored repeating the same routine, I want my workout split to change from week to week,
  so that I stay motivated and train my body in different ways without planning it myself.

  Scenario: A new week brings a different split
    Given I am logged in with a completed profile
    And last week's saved plan used the "Upper / Lower" split
    When I open This Week from the dashboard
    Then I see a plan that does not use the "Upper / Lower" split
    And I see a full week of workouts with exercises, sets, and reps

  Scenario: My plan stays the same all week
    Given I am logged in with a completed profile
    And I have opened This Week once this week
    When I open This Week again later in the week
    Then I see the same split and exercises as before

  Scenario: Choose my preferred split for the week
    Given I am logged in with a completed profile
    When I choose the "Push / Pull / Legs" split for this week
    Then my plan includes push, pull, and legs workouts
    And I see a full week of workouts with exercises, sets, and reps

  Scenario: Switch up my plan in the middle of the week
    Given I am logged in with a completed profile
    And I have opened This Week once this week
    When I ask for a different workout split this week
    Then I see a split that is different from the one I had
    And my daily macro targets are unchanged

  Scenario: Switching too often
    Given I am logged in with a completed profile
    And I have already switched my split 3 times this week
    When I ask for a different workout split this week
    Then I am told I have reached this week's switch limit
    And my plan is unchanged

  Scenario Outline: Every split fits my equipment
    Given I am logged in with a completed profile that has no equipment
    When I choose the "<split>" split for this week
    Then every exercise in my plan can be done without equipment

    Examples:
      | split              |
      | Full Body          |
      | Upper / Lower      |
      | Push / Pull / Legs |