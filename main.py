import streamlit as st
import ee
import geemap
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
import geopandas as gpd
import requests
import io
import zipfile

# Configuración de la página
st.set_page_config(
    page_title="Análisis de Islas de Calor Urbanas - Tabasco",
    page_icon="🌡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título principal
st.title("🌡 Análisis de Islas de Calor Urbanas - Tabasco")
st.markdown("---")

# Inicialización de Google Earth Engine
def initialize_gee():
    try:
        # Opción 1: Usar Service Account desde Secrets de Streamlit
        if all(key in st.secrets for key in ['GEE_SERVICE_ACCOUNT', 'GEE_PRIVATE_KEY']):
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            private_key = st.secrets["GEE_PRIVATE_KEY"].replace('\\n', '\n')
            
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            return True
            
    except Exception as e:
        st.sidebar.warning(f"Service Account no disponible: {e}")
    
    # Opción 2: Autenticación estándar
    try:
        if not ee.data._credentials:
            ee.Authenticate()
        ee.Initialize()
        return True
    except Exception as e:
        st.error(f"❌ Error conectando a Google Earth Engine: {e}")
        return False

# Función para cargar el shapefile desde GitHub
def cargar_shapefile_localidades():
    try:
        # URLs de los archivos del shapefile en tu repositorio
        base_url = "https://github.com/Peralta-Crrt/Proyecto-Islas-de-Calor_2.0/raw/main/localidades_urbanas/"
        
        # Descargar los archivos del shapefile
        shp_url = base_url + "localidades_urbanas.shp"
        shx_url = base_url + "localidades_urbanas.shx"
        dbf_url = base_url + "localidades_urbanas.dbf"
        prj_url = base_url + "localidades_urbanas.prj"
        
        # Descargar archivos
        shp_content = requests.get(shp_url).content
        shx_content = requests.get(shx_url).content
        dbf_content = requests.get(dbf_url).content
        prj_content = requests.get(prj_url).content
        
        # Guardar temporalmente y cargar con geopandas
        with open("temp_localidades.shp", "wb") as f:
            f.write(shp_content)
        with open("temp_localidades.shx", "wb") as f:
            f.write(shx_content)
        with open("temp_localidades.dbf", "wb") as f:
            f.write(dbf_content)
        with open("temp_localidades.prj", "wb") as f:
            f.write(prj_content)
        
        # Cargar el shapefile
        gdf = gpd.read_file("temp_localidades.shp")
        
        return gdf
        
    except Exception as e:
        st.error(f"Error cargando shapefile: {e}")
        return None

# Función alternativa si falla la descarga directa
def cargar_datos_localidades():
    """Cargar datos de localidades - versión simplificada si falla el shapefile"""
    # Datos de ejemplo basados en tu shapefile (puedes ajustar estas coordenadas)
    localidades = {
        "Villahermosa": {"coords": [-92.9183, 17.9895], "tipo": "Urbana"},
        "Cárdenas": {"coords": [-93.3750, 17.9869], "tipo": "Urbana"},
        "Comalcalco": {"coords": [-93.2119, 18.2631], "tipo": "Urbana"},
        "Macuspana": {"coords": [-92.5989, 17.7581], "tipo": "Urbana"},
        "Huimanguillo": {"coords": [-93.3892, 17.8333], "tipo": "Urbana"},
        "Paraíso": {"coords": [-93.2150, 18.3981], "tipo": "Urbana"},
        "Jalpa de Méndez": {"coords": [-93.0631, 18.1764], "tipo": "Urbana"},
        "Nacajuca": {"coords": [-93.0172, 18.0653], "tipo": "Urbana"},
        "Tenosique": {"coords": [-91.4269, 17.4742], "tipo": "Urbana"},
        "Emiliano Zapata": {"coords": [-91.7669, 17.7406], "tipo": "Urbana"}
    }
    return localidades

# Función para calcular temperatura LST de Landsat 8
def calcular_lst_landsat8(image):
    # Conversión a temperatura Celsius
    lst = image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)
    return lst.rename('LST')

