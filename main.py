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
    "Google Maps": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Maps",
        overlay=True,
        control=True,
    ),
    "Google Satellite Hybrid": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite",
        overlay=True,
        control=True,
    ),
}

def connect_with_gee():
    """Conexión simplificada para Streamlit Cloud"""
    try:
        if all(key in st.secrets for key in ['GEE_SERVICE_ACCOUNT', 'GEE_PRIVATE_KEY']):
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            private_key = st.secrets["GEE_PRIVATE_KEY"].replace('\\n', '\n')
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            return True
    except Exception as e:
        st.warning(f"Service Account no disponible: {e}")
    
    try:
        ee.Initialize()
        st.session_state.gee_available = True
        return True
    except Exception as e:
        st.error(f"❌ Error conectando a Google Earth Engine: {e}")
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

def add_ee_layer(self, ee_object, vis_params, name):
    """Método para agregar capas de GEE a Folium"""
    try:
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
            ).add_to(self)
        elif isinstance(ee_object, ee.imagecollection.ImageCollection):
            ee_object_new = ee_object.mosaic()
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
            ).add_to(self)
        elif isinstance(ee_object, ee.geometry.Geometry):
            folium.GeoJson(
                data=ee_object.getInfo(), name=name, overlay=True, control=True
            ).add_to(self)
        elif isinstance(ee_object, ee.featurecollection.FeatureCollection):
            ee_object_new = ee.Image().paint(ee_object, 0, 2)
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
            ).add_to(self)
    except Exception as e:
        st.warning(f"No se pudo cargar la capa {name}: {e}")

# Asignar el método a Folium
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
        # Carga tu capa de localidades urbanas desde tus assets de GEE
        localidades_urbanas = ee.FeatureCollection("projects/ee-cando/assets/areas_urbanas_Tab")
        
        # Filtra la localidad específica por NOMGEO
        aoi_feature = localidades_urbanas.filter(ee.Filter.eq("NOMGEO", localidad_nombre)).first()
        
        # Obtiene la geometría y el centroide
        aoi_geometry = aoi_feature.geometry()
        centroid = aoi_geometry.centroid().coordinates().getInfo()
        
        # Las coordenadas vienen como [long, lat], las convertimos a (lat, long)
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
    """Realiza el análisis COMPLETO de islas de calor usando tu metodología exacta"""
    try:
        # =================================================================================
        # PASO 1: Cargar y procesar imágenes Landsat (igual que en tu código GEE)
        # =================================================================================
        
        # Cargar colección de imágenes Landsat 8
        coleccion = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterBounds(aoi_geometry)
                    .filterDate(fecha_inicio, fecha_fin)
                    .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                    .map(cloudMaskFunction)
                    .map(noThermalDataFunction))

        # Crear mosaico con percentil 50 (robusto)
        mosaico = coleccion.reduce(ee.Reducer.percentile([50]))

        # Mosaico RGB para referencia (color verdadero)
        mosaicoRGB = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                     .filterBounds(aoi_geometry)
                     .filterDate(fecha_inicio, fecha_fin)
                     .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                     .map(cloudMaskFunction)
                     .map(applyScale)
                     .median())

        # =================================================================================
        # PASO 2: Calcular Temperatura Superficial (LST) en Celsius
        # =================================================================================
        
        banda_termica = mosaico.select("ST_B10_p50")
        lstCelsius = (banda_termica
                     .multiply(0.00341802)
                     .add(149.0)
                     .subtract(273.15)
                     .rename("LST_Celsius"))

        # =================================================================================
        # PASO 3: Detección de Islas de Calor por UMBRAL ESTADÍSTICO
        # =================================================================================
        
        lstForThreshold = lstCelsius.rename("LST")
        
        # Calcular percentil para umbral (igual que en tu código)
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

        # Crear máscara de islas de calor con limpieza por tamaño mínimo
        uhiMask = lstForThreshold.gte(umbral)
        compCount = uhiMask.connectedPixelCount(maxSize=1024, eightConnected=True)
        uhiClean = uhiMask.updateMask(compCount.gte(min_pix_parche)).selfMask()

        # =================================================================================
        # PASO 4: Calcular Estadísticas y Métricas
        # =================================================================================
        
        # Estadísticas generales de LST
        stats = lstCelsius.reduceRegion(
            reducer=ee.Reducer.minMax()
            .combine(ee.Reducer.mean(), sharedInputs=True)
            .combine(ee.Reducer.percentile([5, 50, 95]), sharedInputs=True),
            geometry=aoi_geometry,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        # Área de islas de calor en hectáreas
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
            'n_imagenes': coleccion.size().getInfo()
        }
        
    except Exception as e:
        st.error(f"Error en el análisis: {str(e)}")
        return None

