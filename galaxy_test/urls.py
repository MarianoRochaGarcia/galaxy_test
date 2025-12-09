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
    path('', views.index, name='index'),
    path("listar_historias/", views.listar_historias, name="listar_historias"),
    path('crear_historia/', views.crear_historia, name="crear_historia"),
    path("subir_archivo/", views.subir_archivo, name="subir_archivo"),
    path('ejecutar_workflow/', views.ejecutar_workflow, name='ejecutar_workflow'),
    path('show_dataset/<str:id>/', views.show_dataset, name='show_dataset'),
    path('get_jobs/<str:id>', views.get_jobs, name="get_jobs"),
    path('get_jobs_history/<str:id>', views.get_jobs_history, name="get_jobs_history"),
    
    
    # URLS Para desarollo
    path("get_inputs_job/<path:id>/", views.get_inputs_job, name="get_inputs_job"),
    path("get_outputs_job/<path:id>/", views.get_outputs_job, name="get_outputs_job"),
]