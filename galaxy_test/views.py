import json
import os
import tempfile
import re
from django.conf import settings
from django.http import JsonResponse
from bioblend.galaxy import GalaxyInstance
from django.shortcuts import render
from decouple import config
import requests
from django.shortcuts import redirect

GALAXY_URL = settings.GALAXY_URL
GALAXY_API_KEY = settings.GALAXY_API_KEY

headers = {
    "x-api-key": GALAXY_API_KEY
}

def index(request):
    
    return render(request, 'index.html', {})

# def buscar_reportes_fastqc(request):
#     """Buscar todos los reportes FastQC disponibles en todas las historias"""
#     try:
#         gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
#         historias = gi.histories.get_histories()
        
#         reportes_encontrados = []
        
#         for historia in historias:
#             historia_id = historia["id"]
#             historia_nombre = historia.get("name", "Sin nombre")
            
#             # Obtener datasets de esta historia
#             datasets = gi.histories.show_history(historia_id, contents=True)
            
#             for dataset in datasets:
#                 nombre = dataset.get("name", "").lower()
#                 extension = dataset.get("extension", "").lower()
                
#                 # Buscar archivos FastQC HTML
#                 if extension == "html" and ("fastqc" in nombre or "webpage" in nombre):
#                     reportes_encontrados.append({
#                         "dataset_id": dataset["id"],
#                         "nombre": dataset.get("name"),
#                         "historia_nombre": historia_nombre,
#                         "historia_id": historia_id,
#                         "estado": dataset.get("state", "unknown"),
#                         "extension": extension
#                     })
        
#         return JsonResponse({
#             "total_reportes": len(reportes_encontrados),
#             "reportes": reportes_encontrados
#         }, json_dumps_params={'indent': 2})
        
#     except Exception as e:
#         return JsonResponse({"error": str(e)}, status=500)
        
def listar_historias(request):
    
    # Listar todas las historias
    gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
    
    # Obtener todas las historias disponibles
    historias = gi.histories.get_histories()
    
    # Filtrar informacion
    info_historias = [
            {
                "id": h["id"],
                "name": h["name"],
                "datasets": h.get("count"),
                "last_update": h.get("update_time")
            }
        for h in historias
    ]
    
    return JsonResponse(info_historias, safe=False)


def ejecutar_fastqc(request):
    response = listar_historias(request)
    histories = json.loads(response.content)

    if request.method == 'POST':
        nameHistory = request.POST.get('nombre_historia')

        for history in histories:
            if nameHistory == history["name"]:
                history_id = history["id"]

        url = f"{GALAXY_URL}/api/histories/{history_id}/contents"
        resp = requests.get(url, headers=headers)
        datasets = resp.json()
        
        nameDataset = request.POST.get('nombreDataset')

        if nameDataset:
            for dataset in datasets:
                if nameDataset == dataset["name"]:
                    datasetID = dataset["id"]

                    fastqc_resp = requests.post(
                        f"{GALAXY_URL}/api/tools",
                        headers=headers,
                        json={
                            "tool_id": "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
                            "history_id": history_id,
                            "inputs": {
                                "input_file": {"src": "hda", "id": datasetID}
                            }
                        }
                    )

                    job_info = fastqc_resp.json()
                    return render(request, "resultado_fastqc.html", {
                        "mensaje": "FastQC ejecutado correctamente.",
                        "history_id": history_id,
                        "job_info": job_info,
                    })

        return render(request, "datasetsHistoria.html", {
            "datasets": datasets,
            "history_id": history_id,
            "nombre_historia": nameHistory
        })
    return render(request, "ejecutar_herramienta/ejecutar_fastqc.html", {"histories": histories})

def crear_historia(request):
    if request.method == "POST":
        
        #Obtener parametro del POST
        nombre_historia = request.POST.get('nombre_historia')
        
        gi = GalaxyInstance(settings.GALAXY_URL, settings.GALAXY_API_KEY)
        nueva_historia = gi.histories.create_history(nombre_historia)
        context = {
            'nueva_historia': nueva_historia
        }
        
        return render(request, 'historia_creada.html', context)
        
    return render(request, 'crear_historia.html')

def subir_archivo(request):
    
    response = listar_historias(request)
    historias = json.loads(response.content)
    context = {
        'historias': historias
    }
    if request.method == "POST":
        archivo = request.FILES["archivo"]
        history_id = request.POST["history_id"]
        
        ruta_local = os.path.join(settings.MEDIA_ROOT, archivo.name)
        with open(ruta_local, "wb+") as destino:
            for chunk in archivo.chunks():
                destino.write(chunk)
            
        gi = GalaxyInstance(settings.GALAXY_URL, settings.GALAXY_API_KEY)

        dataset = gi.tools.upload_file(
            path=ruta_local,
            history_id=history_id,
            file_name=archivo.name
        )

        os.remove(ruta_local)
        
        context = {
            'dataset': dataset
        }
        
        return redirect('subir_archivo')
    
    return render(request, "subir_archivo.html", context)

def ejecutar_trimmomatic(request):
    response = listar_historias(request)
    histories = json.loads(response.content)

    if request.method == 'POST':
        nameHistory = request.POST.get('nombre_historia')

        for history in histories:
            if nameHistory == history["name"]:
                history_id = history["id"]

        url = f"{GALAXY_URL}/api/histories/{history_id}/contents"
        resp = requests.get(url, headers=headers)
        datasets = resp.json()
        
        nameDataset = request.POST.get('nombreDataset')

        if nameDataset:
            for dataset in datasets:
                if nameDataset == dataset["name"]:
                    datasetID = dataset["id"]

                    # 🔹 Ejecutar Trimmomatic en lugar de FastQC
                    trimmomatic_resp = requests.post(
                        f"{GALAXY_URL}/api/tools",
                        headers=headers,
                        json={
                            "tool_id": "toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
                            "history_id": history_id,
                            "inputs": {
                                "input_reads": {"src": "hda", "id": datasetID},
                                "phred": "phred33",
                                "leading": {"leading": "3"},
                                "trailing": {"trailing": "3"},
                                "slidingwindow": {"slidingwindow": "4:15"},
                                "minlen": {"minlen": "36"}
                            }
                        }
                    )

                    job_info = trimmomatic_resp.json()
                    return render(request, "resultado_trimmomatic.html", {
                        "mensaje": "Trimmomatic ejecutado correctamente.",
                        "history_id": history_id,
                        "job_info": job_info,
                    })

        return render(request, "dataset_trimmomatic.html", {
            "datasets": datasets,
            "history_id": history_id,
            "nombre_historia": nameHistory
        })

    return render(request, "ejecutar_herramienta/ejecutar_trimmomatic.html", {"histories": histories})