def show_map_panel():
    """Panel de mapas con análisis COMPLETO de islas de calor"""
    st.markdown("## 🌡️ Análisis de Islas de Calor - Áreas Urbanas de Tabasco")
    st.caption("Análisis usando los polígonos reales de áreas urbanas desde GEE Asset")

    if not connect_with_gee():
        st.error("No se pudo conectar con Google Earth Engine")
        return

    # Configuración del análisis
    col1, col2, col3 = st.columns(3)
    with col1:
        percentil_uhi = st.slider("Percentil para UHI", 80, 95, 90, 
                                 help="Percentil para definir el umbral de isla de calor (90 = percentil 90)")
    with col2:
        min_pix_parche = st.slider("Mínimo píxeles por parche", 1, 10, 3,
                                  help="Mínimo número de píxeles conectados para considerar isla de calor")
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
                # =================================================================================
                # VISUALIZACIÓN DE RESULTADOS EN EL MAPA (IGUAL QUE TU CÓDIGO GEE)
                # =================================================================================
                
                # 1. Mosaico RGB (Color Verdadero)
                vis_color_verdadero = {
                    'bands': ['SR_B4', 'SR_B3', 'SR_B2'],
                    'min': 0.0,
                    'max': 0.3
                }
                map_obj.add_ee_layer(resultados['mosaicoRGB'].clip(aoi_geometry), vis_color_verdadero, 
                                   "Color Verdadero (RGB)", True)

                # 2. Temperatura Superficial (LST)
                vis_params_lst = {
                    'palette': ['blue', 'cyan', 'green', 'yellow', 'red'],
                    'min': 28,
                    'max': 48,
                }
                map_obj.add_ee_layer(resultados['lstCelsius'].clip(aoi_geometry), vis_params_lst, 
                                   "Temperatura Superficial (°C) p50", True)

                # 3. Islas de Calor (EXACTAMENTE como en tu código GEE)
                map_obj.add_ee_layer(resultados['uhiClean'].clip(aoi_geometry), 
                                   {'palette': ['#d7301f']}, 
                                   f"Islas de Calor (≥ p{percentil_uhi})", True)

                # 4. Área de estudio (polígono real)
                map_obj.add_ee_layer(aoi_geometry, 
                                   {'color': 'white', 'fillColor': '00000000', 'weight': 2}, 
                                   f"Área Urbana: {st.session_state.locality}", True)

                # =================================================================================
                # PANEL DE RESULTADOS MEJORADO
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
                            'Valor (ha)': [
                                f"{resultados['area_total_ha']:.1f}",
                                f"{resultados['area_uhi_ha']:.1f}",
                                f"{resultados['porcentaje_uhi']:.1f}%"
                            ]
                        })
                        st.dataframe(df_areas, use_container_width=True)

                # Interpretación basada en los resultados reales
                with st.expander("🔍 Diagnóstico y Recomendaciones"):
                    porcentaje_uhi = resultados['porcentaje_uhi']
                    temp_promedio = resultados['estadisticas'].get('LST_Celsius_mean', 0)
                    
                    if porcentaje_uhi < 10:
                        st.success("**✅ BUENA SITUACIÓN:** Baja proporción de islas de calor")
                    elif 10 <= porcentaje_uhi < 25:
                        st.warning("**⚠️ ATENCIÓN:** Proporción moderada de islas de calor")
                    else:
                        st.error("**🚨 CRÍTICO:** Alta proporción de islas de calor")
                    
                    st.markdown(f"""
                    **Resumen para {st.session_state.locality}:**
                    - 📍 **Área analizada:** {resultados['area_total_ha']:.1f} ha
                    - 🔥 **Zonas críticas:** {resultados['area_uhi_ha']:.1f} ha ({porcentaje_uhi:.1f}%)
                    - 🌡 **Temperatura promedio:** {temp_promedio:.1f}°C
                    - 🎯 **Umbral UHI:** {resultados['umbral_uhi']:.1f}°C
                    
                    **Acciones recomendadas:**
                    - 🌳 **Reforestación estratégica** en zonas UHI identificadas
                    - 🏗 **Revisión de materiales** de construcción en áreas críticas
                    - 💧 **Incorporación de agua** en el paisaje urbano
                    - 🌬 **Protección de corredores** de ventilación natural
                    """)

    else:
        st.info("""
        **💡 Instrucciones:**
        1. Selecciona una localidad de Tabasco
        2. Define el rango de fechas para análisis  
        3. Ajusta parámetros si es necesario
        4. Haz click en **'Ejecutar Análisis con Geometría Real'**
        
        *El análisis usará los polígonos exactos de áreas urbanas desde tu asset de GEE*
        """)

    # Mostrar el mapa
    st_folium(map_obj, width=None, height=600)

# [El resto del código permanece igual - sidebar, configuración, etc.]

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
        index=15  # Teapa por defecto
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
        st.success("✅ Conectado a GEE")
    else:
        st.error("❌ No conectado a GEE")
    
    if st.button("🔗 Reconectar con Google Earth Engine", type="secondary"):
        connect_with_gee()
        st.rerun()

# Router principal
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.markdown("## 📈 Gráficas")
    st.info("Módulo de gráficas en desarrollo - Próximamente análisis temporales")
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
    - 🌡️ Monitoreo basado en Landsat 8/9
    
    *Usa el asset: projects/ee-cando/assets/areas_urbanas_Tab*
    """)
