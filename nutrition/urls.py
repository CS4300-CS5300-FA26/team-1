from django.urls import path

from . import views

urlpatterns = [
    path('meal-plan/', views.meal_plan, name='meal_plan'),
    path('meal-plan/new/', views.meal_plan_new, name='meal_plan_new'),
]
