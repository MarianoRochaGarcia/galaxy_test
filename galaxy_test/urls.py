"""
URL configuration for galaxy_test project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from . import views


from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path("buscar-fastqc/", views.buscar_reportes_fastqc, name="buscar_fastqc"),
    path("analizar-fastqc/", views.analizar_fastqc, name="analizar_fastqc"),
    path("analizar-fastqc/<str:dataset_id>/", views.analizar_fastqc, name="analizar_fastqc_especifico"),
    path("ver_historia_bioblend/<str:history_id>/", views.ver_historia_bioblend, name="ver_historia_bioblend"),
    path("listar_historias/", views.listar_historias, name="listar_historias"),
    path('analizar_fastqc_tabla/', views.analizar_fastqc_tabla, name="analizar_fastqc_tabla"),
    path('ejecutar_fastqc', views.ejecutar_fastqc, name='ejecutar_fastqc'),
    path('crear_historia/', views.crear_historia, name="crear_historia"),
    path("subir_archivo/", views.subir_archivo, name="subir_archivo"),
]