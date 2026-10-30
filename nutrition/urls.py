from django.urls import path

from . import views

urlpatterns = [
    path('meal-plan/', views.meal_plan, name='meal_plan'),
    path('meal-plan/details/', views.meal_details_fragment, name='meal_plan_details'),
]
