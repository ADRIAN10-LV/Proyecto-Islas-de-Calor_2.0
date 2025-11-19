# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import pandas as pd
import folium
from streamlit_folium import st_folium
from pathlib import Path

# Configuración de la página
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# Estado inicial
if "locality" not in st.session_state:
    st.session_state.locality = "Teapa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.558567, -92.948714)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.date.today())
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

MAX_NUBES = 30

# Mapas para agregar a folium
BASEMAPS = {
    "Google Satellite Hybrid": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite",
        overlay=True,
        control=True,
    ),
}

def connect_with_gee():
    """Conexión MEJORADA para Streamlit Cloud"""
    try:
        if st.session_state.get('gee_available', False):
            return True
            
        if all(key in st.secrets for key in ['GEE_SERVICE_ACCOUNT', 'GEE_PRIVATE_KEY']):
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            private_key = st.secrets["GEE_PRIVATE_KEY"].replace('\\n', '\n')
            
            if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                st.error("❌ Formato incorrecto de la clave privada en Secrets")
                return False
                
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            return True
            
    except ee.EEException as e:
        st.error(f"❌ Error de Google Earth Engine: {str(e)}")
    except Exception as e:
        st.error(f"❌ Error inesperado: {str(e)}")
    
    try:
        ee.Initialize()
        st.session_state.gee_available = True
        return True
    except Exception as e:
        st.error("""
        **🔐 CONFIGURACIÓN REQUERIDA - Google Earth Engine**
        
        Para que la aplicación funcione, necesitas configurar las credenciales de GEE.
        
        **En Streamlit Cloud → Settings → Secrets agrega:**
        ```toml
        GEE_SERVICE_ACCOUNT = "streamlit-bot@ee-cando.iam.gserviceaccount.com"
        GEE_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\n..."
        ```
        """)
        st.session_state.gee_available = False
        return False

def cloudMaskFunction(image):
    qa = image.select("QA_PIXEL")
    cloud_mask = qa.bitwiseAnd(1 << 5)
    shadow_mask = qa.bitwiseAnd(1 << 3)
    combined_mask = cloud_mask.Or(shadow_mask).eq(0)
    return image.updateMask(combined_mask)

def noThermalDataFunction(image):
    st_band = image.select("ST_B10")
    valid = st_band.gt(0).And(st_band.lt(65535))
    return image.updateMask(valid)

def applyScale(image):
    opticalBands = image.select(["SR_B2", "SR_B3", "SR_B4"]).multiply(0.0000275).add(-0.2)
    return image.addBands(opticalBands, None, True)

# 🔧 FUNCIÓN add_ee_layer CORREGIDA
def add_ee_layer(self, ee_image, vis_params, layer_name):
    """Método CORREGIDO para agregar capas de GEE a Folium"""
    try:
        # Asegurarnos de que tenemos una imagen válida
        if not isinstance(ee_image, ee.Image):
            st.warning(f"❌ No se puede cargar {layer_name}: no es una imagen válida")
            return
            
        map_id_dict = ee_image.getMapId(vis_params)
        
        folium.raster_layers.TileLayer(
            tiles=map_id_dict["tile_fetcher"].url_format,
            attr="Google Earth Engine",
            name=layer_name,
            overlay=True,
            control=True,
        ).add_to(self)
        
    except Exception as e:
        st.warning(f"⚠️ No se pudo cargar la capa {layer_name}: {str(e)}")

# Asignar el método corregido a Folium
folium.Map.add_ee_layer = add_ee_layer

def create_map(center=None, zoom_start=12):
    """Crea un mapa base Folium"""
    if center is None:
        center = st.session_state.coordinates
    
    map_obj = folium.Map(
        location=[center[0], center[1]], 
        zoom_start=zoom_start
    )
    return map_obj

