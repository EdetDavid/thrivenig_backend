from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views


# url for viewsets using router
router = DefaultRouter()
router.register('users', views.UserViewSet, )


urlpatterns = [
    path('', views.demo, name='home'),
    path('api/flight-search', views.flight, name='flight-search'),

    path('origin_airport_search/', views.origin_airport_search,
         name='origin_airport_search'),
    path('destination_airport_search/', views.destination_airport_search,
         name='destination_airport_search'),
    path('api/', include(router.urls)),
]
