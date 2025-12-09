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
    
    return render(request, 'layout/index.html', {})

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

    fastqc_job1 = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
        tool_inputs={
                "input_file": {"src": "hda", "id": datasetID_R1}
        }
    )

    fastqc_job2 = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
        tool_inputs={
                "input_file": {"src": "hda", "id": datasetID_R2}
        }
    )
    fastqc_job_id1 = fastqc_job1["jobs"][0]["id"]
    fastqc_job_id2 = fastqc_job2["jobs"][0]["id"]

    esperar_finalizacion(gi, fastqc_job_id1)
    esperar_finalizacion(gi, fastqc_job_id2)

    job_info1 = gi.jobs.show_job(fastqc_job_id1)
    job_info2 = gi.jobs.show_job(fastqc_job_id2)

    outputs_dict1  = job_info1.get("outputs", [])
    fastqc_outputs1 = list(outputs_dict1.values())

    outputs_dict2  = job_info2.get("outputs", [])
    fastqc_outputs2 = list(outputs_dict2.values())

    return fastqc_job_id1, fastqc_job_id2, fastqc_outputs1, fastqc_outputs2

def ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2):    

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    tool_inputs = {
        "readtype|single_or_paired": "pair_of_files",
        "readtype|fastq_r1_in": {"src": "hda", "id": unaligned_R1},
        "readtype|fastq_r2_in": {"src": "hda", "id": unaligned_R2},
        "illuminaclip|do_illuminaclip": "no",
        }
    
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs=tool_inputs,
    )

    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)

    outputs = info.get("outputs", {})
    output_datasets = list(outputs.values())

    paired_R1 = outputs.get("fastq_out_r1_paired", {}).get("id")
    paired_R2 = outputs.get("fastq_out_r2_paired", {}).get("id")

    return job_id, output_datasets, paired_R1, paired_R2

def ejecutar_bowtie(history_id, datasetID_R1, datasetID_R2, genomaId):

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    tool_inputs = {
        "library|type": "paired",
        "library|input_1": {"src": "hda", "id": datasetID_R1},
        "library|input_2": {"src": "hda", "id": datasetID_R2},
        "library|unaligned_file": "true",     
        "library|aligned_file": "true",       

        "library|paired_options|paired_options_selector": "no",

        "reference_genome|source": "history",
        "reference_genome|own_file": {"src": "hda", "id": genomaId},
    }

    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/bowtie2/bowtie2/2.5.3+galaxy0",
        tool_inputs=tool_inputs,
        )


    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)

    outputs = info.get("outputs", {})
    output_datasets = list(outputs.values())


    unaligned_R1 = outputs.get("output_unaligned_reads_r", {}).get("id")
    unaligned_R2 = outputs.get("output_unaligned_reads_l", {}).get("id")

    return job_id, output_datasets, unaligned_R1, unaligned_R2

def ejecutar_spades(history_id, paired_R1, paired_R2):

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    tool_inputs = {
        "library|lib_type": "paired",
        "library|R1": {"src": "hda", "id": paired_R1,},
        "library|R2": {"src": "hda", "id": paired_R2,}
    }

    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/iuc/shovill/shovill/1.1.0+galaxy2",
        tool_inputs=tool_inputs,
        )

    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)

    outputs = info.get("outputs", {})
    output_datasets = list(outputs.values())

    shovill = outputs.get("contigs", {}).get("id")

    return job_id, output_datasets, shovill

def ejecutar_velvet(history_id, paired_R1, paired_R2):
    
    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)

    tool_inputs = {
        "files_0|filetype": "fastq",
        "files_0|paired_type|paired_type_selector": "paired",

        "files_0|paired_type|input1": {"src": "hda", "id": paired_R1},
        "files_0|paired_type|input2": {"src": "hda", "id": paired_R2},

        "start_kmer": 31,
        "end_kmer": 191,
        "kmer_step": 2,
    }

    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/simon-gladman/velvetoptimiser/velvetoptimiser/2.2.6",
        tool_inputs=tool_inputs,
        )
    
    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)

    outputs = info.get("outputs", {})
    output_datasets = list(outputs.values())

    shovill = outputs.get("contigs", {}).get("id")

    return job_id, output_datasets, shovill

