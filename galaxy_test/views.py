import json
import os
import tempfile
import re
import time
from django.conf import settings
from django.http import JsonResponse
from bioblend.galaxy import GalaxyInstance
from django.shortcuts import render
from decouple import config
import requests
from django.shortcuts import redirect
from bs4 import BeautifulSoup

GALAXY_URL = settings.GALAXY_URL
GALAXY_API_KEY = settings.GALAXY_API_KEY

headers = {
    "x-api-key": GALAXY_API_KEY
}

def index(request):
    
    return render(request, 'index.html', {})

def obtener_historias():
    
    #Crear conexion con galaxy
    gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
    
    # Filtrar los parametros que se requieren
    historias = gi.histories.get_histories(keys=['id', 'name', 'count', 'update_time'])
    
    return historias

def listar_historias(request):
    
    # Obtener historias con metodo auxiliar
    historias = obtener_historias()
    
    # Conertimos a Json para facilitar su manipulacion
    return JsonResponse(historias, safe=False)


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
    
    if request.method == "POST":
        archivo = request.FILES["archivo"]
        history_id = request.POST["history_id"]
        
        # Crear la ruta temporal 
        temp_dir = tempfile.gettempdir()
        
        # Une la ruta correctamente
        ruta_temp = os.path.join(temp_dir, archivo.name)
        
        # Guardar el archivo temporalmente en el sistema
        with open(ruta_temp, "wb+") as destino:
            for chunk in archivo.chunks():
                destino.write(chunk)
                
        # Crear la instancia de Galaxy
        gi = GalaxyInstance(settings.GALAXY_URL, settings.GALAXY_API_KEY)

        # Subir el archivo a Galaxy
        dataset = gi.tools.upload_file(
            path=ruta_temp,
            history_id=history_id,
            file_name=archivo.name
        )
        
        context = {
            'dataset': dataset
        }

        # Eliminar el archivo temporal despues de subirlo
        os.remove(ruta_temp)
        
        return redirect('subir_archivo')
    
    historias = obtener_historias()
    context = {
        'historias': historias
    }
    
    return render(request, "subir_archivo.html", context)


def esperar_finalizacion(gi, job_id, intervalo=10):
    while True:
        job = gi.jobs.show_job(job_id)
        estado = job.get("state")
        if estado in ["ok", "error"]:
            break
        time.sleep(intervalo)

def ejecutar_fastqc(history_id, datasetID):
        
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)

    fastqc_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
        tool_inputs={
            "input_file": {"src": "hda", "id": datasetID}
        }
    )
    fastqc_job_id = fastqc_job["jobs"][0]["id"]
    esperar_finalizacion(gi, fastqc_job_id)

    job_info = gi.jobs.show_job(fastqc_job_id)

    outputs_dict  = job_info.get("outputs", [])
    fastqc_outputs = list(outputs_dict.values())

    return fastqc_job_id, fastqc_outputs

def ejecutar_trimmomatic(history_id, datasetID):    

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    trimmomatic_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs={
            "input_file": {"src": "hda", "id": datasetID}
        }
    )

    trimmomatic_job_id = trimmomatic_job["jobs"][0]["id"]
    esperar_finalizacion(gi, trimmomatic_job_id)

    job_info = gi.jobs.show_job(trimmomatic_job_id)

    # Extraer los datasets de salida directamente del job
    outputs_dict  = job_info.get("outputs", [])
    output_datasets = list(outputs_dict.values())

    if not output_datasets:
        raise Exception("El trabajo terminó, pero no se encontraron datasets de salida en Galaxy.")

    trimmomatic_output_id = output_datasets[0]["id"]

    return trimmomatic_job_id, trimmomatic_output_id, output_datasets

def ejecutar_bowtie(history_id, trimmomatic_output):
    
    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    bowtie_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/bowtie2/bowtie2/2.5.1",
        tool_inputs={
            "fastq_input": {"src": "hda", "id": trimmomatic_output}
        }
    )
    bowtie_job_id = bowtie_job["jobs"][0]["id"]
    esperar_finalizacion(gi, bowtie_job_id)

    # Obtener la salida del alineamiento de Bowtie2
    bowtie_output = bowtie_job["outputs"][0]["id"]

    return bowtie_job_id, bowtie_output

# Metodo para ejecutar Fastqc, Trimmomatic y Bowtie
def ejecutar_workflow(request):

    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)

    histories = gi.histories.get_histories()

    if request.method == 'POST':
        nameHistory = request.POST.get('nombre_historia')
        if not nameHistory:
            return render(request, "error.html", {"mensaje": "No se seleccionó ninguna historia."})

        # Buscar historia seleccionada
        history_id = None
        for history in histories:
            if history["name"] == nameHistory:
                history_id = history["id"]
                break

        if not history_id:
            return render(request, "error.html", {"mensaje": "Historia no encontrada."})

        # Obtener datasets dentro de la historia
        datasets = gi.histories.show_history(history_id, contents=True)
        IdDataset = request.POST.get('id_dataset')

        if not IdDataset:
            # Mostrar datasets disponibles si no se seleccionó ninguno
            return render(request, "datasetsHistoria.html", {
                "datasets": datasets,
                "history_id": history_id,
                "nombre_historia": nameHistory
            })

        # Buscar dataset seleccionado
        datasetID = None
        for dataset in datasets:
            if dataset['id'] == IdDataset:
                datasetID = IdDataset

        if not datasetID:
            return render(request, "error.html", {"mensaje": "Dataset no encontrado."})
        
        results = {}
        
        fastqc_id, fastqc_outputs = ejecutar_fastqc(history_id, datasetID)
        results["fastqc"] = {
            "fastqc_id" : fastqc_id,
            "fastqc_outputs" : fastqc_outputs
        }

        trimmomatic_id, trimmomatic_output_id, trimmomatic_output = ejecutar_trimmomatic(history_id, datasetID)
        results["trimmomatic"] = {
            "trimmomatic_id": trimmomatic_id,
            "trimmomatic_output_id": trimmomatic_output_id,
            "trimmomatic_output": trimmomatic_output
        }

        bowtie_id, bowtie_outputs = ejecutar_bowtie(history_id, trimmomatic_output_id)
        results["bowtie"] = {
            "bowtie_id": bowtie_id,
            "bowtie_outputs":bowtie_outputs

        }

        return render(request, "resultado_fastqc.html",{
            "history_id": history_id, 
            "job_results" : results
        })

    
    return render(request, "ejecutar_herramienta/ejecutar_workflow.html", {"histories": histories})

def show_dataset(request, id):
    
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    dataset_info = gi.datasets.show_dataset(id)
    
    return JsonResponse(dataset_info)
    
def get_jobs(request, id):
    
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    jobs = gi.jobs.get_metrics(id)
    
    return JsonResponse(jobs, safe=False)
