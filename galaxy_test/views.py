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

def ejecutar_fastqc(history_id, datasetID_R1, datasetID_R2):
        
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)

    fastqc_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
        tool_inputs={
            "analysis_type": "paired",
            "left_input": {"src": "hda", "id": datasetID_R1},
            "right_input": {"src": "hda", "id": datasetID_R2},
        }
    )
    fastqc_job_id = fastqc_job["jobs"][0]["id"]
    esperar_finalizacion(gi, fastqc_job_id)

    job_info = gi.jobs.show_job(fastqc_job_id)

    outputs_dict  = job_info.get("outputs", [])
    fastqc_outputs = list(outputs_dict.values())

    return fastqc_job_id, fastqc_outputs

def ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2):    

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    trimmomatic_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs={
            "paired_or_single": "paired",
            "left_input1": {"src": "hda", "id": unaligned_R1},
            "right_input1": {"src": "hda", "id": unaligned_R2},
        }
    )

    trimmomatic_job_id = trimmomatic_job["jobs"][0]["id"]
    esperar_finalizacion(gi, trimmomatic_job_id)

    job_info = gi.jobs.show_job(trimmomatic_job_id)

    # Extraer los datasets de salida directamente del job
    outputs  = job_info.get("outputs", {})
    output_datasets = list(outputs.values())
    outputs_dict = {k: v for k, v in outputs.items()}

    unpaired_R1 = outputs.get("output_unpaired_forward", {}).get("id")
    unpaired_R2 = outputs.get("output_unpaired_reverse", {}).get("id")

    return trimmomatic_job_id, output_datasets, unpaired_R1, unpaired_R2

def ejecutar_bowtie(history_id, datasetID_R1, datasetID_R2, genomaId):

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    bowtie_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/bowtie2/bowtie2/2.5.3+galaxy1",
        tool_inputs = {
            "paired_or_single": "paired",
            "left_input": {"src": "hda", "id": datasetID_R1},
            "right_input": {"src": "hda", "id": datasetID_R2},
            "reference_genome_source": "history",
            "reference_genome": {"src": "hda", "id": genomaId},
            "write_unaligned_reads": True,
            "unaligned_reads_filename": "unaligned_reads",
            "write_aligned_reads": True,
            "aligned_reads_filename": "aligned_reads.sam"  
        }
    )
    bowtie_job_id = bowtie_job["jobs"][0]["id"]
    esperar_finalizacion(gi, bowtie_job_id)

    job_info = gi.jobs.show_job(bowtie_job_id)
    outputs = job_info.get("outputs", {})

    outputs_dict = {k: v for k, v in outputs.items()}

    #Se filtra los dos unaligned
    unaligned_R1 = outputs_dict.get("unaligned_reads_1")
    unaligned_R2 = outputs_dict.get("unaligned_reads_2")

    return bowtie_job_id, outputs_dict, unaligned_R1, unaligned_R2

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
        idDataset = request.POST.get('id_dataset')
        idDataset2 = request.POST.get('id_dataset2')
        idGenoma = request.POST.get('id_genoma')

        if not (idDataset and idDataset2 and idGenoma):
            # Mostrar datasets disponibles si no se seleccionó ninguno
            return render(request, "datasetsHistoria.html", {
                "datasets": datasets,
                "history_id": history_id,
                "nombre_historia": nameHistory
            })

        # Buscar dataset seleccionado
        datasetID = None
        datasetID2 =None
        genomaId = None

        for dataset in datasets:
            if dataset['id'] == idDataset:
                datasetID = idDataset
            elif dataset['id'] == idDataset2:
                datasetID2 = idDataset2
            elif dataset['id'] == idGenoma:
                genomaId = idGenoma

        if not (datasetID and datasetID2 and genomaId):
            return render(request, "error.html", {"mensaje": "Dataset no encontrado."})
        
        results = {}

        fastqc_id, fastqc_outputs = ejecutar_fastqc(history_id, datasetID, datasetID2)
        results["fastqc"] = {
            "fastqc_id" : fastqc_id,
            "fastqc_outputs" : fastqc_outputs
        }

        bowtie_id, bowtie_outputs, unaligned_R1, unaligned_R2 = ejecutar_bowtie(history_id, datasetID, datasetID2, genomaId)
        results["bowtie"] = {
            "bowtie_id": bowtie_id,
            "bowtie_outputs":bowtie_outputs,
        }
        
        trimmomatic_id, trimmomatic_output, unpaired_R1, unpaired_R2 = ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2)
        results["trimmomatic"] = {
            "trimmomatic_id": trimmomatic_id,
            "trimmomatic_output": trimmomatic_output
        }

        fastqc_id, fastqc_outputs = ejecutar_fastqc(history_id, unpaired_R1, unpaired_R2)
        results["fastqc"] = {
            "fastqc_id" : fastqc_id,
            "fastqc_outputs" : fastqc_outputs
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
