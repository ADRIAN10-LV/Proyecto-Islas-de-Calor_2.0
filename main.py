import streamlit as st
import ee
import geemap
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json

# Configuración de la página
st.set_page_config(
    page_title="Análisis de Islas de Calor Urbanas",
    page_icon="🌡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título principal
st.title("🌡 Análisis de Islas de Calor Urbanas")
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

# Diccionario de coordenadas de ciudades españolas
CIUDADES = {
    "Madrid": {"coords": [-3.7038, 40.4168], "radio": 15000},
    "Barcelona": {"coords": [2.1734, 41.3851], "radio": 12000},
    "Valencia": {"coords": [-0.3774, 39.4699], "radio": 10000},
    "Sevilla": {"coords": [-5.9845, 37.3891], "radio": 10000},
    "Bilbao": {"coords": [-2.9349, 43.2630], "radio": 8000},
    "Zaragoza": {"coords": [-0.8891, 41.6488], "radio": 9000}
}

# Función para calcular temperatura LST de Landsat 8
def calcular_lst_landsat8(image):
    # Conversión a temperatura Celsius
    lst = image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)
    return lst.rename('LST')

# Análisis principal de isla de calor
def analizar_isla_calor(ciudad, fecha_inicio, fecha_fin):
    try:
        # Obtener configuración de la ciudad
        config = CIUDADES[ciudad]
        punto = ee.Geometry.Point(config['coords'])
        area = punto.buffer(config['radio'])  # Radio en metros
        
        # Obtener imagen Landsat 8
        coleccion = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
            .filterBounds(area) \
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
            geometry=area,
            scale=30,
            maxPixels=1e9
        ).getInfo()
        
        # Preparar resultados
        resultados = {
            'imagen_lst': lst,
            'area_estudio': area,
            'estadisticas': {
                'temp_promedio': round(stats.get('LST_mean', 0), 2),
                'temp_minima': round(stats.get('LST_min', 0), 2),
                'temp_maxima': round(stats.get('LST_max', 0), 2),
                'rango_termico': round(stats.get('LST_max', 0) - stats.get('LST_min', 0), 2)
            },
            'metadatos': {
                'fecha_imagen': imagen.date().format('YYYY-MM-dd').getInfo(),
                'ciudad': ciudad,
                'n_imagenes': count
            }
        }
        
        return resultados, None
        
    except Exception as e:
        return None, f"Error en el análisis: {str(e)}"

# Interfaz principal de la aplicación
def main():
    # Sidebar - Configuración
    st.sidebar.header("⚙️ Configuración del Análisis")
    
    # Selector de ciudad
    ciudad = st.sidebar.selectbox(
        "Selecciona una ciudad:",
        list(CIUDADES.keys()),
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
    1. Selecciona una ciudad
    2. Define el rango de fechas
    3. Haz click en 'Ejecutar Análisis'
    4. Visualiza los resultados
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
            resultados, error = analizar_isla_calor(ciudad, fecha_inicio, fecha_fin)
            
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
    st.subheader(f"📊 Resultados para {metadatos['ciudad']}")
    
    col_meta1, col_meta2, col_meta3 = st.columns(3)
    with col_meta1:
        st.metric("Fecha de Imagen", metadatos['fecha_imagen'])
    with col_meta2:
        st.metric("Ciudad", metadatos['ciudad'])
    with col_meta3:
        st.metric("Imágenes Disponibles", metadatos['n_imagenes'])
    
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
        Map.add_colorbar(vis_params, label="Temperatura (°C)")
        
        # Mostrar mapa en Streamlit
        Map.to_streamlit(height=500)
        
    except Exception as e:
        st.error(f"Error al generar el mapa: {str(e)}")
    
    # Interpretación de resultados
    st.markdown("---")
    st.subheader("📈 Interpretación de Resultados")
    
    temp_promedio = stats['temp_promedio']
    
    if temp_promedio < 15:
        st.info("**Zona Fría:** Temperaturas bajas, posible efecto de áreas verdes o cuerpos de agua.")
    elif 15 <= temp_promedio < 25:
        st.success("**Zona Templada:** Temperaturas moderadas, equilibrio urbano-natural.")
    elif 25 <= temp_promedio < 30:
        st.warning("**Zona Cálida:** Temperaturas elevadas, posible efecto de isla de calor incipiente.")
    else:
        st.error("**Zona de Isla de Calor:** Temperaturas significativamente elevadas, efecto de isla de calor urbano pronunciado.")
    
    # Recomendaciones
    with st.expander("💡 Recomendaciones para Mitigar Islas de Calor"):
        st.markdown("""
        - **Aumentar áreas verdes:** Parques y jardines reducen temperaturas
        - **Techos verdes:** Absorben calor y mejoran el aislamiento
        - **Materiales reflectantes:** Usar colores claros en pavimentos y techos
        - **Corredores de ventilación:** Mantener espacios abiertos para circulación de aire
        - **Agua en el paisaje:** Fuentes y estanques ayudan a refrescar el ambiente
        """)

# Ejecutar la aplicación
if __name__ == "__main__":
    main()

