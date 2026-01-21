import json
import os
import tempfile
import re
import time
import pandas as pd
from django.conf import settings
from django.http import HttpResponse, JsonResponse
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

def ejecutar_fastqc(history_id, datsets):

    gi = GalaxyInstance(url=GALAXY_URL, key= GALAXY_API_KEY)
    
    results = {}

    for dataset in datsets:
        tool_inputs = {
            "input_file": {"src": "hda", "id": dataset}
        }

        job = gi.tools.run_tool(
            history_id=history_id,
            tool_id="toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72",
            tool_inputs=tool_inputs,
        )

        job_id = job["jobs"][0]["id"]
        esperar_finalizacion(gi, job_id)
        info = gi.jobs.show_job(job_id)

        outputs = info.get("outputs", {})
        output_datasets = list(outputs.values())

        results[dataset] = {"job_id": job_id, "output_datasets": output_datasets}

    return results

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

def ejecutar_shovill(history_id, paired_R1, paired_R2, type_assembler):

    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    tool_inputs = {
        "library|lib_type": "paired",
        "library|R1": {"src": "hda", "id": paired_R1,},
        "library|R2": {"src": "hda", "id": paired_R2,},
        "assembler": type_assembler
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

def ejecutar_quast(history_id, contigs):
    
    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)

    results = {}
    datasets_calidad = {}
    winner = None

    for contigId in contigs:
        tool_inputs = {
            "mode|mode": "individual",
            "mode|in|custom": "false",
            "mode|in|inputs": {"src": "hda","id": contigId},
            "output_files": ["tabular"]
        }

        job = gi.tools.run_tool(
            history_id=history_id,
            tool_id="toolshed.g2.bx.psu.edu/repos/iuc/quast/quast/5.3.0+galaxy1",
            tool_inputs=tool_inputs,
            )

        job_id = job["jobs"][0]["id"]
        esperar_finalizacion(gi, job_id)

        info = gi.jobs.show_job(job_id)

        outputs = info.get("outputs", {})
        output_datasets = list(outputs.values())

        id_tsv = outputs['report_tabular']['id']
        ruta = '/tmp/report.tsv'

        gi.datasets.download_dataset(id_tsv, file_path=ruta, use_default_filename=False)

        data_tsv = pd.read_csv(ruta, sep="\t", index_col=0)

        n50 = data_tsv.loc["N50"].values[0]
        l50 = data_tsv.loc["L50"].values[0]

        datasets_calidad[contigId] = {'N50':n50, 'L50': l50}

        os.remove(ruta)

        results[contigId] = {"job_id": job_id, "output_datasets": output_datasets}

        if len(datasets_calidad) == 2:

            if datasets_calidad[contigs[0]]['N50'] > datasets_calidad[contigs[1]]['N50'] and datasets_calidad[contigs[0]]['L50'] < datasets_calidad[contigs[1]]['L50'] :
                winner = contigs[0]

            elif datasets_calidad[contigs[0]]['N50'] > datasets_calidad[contigs[1]]['N50']:
                winner = contigs[0]

            else:
                winner = contigs[1]

    return results, winner

