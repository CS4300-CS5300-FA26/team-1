from django.urls import path

from . import views

urlpatterns = [
    path('meal-plan/', views.meal_plan, name='meal_plan'),
]
