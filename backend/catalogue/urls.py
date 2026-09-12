from rest_framework.routers import SimpleRouter

from .views import AccessoryViewSet, CableSizeViewSet, CableTypeViewSet

router = SimpleRouter()
router.register("cable-types", CableTypeViewSet, basename="cable-type")
router.register("sizes", CableSizeViewSet, basename="cable-size")
router.register("accessories", AccessoryViewSet, basename="accessory")

urlpatterns = router.urls
