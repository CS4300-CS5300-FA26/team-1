from django.urls import path

from . import views

urlpatterns = [
    path('this-week/', views.this_week, name='this_week'),
    path('this-week/split/', views.change_split, name='change_split'),
    path('nutrition/', views.nutrition, name='nutrition'),
]
