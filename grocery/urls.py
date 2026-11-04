from django.urls import path

from . import views

urlpatterns = [
    path('grocery-list/', views.grocery_list, name='grocery_list'),
]
