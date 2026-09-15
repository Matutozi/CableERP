from rest_framework.routers import SimpleRouter

from .views import WaybillViewSet

router = SimpleRouter()
router.register("waybills", WaybillViewSet, basename="waybill")

urlpatterns = router.urls