# Análisis principal de isla de calor usando geometría del shapefile
def analizar_isla_calor(localidad_seleccionada, fecha_inicio, fecha_fin, usar_shapefile=True):
    try:
        if usar_shapefile:
            # Cargar shapefile
            gdf = cargar_shapefile_localidades()
            if gdf is None:
                st.warning("⚠️ No se pudo cargar el shapefile, usando coordenadas predeterminadas")
                return analizar_isla_calor_fallback(localidad_seleccionada, fecha_inicio, fecha_fin)
            
            # Filtrar la localidad seleccionada
            localidad_data = gdf[gdf['NOM_LOC'] == localidad_seleccionada]
            if localidad_data.empty:
                st.warning(f"⚠️ Localidad '{localidad_seleccionada}' no encontrada en shapefile")
                return analizar_isla_calor_fallback(localidad_seleccionada, fecha_inicio, fecha_fin)
            
            # Convertir a geometría de Earth Engine
            geometry_json = localidad_data.geometry.iloc[0].__geo_interface__
            area_estudio = ee.Geometry(geometry_json)
            
        else:
            # Usar coordenadas predeterminadas
            localidades = cargar_datos_localidades()
            config = localidades[localidad_seleccionada]
            punto = ee.Geometry.Point(config['coords'])
            area_estudio = punto.buffer(10000)  # Radio de 10km
        
        # Obtener imagen Landsat 8
        coleccion = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
            .filterBounds(area_estudio) \
            .filterDate(fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')) \
            .filter(ee.Filter.lt('CLOUD_COVER', 20))
        
        # Verificar si hay imágenes disponibles
        count = coleccion.size().getInfo()
        if count == 0:
            return None, "No se encontraron imágenes satelitales para las fechas seleccionadas"
        
        # Obtener la imagen más reciente
        imagen = coleccion.sort('system:time_start', False).first()
        
        # Calcular LST
        lst = calcular_lst_landsat8(imagen)
        
        # Calcular estadísticas
        stats = lst.reduceRegion(
            reducer=ee.Reducer.mean().combine(
                reducer2=ee.Reducer.minMax(), 
                sharedInputs=True
            ),
            geometry=area_estudio,
            scale=30,
            maxPixels=1e9
        ).getInfo()
        
        # Preparar resultados
        resultados = {
            'imagen_lst': lst,
            'area_estudio': area_estudio,
            'estadisticas': {
                'temp_promedio': round(stats.get('LST_mean', 0), 2),
                'temp_minima': round(stats.get('LST_min', 0), 2),
                'temp_maxima': round(stats.get('LST_max', 0), 2),
                'rango_termico': round(stats.get('LST_max', 0) - stats.get('LST_min', 0), 2)
            },
            'metadatos': {
                'fecha_imagen': imagen.date().format('YYYY-MM-dd').getInfo(),
                'localidad': localidad_seleccionada,
                'n_imagenes': count,
                'usando_shapefile': usar_shapefile
            }
        }
        
        return resultados, None
        
    except Exception as e:
        return None, f"Error en el análisis: {str(e)}"

# Función de respaldo si falla el shapefile
def analizar_isla_calor_fallback(localidad_seleccionada, fecha_inicio, fecha_fin):
    """Análisis usando coordenadas predeterminadas"""
    localidades = cargar_datos_localidades()
    config = localidades[localidad_seleccionada]
    punto = ee.Geometry.Point(config['coords'])
    area_estudio = punto.buffer(10000)
    
    # Obtener imagen Landsat 8
    coleccion = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterBounds(area_estudio) \
        .filterDate(fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')) \
        .filter(ee.Filter.lt('CLOUD_COVER', 20))
    
    count = coleccion.size().getInfo()
    if count == 0:
        return None, "No se encontraron imágenes satelitales"
    
    imagen = coleccion.sort('system:time_start', False).first()
    lst = calcular_lst_landsat8(imagen)
    
    stats = lst.reduceRegion(
        reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.minMax(), sharedInputs=True),
        geometry=area_estudio,
        scale=30,
        maxPixels=1e9
    ).getInfo()
    
    resultados = {
        'imagen_lst': lst,
        'area_estudio': area_estudio,
        'estadisticas': {
            'temp_promedio': round(stats.get('LST_mean', 0), 2),
            'temp_minima': round(stats.get('LST_min', 0), 2),
            'temp_maxima': round(stats.get('LST_max', 0), 2),
            'rango_termico': round(stats.get('LST_max', 0) - stats.get('LST_min', 0), 2)
        },
        'metadatos': {
            'fecha_imagen': imagen.date().format('YYYY-MM-dd').getInfo(),
            'localidad': localidad_seleccionada,
            'n_imagenes': count,
            'usando_shapefile': False
        }
    }
    
    return resultados, None

# Interfaz principal de la aplicación
def main():
    # Sidebar - Configuración
    st.sidebar.header("⚙️ Configuración del Análisis")
    
    # Cargar localidades disponibles
    st.sidebar.info("📁 Cargando localidades de Tabasco...")
    
    # Intentar cargar shapefile primero
    gdf = cargar_shapefile_localidades()
    if gdf is not None:
        localidades_disponibles = sorted(gdf['NOM_LOC'].unique().tolist())
        usar_shapefile = True
        st.sidebar.success(f"✅ Shapefile cargado: {len(localidades_disponibles)} localidades")
    else:
        localidades_data = cargar_datos_localidades()
        localidades_disponibles = sorted(localidades_data.keys())
        usar_shapefile = False
        st.sidebar.warning("⚠️ Usando coordenadas predeterminadas")
    
    # Selector de localidad
    localidad = st.sidebar.selectbox(
        "Selecciona una localidad:",
        localidades_disponibles,
        index=0
    )
    
    # Selector de fechas
    col1, col2 = st.sidebar.columns(2)
    with col1:
        fecha_inicio = st.date_input(
            "Fecha inicio",
            value=datetime.now() - timedelta(days=30),
            max_value=datetime.now()
        )
    with col2:
        fecha_fin = st.date_input(
            "Fecha fin", 
            value=datetime.now(),
            max_value=datetime.now()
        )
    
    # Validación de fechas
    if fecha_inicio >= fecha_fin:
        st.sidebar.error("❌ La fecha inicio debe ser anterior a la fecha fin")
        return
    
    # Botón de ejecución
    st.sidebar.markdown("---")
    ejecutar_analisis = st.sidebar.button(
        "🚀 Ejecutar Análisis de Isla de Calor", 
        type="primary",
        use_container_width=True
    )
    
    # Información del sidebar
    st.sidebar.markdown("---")
    st.sidebar.info("""
    **ℹ️ Instrucciones:**
    1. Selecciona una localidad de Tabasco
    2. Define el rango de fechas
    3. Haz click en 'Ejecutar Análisis'
    4. Visualiza los resultados específicos del polígono
    """)
    
    # Inicializar GEE
    if not initialize_gee():
        st.error("""
        **🔐 Configuración Requerida**
        
        Para que la aplicación funcione, necesitas configurar las credenciales de Google Earth Engine.
        
        **En Streamlit Cloud:**
        1. Ve a Settings → Secrets
        2. Agrega:
        ```
        GEE_SERVICE_ACCOUNT = "tu-service-account@..."
        GEE_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\n..."
        ```
        """)
        return
    
    # Ejecutar análisis cuando se presiona el botón
    if ejecutar_analisis:
        with st.spinner("🛰️ Analizando datos satelitales..."):
            resultados, error = analizar_isla_calor(localidad, fecha_inicio, fecha_fin, usar_shapefile)
            
            if error:
                st.error(f"❌ {error}")
                return
            
            if resultados:
                mostrar_resultados(resultados)

# Función para mostrar resultados
def mostrar_resultados(resultados):
    st.success("✅ Análisis completado exitosamente!")
    
    # Mostrar metadatos
    metadatos = resultados['metadatos']
    st.subheader(f"📊 Resultados para {metadatos['localidad']}")
    
    col_meta1, col_meta2, col_meta3, col_meta4 = st.columns(4)
    with col_meta1:
        st.metric("Fecha de Imagen", metadatos['fecha_imagen'])
    with col_meta2:
        st.metric("Localidad", metadatos['localidad'])
    with col_meta3:
        st.metric("Imágenes Disponibles", metadatos['n_imagenes'])
    with col_meta4:
        fuente = "Shapefile" if metadatos['usando_shapefile'] else "Coordenadas"
        st.metric("Fuente de datos", fuente)
    
    st.markdown("---")
    
    # Mostrar estadísticas de temperatura
    st.subheader("🌡 Estadísticas de Temperatura")
    stats = resultados['estadisticas']
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Temperatura Promedio", f"{stats['temp_promedio']}°C")
    with col2:
        st.metric("Temperatura Mínima", f"{stats['temp_minima']}°C")
    with col3:
        st.metric("Temperatura Máxima", f"{stats['temp_maxima']}°C")
    with col4:
        st.metric("Rango Térmico", f"{stats['rango_termico']}°C")
    
    st.markdown("---")
    
    # Mostrar mapa de temperatura
    st.subheader("🗺 Mapa de Temperatura Superficial")
    
    try:
        # Crear mapa interactivo
        Map = geemap.Map()
        Map.centerObject(resultados['area_estudio'], 10)
        
        # Añadir capa de temperatura
        vis_params = {
            'min': stats['temp_minima'] - 5,
            'max': stats['temp_maxima'] + 5,
            'palette': ['blue', 'cyan', 'green', 'yellow', 'orange', 'red']
        }
        
        Map.addLayer(resultados['imagen_lst'], vis_params, "Temperatura Superficial (°C)")
        Map.addLayer(resultados['area_estudio'], {'color': 'white'}, "Área de Estudio")
        Map.add_colorbar(vis_params, label="Temperatura (°C)")
        
        # Mostrar mapa en Streamlit
        Map.to_streamlit(height=500)
        
    except Exception as e:
        st.error(f"Error al generar el mapa: {str(e)}")
    
    # Interpretación de resultados
    st.markdown("---")
    st.subheader("📈 Interpretación de Resultados")
    
    temp_promedio = stats['temp_promedio']
    
    if temp_promedio < 25:
        st.info("**Zona Fría:** Temperaturas bajas, posible efecto de áreas verdes o cuerpos de agua.")
    elif 25 <= temp_promedio < 30:
        st.success("**Zona Templada:** Temperaturas moderadas, equilibrio urbano-natural.")
    elif 30 <= temp_promedio < 35:
        st.warning("**Zona Cálida:** Temperaturas elevadas, posible efecto de isla de calor incipiente.")
    else:
        st.error("**Zona de Isla de Calor:** Temperaturas significativamente elevadas, efecto de isla de calor urbano pronunciado.")

# Ejecutar la aplicación
if __name__ == "__main__":
    main()
