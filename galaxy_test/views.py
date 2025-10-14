import json
import os
import tempfile
import re
from bs4 import BeautifulSoup
from django.conf import settings
from django.http import JsonResponse
from bioblend.galaxy import GalaxyInstance
from django.shortcuts import render
from decouple import config
import requests

GALAXY_URL = settings.GALAXY_URL
GALAXY_API_KEY = settings.GALAXY_API_KEY

headers = {
    "x-api-key": GALAXY_API_KEY
}

def buscar_reportes_fastqc(request):
    """Buscar todos los reportes FastQC disponibles en todas las historias"""
    try:
        gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
        historias = gi.histories.get_histories()
        
        reportes_encontrados = []
        
        for historia in historias:
            historia_id = historia["id"]
            historia_nombre = historia.get("name", "Sin nombre")
            
            # Obtener datasets de esta historia
            datasets = gi.histories.show_history(historia_id, contents=True)
            
            for dataset in datasets:
                nombre = dataset.get("name", "").lower()
                extension = dataset.get("extension", "").lower()
                
                # Buscar archivos FastQC HTML
                if extension == "html" and ("fastqc" in nombre or "webpage" in nombre):
                    reportes_encontrados.append({
                        "dataset_id": dataset["id"],
                        "nombre": dataset.get("name"),
                        "historia_nombre": historia_nombre,
                        "historia_id": historia_id,
                        "estado": dataset.get("state", "unknown"),
                        "extension": extension
                    })
        
        return JsonResponse({
            "total_reportes": len(reportes_encontrados),
            "reportes": reportes_encontrados
        }, json_dumps_params={'indent': 2})
        
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def analizar_fastqc(request, dataset_id=None):
    """Analizar un reporte FastQC específico y extraer métricas clave"""
    
    # Si no se especifica dataset_id, buscar el más reciente
    if not dataset_id:
        try:
            gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
            historias = gi.histories.get_histories()
            
            # Buscar el primer reporte FastQC disponible
            for historia in historias:
                datasets = gi.histories.show_history(historia["id"], contents=True)
                
                for dataset in datasets:
                    nombre = dataset.get("name", "").lower()
                    extension = dataset.get("extension", "").lower()
                    
                    if extension == "html" and ("fastqc" in nombre or "webpage" in nombre):
                        dataset_id = dataset["id"]
                        break
                
                if dataset_id:
                    break
            
            if not dataset_id:
                return JsonResponse({"error": "No se encontraron reportes FastQC"}, status=404)
                
        except Exception as e:
            return JsonResponse({"error": f"Error buscando reportes: {str(e)}"}, status=500)
    
    try:
        gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
        
        temp_dir = tempfile.gettempdir()
        ruta_archivo = os.path.join(temp_dir, f"fastqc_report_{dataset_id}.html")
        
        print(f"Descargando FastQC a: {ruta_archivo}")
        gi.datasets.download_dataset(dataset_id, file_path=ruta_archivo, use_default_filename=False)
        
        # Leer el archivo con manejo de codificación
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                contenido_html = f.read()
        except UnicodeDecodeError:
            with open(ruta_archivo, "r", encoding="latin-1") as f:
                contenido_html = f.read()
        
        # Limpiar archivo temporal
        try:
            os.remove(ruta_archivo)
        except:
            pass
        
        # Parsear el HTML para extraer métricas
        soup = BeautifulSoup(contenido_html, 'html.parser')
        
        # Extraer información clave del FastQC
        metricas = {
            "nombre_archivo": None,
            "tipo_archivo" : None,
            "encoding": None,
            "total_secuencias": None,
            "longitud_secuencias": None,
            "contenido_gc": None,
            "calidad_promedio": None,
        }

        try:
            tablas = soup.find_all('table')
            for tabla in tablas:
                filas = tabla.find_all('tr')
                for fila in filas:
                    celdas = fila.find_all('td')
                    if len(celdas) >= 2:
                        campo = celdas[0].text.strip().lower()
                        valor = celdas[1].text.strip()
                        if 'filename' in campo:
                            metricas["nombre_archivo"] = valor
                        if 'file type' in campo:
                            metricas["tipo_archivo"] = valor
                        if 'encoding' in campo:
                            metricas["encoding"] = valor
                        if 'total sequences' in campo:
                            metricas["total_secuencias"] = valor
                        elif 'sequence length' in campo:
                            metricas["longitud_secuencias"] = valor
                        elif '%gc' in campo:
                            metricas["contenido_gc"] = valor
        except:
            pass
        
        return JsonResponse({
            "dataset_id": dataset_id,
            "metricas": metricas,
            "procesamiento": "exitoso"
        }, json_dumps_params={'indent': 2})
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error procesando FastQC: {str(e)}",
            "dataset_id": dataset_id
        }, status=500)
        
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

def ver_historia_bioblend(request, history_id):
    gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
    datasets = gi.histories.show_history(history_id, contents=True)
    
    fastqc_datasets = [
        ds for ds in datasets
        if 'FASTQC' in ds.get('name', '')
    ]
    
    return JsonResponse(fastqc_datasets, safe=False)

