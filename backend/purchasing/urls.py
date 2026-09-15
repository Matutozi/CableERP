from rest_framework.routers import SimpleRouter

from .views import PurchaseViewSet

router = SimpleRouter()
router.register("purchases", PurchaseViewSet, basename="purchase")

urlpatterns = router.urls
