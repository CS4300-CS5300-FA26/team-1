from django.urls import path

from . import views

urlpatterns = [
    path('this-week/', views.this_week, name='this_week'),
    path('nutrition/', views.nutrition, name='nutrition'),
]
