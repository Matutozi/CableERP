from rest_framework.routers import SimpleRouter

from django.urls import path

from .views import AccessoryViewSet, CableSizeViewSet, CableTypeViewSet, PriceMovementsView

router = SimpleRouter()
router.register("cable-types", CableTypeViewSet, basename="cable-type")
router.register("sizes", CableSizeViewSet, basename="cable-size")
router.register("accessories", AccessoryViewSet, basename="accessory")

urlpatterns = [path("price-movements/", PriceMovementsView.as_view(), name="price-movements")] + router.urls
