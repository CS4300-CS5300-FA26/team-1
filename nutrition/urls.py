from django.urls import path

from . import views

urlpatterns = [
    path('meal-plan/', views.meal_plan, name='meal_plan'),
    path('meal-plan/details/', views.meal_details_fragment, name='meal_plan_details'),
    path('meal-plan/save/', views.save_plan, name='meal_plan_save'),
    path('meal-plan/new/', views.new_plan, name='meal_plan_new'),
    path('meal-plan/discard/', views.discard_plan, name='meal_plan_discard'),
    path('meal-plan/report/', views.meal_plan_report, name='meal_plan_report'),
    path('meal-plan/report/ingredients.csv', views.ingredients_download, name='meal_plan_ingredients_csv'),
]