def get_localidad_geometry(localidad_nombre):
    """Obtiene la geometría exacta de la localidad desde tu asset de GEE"""
    try:
        if not st.session_state.gee_available:
            return None, st.session_state.coordinates
            
        localidades_urbanas = ee.FeatureCollection("projects/ee-cando/assets/areas_urbanas_Tab")
        aoi_feature = localidades_urbanas.filter(ee.Filter.eq("NOMGEO", localidad_nombre)).first()
        
        if aoi_feature is None:
            st.error(f"No se encontró la localidad '{localidad_nombre}' en el asset de GEE")
            return None, st.session_state.coordinates
            
        aoi_geometry = aoi_feature.geometry()
        centroid = aoi_geometry.centroid().coordinates().getInfo()
        coordinates = (centroid[1], centroid[0])
        
        return aoi_geometry, coordinates
        
    except Exception as e:
        st.error(f"Error al cargar geometría para {localidad_nombre}: {str(e)}")
        return None, st.session_state.coordinates

def set_coordinates():
    """Configura coordenadas usando el asset de GEE"""
    aoi_geometry, coordinates = get_localidad_geometry(st.session_state.locality)
    if coordinates:
        st.session_state.coordinates = coordinates
    if aoi_geometry:
        st.session_state.aoi_geometry = aoi_geometry

def analizar_islas_calor_completo(aoi_geometry, fecha_inicio, fecha_fin, percentil_uhi=90, min_pix_parche=3):
    """Realiza el análisis COMPLETO de islas de calor"""
    try:
        # Cargar colección de imágenes Landsat 8
        coleccion = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterBounds(aoi_geometry)
                    .filterDate(fecha_inicio, fecha_fin)
                    .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                    .map(cloudMaskFunction)
                    .map(noThermalDataFunction))

        # Verificar si hay imágenes disponibles
        count = coleccion.size().getInfo()
        if count == 0:
            st.error("No se encontraron imágenes Landsat para el rango de fechas y área seleccionados")
            return None

        # Crear mosaico con percentil 50
        mosaico = coleccion.reduce(ee.Reducer.percentile([50]))

        # Mosaico RGB para referencia
        mosaicoRGB = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                     .filterBounds(aoi_geometry)
                     .filterDate(fecha_inicio, fecha_fin)
                     .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                     .map(cloudMaskFunction)
                     .map(applyScale)
                     .median())

        # Calcular LST
        banda_termica = mosaico.select("ST_B10_p50")
        lstCelsius = (banda_termica
                     .multiply(0.00341802)
                     .add(149.0)
                     .subtract(273.15)
                     .rename("LST_Celsius"))

        # Detección de Islas de Calor
        lstForThreshold = lstCelsius.rename("LST")
        
        pctDict = lstForThreshold.reduceRegion(
            reducer=ee.Reducer.percentile([percentil_uhi]),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        )

        key = ee.String("LST_p").cat(ee.Number(percentil_uhi).format())
        umbral = ee.Algorithms.If(
            pctDict.contains(key),
            ee.Number(pctDict.get(key)),
            ee.Number(ee.Dictionary(pctDict).values().get(0)),
        )
        umbral = ee.Number(umbral)

        # Crear máscara de islas de calor
        uhiMask = lstForThreshold.gte(umbral)
        compCount = uhiMask.connectedPixelCount(maxSize=1024, eightConnected=True)
        uhiClean = uhiMask.updateMask(compCount.gte(min_pix_parche)).selfMask()

        # Calcular estadísticas
        stats = lstCelsius.reduceRegion(
            reducer=ee.Reducer.minMax()
            .combine(ee.Reducer.mean(), sharedInputs=True)
            .combine(ee.Reducer.percentile([5, 50, 95]), sharedInputs=True),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        # Área de islas de calor
        areaUHI = ee.Image.pixelArea().updateMask(uhiClean).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        ).get("area")

        areaUHI_ha = ee.Number(areaUHI).divide(10000).getInfo() if areaUHI else 0

        # Severidad en zonas UHI
        sevStats = lstCelsius.updateMask(uhiClean).reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        # Porcentaje de área urbana que es UHI
        area_total = ee.Image.pixelArea().reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        ).get("area")
        
        area_total_ha = ee.Number(area_total).divide(10000).getInfo() if area_total else 1
        porcentaje_uhi = (areaUHI_ha / area_total_ha * 100) if area_total_ha > 0 else 0

        return {
            'mosaicoRGB': mosaicoRGB,
            'lstCelsius': lstCelsius,
            'uhiClean': uhiClean,
            'aoi_geometry': aoi_geometry,
            'estadisticas': stats,
            'area_uhi_ha': areaUHI_ha,
            'area_total_ha': area_total_ha,
            'porcentaje_uhi': porcentaje_uhi,
            'severidad': sevStats,
            'umbral_uhi': umbral.getInfo(),
            'n_imagenes': count
        }
        
    except Exception as e:
        st.error(f"Error en el análisis: {str(e)}")
        return None

