from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("items/", views.CatalogItemListView.as_view(), name="item-list"),
    path("items/<slug:slug>/", views.CatalogItemDetailView.as_view(), name="item-detail"),
]