def ejecutar_augustus(history_id, shovill):
    gi = GalaxyInstance(url = GALAXY_URL, key = GALAXY_API_KEY)

    tool_inputs = {
        "model|augustus_mode" : "history",
        "model|custom_model" : {"src": "hda", "id": shovill}
    }

    job = gi.tools.run_tool(
    history_id=history_id,
    tool_id="toolshed.g2.bx.psu.edu/repos/bgruening/augustus/augustus/3.5.0+galaxy0",
    tool_inputs=tool_inputs,
    )

    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.datasets.show_dataset(job_id)
    outputs = info.get("outputs", {}) 

    return job_id, outputs

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
            fasqc_results_inicial = ejecutar_fastqc(history_id, [datasetID, datasetID2])
            results["fastqc_inicial"] = {
                "fastqc_id1" : fasqc_results_inicial[datasetID]["job_id"],
                "fastqc_outputs1" : fasqc_results_inicial[datasetID]["output_datasets"],
                "fastqc_id2" : fasqc_results_inicial[datasetID2]["job_id"],
                "fastqc_outputs2" : fasqc_results_inicial[datasetID2]["output_datasets"]
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
            fasqc_results_final = ejecutar_fastqc(history_id, [paired_R1, paired_R2])
            results["fastqc_final"] = {
                "fastqc_id1" : fasqc_results_final[paired_R1]["job_id"],
                "fastqc_outputs1" : fasqc_results_final[paired_R1]["output_datasets"],
                "fastqc_id2" : fasqc_results_final[paired_R2]["job_id"],
                "fastqc_outputs2" : fasqc_results_final[paired_R2]["output_datasets"]
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar FastQC final: {str(e)}"})

        try:
            spades_id, spades_outputs, spades_contigs = ejecutar_shovill(history_id, paired_R1, paired_R2, "spades")
            results["spades"] = {
                "spades_id": spades_id,
                "spades_outputs": spades_outputs
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar SPAdes: {str(e)}"})

        try:
            velvet_id, velvet_outputs, velvet_contigs = ejecutar_shovill(history_id, paired_R1, paired_R2, "velvet")
            results["velvet"] = {
                "velvet_id": velvet_id,
                "velvet_outputs": velvet_outputs
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar velvet: {str(e)}"})

        try: 
            quast_results, winner = ejecutar_quast(history_id, [spades_contigs, velvet_contigs])

            results["quast"] = {
                "reporteSpades": {"spades_contigs": spades_contigs,
                "job_id": quast_results[spades_contigs]["job_id"],
                "output_datasets": quast_results[spades_contigs]["output_datasets"]
                },
                
                "reporteVelvet": {"velvet_contigs": velvet_contigs,
                "job_id": quast_results[velvet_contigs]["job_id"],
                "output_datasets": quast_results[velvet_contigs]["output_datasets"]
                } 
            }
        except Exception as e:
            return render(request, "error.html", {"mensaje": f"Error al ejecutar Quast: {str(e)}"})
        
        try: 
            augustus_id, augustus_outputs = ejecutar_augustus(history_id, winner)
            results["augustus"]= {
                "augustus_id": augustus_id,
                "augustus_outputs": augustus_outputs
            }

        except Exception as e: 
            return render(request, "error.html", {"mensaje": f"Error al ejecutar Augustus: {str(e)}"})

        return render(request, "resultado_fastqc.html",{
            "history_id": history_id, 
            "job_results" : results
        })

    return render(request, "ejecutar_herramienta/ejecutar_workflow.html", {"histories": histories})

"""
def probar_trimmomatic(request):
    gi = GalaxyInstance(url=GALAXY_URL, key=GALAXY_API_KEY)
    histories = gi.histories.get_histories()

    if request.method == "POST":
        history_id = request.POST.get("history_id")
        r1 = request.POST.get("r1")
        r2 = request.POST.get("r2")

        trimmomatic_id, outputs, unpaired_R1, unpaired_R2 = ejecutar_trimmomatic(history_id, r1, r2)

        return render(request, "resultado_trimmomatic.html", {
            "history_id": history_id,
            "trimmomatic_id": trimmomatic_id,
            "outputs": outputs,
            "unpaired_R1": unpaired_R1,
            "unpaired_R2": unpaired_R2,
        })

    # Render inicial: mostrar historias
    return render(request, "probar_trimmomatic.html", {
        "histories": histories
    })
"""
def ejecutar_trimmomatic_single(request,history_id):
    gi = GalaxyInstance(url=GALAXY_URL, key=GALAXY_API_KEY)
    
    history_info = gi.histories.show_history(history_id, keys=["name"])
    nameHistory = history_info["name"]
    idDataset = request.POST.get('id_dataset')
    idDataset2 = request.POST.get('id_dataset2')
    
    datasets_raw = gi.histories.show_history(history_id, contents=True)
    datasets = [
        d for d in datasets_raw
        if (not d.get("deleted", False)) and d.get("visible", True)
    ]
    
    datasets_fastq = [
        d for d in datasets 
        if d["name"].lower().endswith((".fastq", ".fq", ".fastq.gz"))
    ]


    if not (idDataset and idDataset2):
        # Mostrar datasets disponibles si no se seleccionó ninguno
        return render(request, "ejecutar_herramienta/ejecutar_trimmomatic_single.html", {
            "datasets": datasets,
            "datasets_fastq": datasets_fastq,
            "history_id": history_id,
            "nombre_historia": nameHistory
        })

    # Buscar dataset seleccionado
    datasetID = None
    datasetID2 =None

    for dataset in datasets:
        if dataset['id'] == idDataset:
            datasetID = idDataset
        elif dataset['id'] == idDataset2:
            datasetID2 = idDataset2

    if not (datasetID and datasetID2):
        return render(request, "error.html", {"mensaje": "Dataset no encontrado."})
    
    tool_inputs = {
    "readtype|single_or_paired": "pair_of_files",
    "readtype|fastq_r1_in": {"src": "hda", "id": idDataset},
    "readtype|fastq_r2_in": {"src": "hda", "id": idDataset2},
    "illuminaclip|do_illuminaclip": "no",
    # "operations_0|operation|name": "SLIDINGWINDOW",
    # "operations_0|operation|window_size": "4",
    # "operations_0|operation|required_quality": "20",
    }
    job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2",
        tool_inputs=tool_inputs,
    )
    job_id = job["jobs"][0]["id"]
    esperar_finalizacion(gi, job_id)
    info = gi.jobs.show_job(job_id)
    print("params:", info.get("params"))
    print("outputs:", info.get("outputs"))

    response = {
        "info": info
    }
    return JsonResponse(response, safe=False)

def ejecutar_bowtie2_single(request, history_id):
    
    gi = GalaxyInstance(url= GALAXY_URL, key=GALAXY_API_KEY)  

    history_info = gi.histories.show_history(history_id, keys=["name"])
    nameHistory = history_info["name"]
    idDataset = request.POST.get("id_dataset")
    idDataset2 = request.POST.get("id_dataset2")
    
    datasets_raw = gi.histories.show_history(history_id, contents=True)
    datasets = [
        d for d in datasets_raw
        if (not d.get("deleted", False)) and d.get("visible", True)
    ]
    
    datasets_fastq = [
        d for d in datasets 
        if d["name"].lower().endswith((".fastq", ".fq", ".fastq.gz"))
    ]


    if not (idDataset and idDataset2):
        # Mostrar datasets disponibles si no se seleccionó ninguno
        return render(request, "ejecutar_herramienta/ejecutar_trimmomatic_single.html", {
            "datasets": datasets,
            "datasets_fastq": datasets_fastq,
            "history_id": history_id,
            "nombre_historia": nameHistory
        })

    # Buscar dataset seleccionado
    datasetID = None
    datasetID2 =None

    for dataset in datasets:
        if dataset['id'] == idDataset:
            datasetID = idDataset
        elif dataset['id'] == idDataset2:
            datasetID2 = idDataset2

    if not (datasetID and datasetID2):
        return render(request, "error.html", {"mensaje": "Dataset no encontrado."})
    
    tool_inputs= {
        
    }

    bowtie_job = gi.tools.run_tool(
        history_id=history_id,
        tool_id="toolshed.g2.bx.psu.edu/repos/devteam/bowtie2/bowtie2/2.5.3+galaxy0",
        tool_inputs={
            "library": {
                "type": "paired",
                "input_1": {"src": "hda", "id": datasetID_R1},
                "input_2": {"src": "hda", "id": datasetID_R2},
                "unaligned_file": True,
                "aligned_file": True,
                "paired_options": {
                "paired_options_selector": "no"}
            },
            "reference_genome": {
                "source": "history",
                "own_file": {"src": "hda", "id": genomaId}
            }
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