def show_map_panel():
    """Panel de mapas con análisis COMPLETO de islas de calor"""
    st.markdown("## 🌡️ Análisis de Islas de Calor - Áreas Urbanas de Tabasco")
    st.caption("Análisis usando los polígonos reales de áreas urbanas desde GEE Asset")

    if not st.session_state.get('gee_available', False):
        connect_with_gee()

    if not st.session_state.gee_available:
        st.error("No se pudo conectar con Google Earth Engine. Configura las credenciales en Secrets.")
        return

    # Configuración del análisis
    col1, col2, col3 = st.columns(3)
    with col1:
        percentil_uhi = st.slider("Percentil para UHI", 80, 95, 90)
    with col2:
        min_pix_parche = st.slider("Mínimo píxeles por parche", 1, 10, 3)
    with col3:
        st.markdown("###")
        ejecutar_analisis = st.button("🚀 Ejecutar Análisis con Geometría Real", type="primary")

    # Obtener geometría actual
    aoi_geometry, _ = get_localidad_geometry(st.session_state.locality)
    
    if aoi_geometry is None:
        st.error("No se pudo cargar la geometría de la localidad seleccionada")
        return

    map_obj = create_map()
    if map_obj is None:
        st.error("Error al crear el mapa")
        return

    # Agregar base map
    BASEMAPS["Google Satellite Hybrid"].add_to(map_obj)

    if ejecutar_analisis and st.session_state.gee_available:
        with st.spinner("🛰️ Realizando análisis completo de islas de calor..."):
            
            fecha_inicio = st.session_state.date_range[0].strftime("%Y-%m-%d")
            fecha_fin = st.session_state.date_range[1].strftime("%Y-%m-%d")
            
            resultados = analizar_islas_calor_completo(aoi_geometry, fecha_inicio, fecha_fin, percentil_uhi, min_pix_parche)
            
            if resultados:
                # 🔧 VISUALIZACIÓN CORREGIDA - SIN PARÁMETROS EXTRA
                
                # 1. Mosaico RGB (Color Verdadero)
                vis_color_verdadero = {
                    'bands': ['SR_B4', 'SR_B3', 'SR_B2'],
                    'min': 0.0,
                    'max': 0.3
                }
                map_obj.add_ee_layer(
                    resultados['mosaicoRGB'].clip(aoi_geometry), 
                    vis_color_verdadero, 
                    "Color Verdadero (RGB)"
                )

                # 2. Temperatura Superficial (LST)
                vis_params_lst = {
                    'palette': ['blue', 'cyan', 'green', 'yellow', 'red'],
                    'min': 28,
                    'max': 48,
                }
                map_obj.add_ee_layer(
                    resultados['lstCelsius'].clip(aoi_geometry), 
                    vis_params_lst, 
                    "Temperatura Superficial (°C) p50"
                )

                # 3. Islas de Calor
                map_obj.add_ee_layer(
                    resultados['uhiClean'].clip(aoi_geometry), 
                    {'palette': ['#d7301f']}, 
                    f"Islas de Calor (≥ p{percentil_uhi})"
                )

                # 4. Área de estudio (polígono real)
                try:
                    # Para geometrías, usamos GeoJson directamente
                    folium.GeoJson(
                        data=aoi_geometry.getInfo(),
                        name=f"Área Urbana: {st.session_state.locality}",
                        style_function=lambda x: {
                            'color': 'white',
                            'weight': 2,
                            'fillColor': '00000000'
                        }
                    ).add_to(map_obj)
                except Exception as e:
                    st.warning(f"No se pudo agregar el polígono del área de estudio: {e}")

                # =================================================================================
                # PANEL DE RESULTADOS
                # =================================================================================
                
                st.success("✅ Análisis completado usando geometrías reales!")

                # Métricas principales
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    temp_promedio = resultados['estadisticas'].get('LST_Celsius_mean', 0)
                    st.metric("🌡 Temp. Promedio", f"{temp_promedio:.1f}°C")
                
                with col2:
                    st.metric("🔥 Umbral UHI", f"{resultados['umbral_uhi']:.1f}°C")
                
                with col3:
                    st.metric("🏝 Área UHI", f"{resultados['area_uhi_ha']:.1f} ha")
                
                with col4:
                    st.metric("📊 % Área UHI", f"{resultados['porcentaje_uhi']:.1f}%")

                # Estadísticas detalladas
                with st.expander("📈 Estadísticas Detalladas del Área Urbana"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Distribución de Temperaturas")
                        stats = resultados['estadisticas']
                        df_stats = pd.DataFrame({
                            'Percentil': ['P5', 'P50 (Mediana)', 'P95'],
                            'Temperatura (°C)': [
                                stats.get('LST_Celsius_p5', 0),
                                stats.get('LST_Celsius_p50', 0),
                                stats.get('LST_Celsius_p95', 0)
                            ]
                        })
                        st.dataframe(df_stats, use_container_width=True)
                    
                    with col2:
                        st.subheader("Áreas y Cobertura")
                        df_areas = pd.DataFrame({
                            'Métrica': ['Área Total', 'Área UHI', 'Porcentaje UHI'],
                            'Valor': [
                                f"{resultados['area_total_ha']:.1f} ha",
                                f"{resultados['area_uhi_ha']:.1f} ha",
                                f"{resultados['porcentaje_uhi']:.1f}%"
                            ]
                        })
                        st.dataframe(df_areas, use_container_width=True)

    else:
        st.info("""
        **💡 Instrucciones:**
        1. Selecciona una localidad de Tabasco
        2. Define el rango de fechas para análisis  
        3. Haz click en **'Ejecutar Análisis con Geometría Real'**
        """)

    # Mostrar el mapa
    st_folium(map_obj, width=None, height=600)

# Sidebar
with st.sidebar:
    st.markdown("# 🌡 Islas de Calor Tabasco")
    st.caption("Análisis con geometrías reales de áreas urbanas")

    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )
    st.session_state.window = section

    st.markdown("---")
    st.markdown("### ⚙️ Configuración")

    st.session_state.locality = st.selectbox(
        "Localidad de estudio",
        [
            "Balancán", "Cárdenas", "Frontera", "Villahermosa", "Comalcalco",
            "Cunduacán", "Emiliano Zapata", "Huimanguillo", "Jalapa",
            "Jalpa de Méndez", "Jonuta", "Macuspana", "Nacajuca", "Paraíso",
            "Tacotalpa", "Teapa", "Tenosique de Pino Suárez"
        ],
        index=15
    )

    set_coordinates()

    min_date, max_date = dt.date(2014, 1, 1), dt.date.today()
    date_range = st.date_input(
        "Rango de fechas para análisis",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    st.markdown("---")
    
    if st.session_state.gee_available:
        st.success("✅ **CONECTADO A GEE**")
    else:
        st.error("❌ **NO CONECTADO A GEE**")
    
    if st.button("🔄 Verificar Conexión GEE", type="secondary"):
        connect_with_gee()
        st.rerun()

# Router principal
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.markdown("## 📈 Gráficas")
    st.info("Módulo de gráficas en desarrollo")
elif st.session_state.window == "Reportes":
    st.markdown("## 📊 Reportes")
    st.info("Módulo de reportes en desarrollo")
elif st.session_state.window == "Acerca de":
    st.markdown("## ℹ️ Acerca de")
    st.write("""
    **Dashboard para análisis de Islas de Calor Urbano en Tabasco**
    
    **Características:**
    - 🗺️ Uso de geometrías reales de áreas urbanas desde GEE
    - 🔥 Detección precisa de islas de calor por percentiles
    - 📊 Análisis estadístico dentro de polígonos urbanos
    
    *Usa el asset: projects/ee-cando/assets/areas_urbanas_Tab*
    """)
