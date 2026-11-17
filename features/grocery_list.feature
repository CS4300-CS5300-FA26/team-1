Feature: D-6 Grocery list generation

Scenario: Ingredients combined
  Given my meal plan uses 2 cups of rice on Monday and 1 cup on Wednesday
  When I open Grocery List
  Then I see rice listed once as 3 cups
  And the list shows an estimated total cost

Scenario: Empty week
  Given I have no meal plan this week
  When I open Grocery List
  Then I see a prompt to create a meal plan first