def analizar_fastqc_tabla(request, dataset_id=None):

    """Analizar un reporte FastQC específico y extraer métricas clave"""
    
    # Si no se especifica dataset_id, buscar el más reciente
    if not dataset_id:
        try:
            gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
            historias = gi.histories.get_histories()
            
            # Buscar el primer reporte FastQC disponible
            for historia in historias:
                datasets = gi.histories.show_history(historia["id"], contents=True)
                
                for dataset in datasets:
                    nombre = dataset.get("name", "").lower()
                    extension = dataset.get("extension", "").lower()
                    
                    if extension == "html" and ("fastqc" in nombre or "webpage" in nombre):
                        dataset_id = dataset["id"]
                        break
                
                if dataset_id:
                    break
            
            if not dataset_id:
                return JsonResponse({"error": "No se encontraron reportes FastQC"}, status=404)
                
        except Exception as e:
            return JsonResponse({"error": f"Error buscando reportes: {str(e)}"}, status=500)
    
    try:
        gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)
        
        temp_dir = tempfile.gettempdir()
        ruta_archivo = os.path.join(temp_dir, f"fastqc_report_{dataset_id}.html")
        
        print(f"Descargando FastQC a: {ruta_archivo}")
        gi.datasets.download_dataset(dataset_id, file_path=ruta_archivo, use_default_filename=False)
        
        # Leer el archivo con manejo de codificación
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                contenido_html = f.read()
        except UnicodeDecodeError:
            with open(ruta_archivo, "r", encoding="latin-1") as f:
                contenido_html = f.read()
        
        # Limpiar archivo temporal
        try:
            os.remove(ruta_archivo)
        except:
            pass
        
        # Parsear el HTML para extraer métricas
        soup = BeautifulSoup(contenido_html, 'html.parser')
        
        # Extraer información clave del FastQC
        metricas = {
            "dataset_id" :dataset_id,
            "nombre_archivo": None,
            "tipo_archivo" : None,
            "encoding": None,
            "total_secuencias": None,
            "longitud_secuencias": None,
            "contenido_gc": None,
            "calidad_promedio": None,
        }

        try:
            tablas = soup.find_all('table')
            for tabla in tablas:
                filas = tabla.find_all('tr')
                for fila in filas:
                    celdas = fila.find_all('td')
                    if len(celdas) >= 2:
                        campo = celdas[0].text.strip().lower()
                        valor = celdas[1].text.strip()
                        if 'filename' in campo:
                            metricas["nombre_archivo"] = valor
                        if 'file type' in campo:
                            metricas["tipo_archivo"] = valor
                        if 'encoding' in campo:
                            metricas["encoding"] = valor
                        if 'total sequences' in campo:
                            metricas["total_secuencias"] = valor
                        elif 'sequence length' in campo:
                            metricas["longitud_secuencias"] = valor
                        elif '%gc' in campo:
                            metricas["contenido_gc"] = valor
        except:
            pass
        
        context = {
            'metricas': metricas
        }
        
        return render(request, 'analizar_fastqc_tabla.html', context)
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error procesando FastQC: {str(e)}",
            "dataset_id": dataset_id
        }, status=500)

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
    return render(request, "subir_fastqc.html", {"histories": histories})

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
        
        return render(request, "subida_exitosa.html", context)
    
    return render(request, "subir_archivo.html")

def fastqc_trimmomatic(request):
    if request.method == 'POST':
        archivo = request.FILES['archivo']

        # Conectarse a Galaxy
        gi = GalaxyInstance(settings.GALAXY_URL, key=settings.GALAXY_API_KEY)


        # Crear historia
        historia = gi.histories.create_history(name="Pipeline FastQC + Trimmomatic")
        history_id = historia['id']

        # Guardar archivo temporalmente para subirlo
        ruta_local = os.path.join(settings.MEDIA_ROOT, archivo.name)
        with open(ruta_local, "wb+") as destino:
            for chunk in archivo.chunks():
                destino.write(chunk)

        dataset = gi.tools.upload_file(
            path=ruta_local,
            history_id=history_id,
            file_name=archivo.name
        )
        
        dataset_id = dataset['outputs'][0]['id']

        # Ejecutar FastQC
        fastqc_tool_id = 'toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.72'
        fastqc_job = gi.tools.run_tool(
            history_id=history_id,
            tool_id=fastqc_tool_id,
            tool_inputs={'input_file': {'src': 'hda', 'id': dataset_id}}
        )

        # Ejecutar Trimmomatic
        trimmomatic_tool_id = 'toolshed.g2.bx.psu.edu/repos/devteam/trimmomatic/trimmomatic/0.39'
        trimmomatic_inputs = {
            'input_file': {'src': 'hda', 'id': dataset_id},
            'ILLUMINACLIP': {'value': 'adapters.fa:2:30:10'},
            'SLIDINGWINDOW': {'value': '4:20'},
            'MINLEN': {'value': 36}
        }
        trimmomatic_job = gi.tools.run_tool(
            history_id=history_id,
            tool_id=trimmomatic_tool_id,
            tool_inputs=trimmomatic_inputs
        )

        #  Limpiar archivo temporal
        os.remove(ruta_local)

        # Mostrar resultados
        context = {
            "mensaje": "Pipeline FastQC + Trimmomatic ejecutado correctamente.",
            "historia_id": history_id,
            "fastqc_job": fastqc_job,
            "trimmomatic_job": trimmomatic_job
        }

        return render(request, "resultado_fastqc_trimmomatic.html", context)

    return render(request, "subir_fastqc_trimmomatic.html")
        

    