# Metodo el proceso completo
def ejecutar_workflow(request):

    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)

    histories = gi.histories.get_histories()

    #Entrada del nombre de la historia
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
        idDataset = request.POST.get('id_dataset')
        idDataset2 = request.POST.get('id_dataset2')
        idGenoma = request.POST.get('id_genoma')
        
        datasets_raw = gi.histories.show_history(history_id, contents=True)
        datasets = [
            d for d in datasets_raw
            if (not d.get("deleted", False)) and d.get("visible", True)
        ]
        datasets_fastq = [
            d for d in datasets 
            if d["name"].lower().endswith((".fastq", ".fq", ".fastq.gz"))
        ]
        genomas = [
            d for d in datasets 
            if d["name"].lower().endswith(".fasta")
        ]

        if not (idDataset and idDataset2 and idGenoma):
            # Mostrar datasets disponibles si no se seleccionó ninguno
            return render(request, "datasetsHistoria.html", {
                "datasets": datasets,
                "datasets_fastq": datasets_fastq,
                "history_id": history_id,
                "genomas": genomas,
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

        #Ejecución de los procesos 
        try:
            fastqc_inicial_id1, fastqc_inicial_id2, fastqc_inicial_outputs1, fastqc_inicial_outputs2 = ejecutar_fastqc(history_id, datasetID, datasetID2)
            results["fastqc"] = {
                "fastqc_id1" : fastqc_inicial_id1,
                "fastqc_outputs1" : fastqc_inicial_outputs1,
                "fastqc_id2" : fastqc_inicial_id2,
                "fastqc_outputs2" : fastqc_inicial_outputs2
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar FastQC inicial: {str(e)}"})

        try:
            bowtie_id, bowtie_outputs, unaligned_R1, unaligned_R2 = ejecutar_bowtie(history_id, datasetID, datasetID2, genomaId)
            results["bowtie"] = {
                "bowtie_id": bowtie_id,
                "bowtie_outputs":bowtie_outputs,
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar Bowtie2: {str(e)}"})
        
        try:
            trimmomatic_id, trimmomatic_outputs, paired_R1, paired_R2 = ejecutar_trimmomatic(history_id, unaligned_R1, unaligned_R2)
            results["trimmomatic"] = {
                "trimmomatic_id": trimmomatic_id,
                "trimmomatic_output": trimmomatic_outputs
            }
        except Exception as e: 
            return render(request, "error.html", {"mensaje": f"Error al ejecutar Trimmomatic: {str(e)}"})

        try:
            fastqc_final_id1, fastqc_final_id2, fastqc_final_outputs1, fastqc_final_outputs2 = ejecutar_fastqc(history_id, paired_R1, paired_R2)
            results["fastqc"] = {
                "fastqc_id1" : fastqc_final_id1,
                "fastqc_outputs1" : fastqc_final_outputs1,
                "fastqc_id2" : fastqc_final_id2,
                "fastqc_outputs2" : fastqc_final_outputs2
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar FastQC final: {str(e)}"})

        try:
            spades_id, sapades_outputs, shovill_contigs = ejecutar_spades(history_id, paired_R1, paired_R2)
            results["spades"] = {
                "spades_id": spades_id,
                "spades_outputs": sapades_outputs
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar SPAdes: {str(e)}"})

        try:
            velvet_id, velvet_outputs, velvet_contigs = ejecutar_velvet(history_id, paired_R1, paired_R2)
            results["velvet"] = {
                "velvet_id": velvet_id,
                "velvet_outputs": velvet_outputs
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar Velvet: {str(e)}"})

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
    jobs = gi.jobs.get_outputs(id)
    
    return JsonResponse(jobs, safe=False)

def get_jobs_history(request, id):
    
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    jobs = gi.jobs.get_jobs(history_id=id)
    
    return JsonResponse(jobs, safe=False)

def get_inputs_job(request, id):
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    inputs = gi.jobs.get_inputs(job_id=id)
    return JsonResponse(inputs, safe=False)

def get_outputs_job(request, id):
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    inputs = gi.jobs.get_outputs(job_id=id)
    return JsonResponse(inputs, safe=False)

def ver_parametros_permitidos_tool(request, id_tool):
    
    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    info_tool = gi.tools.show_tool(tool_id=id_tool, io_details=True)
    return JsonResponse(info_tool)
