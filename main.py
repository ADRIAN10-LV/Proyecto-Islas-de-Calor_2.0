# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import pandas as pd
import folium
from streamlit_folium import st_folium
import json

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
            st.success("✅ Conectado a Google Earth Engine")
            return True
            
    except Exception as e:
        st.warning(f"Service Account no disponible: {e}")
    
    try:
        ee.Initialize()
        st.session_state.gee_available = True
        st.success("✅ Conectado a Google Earth Engine")
        return True
    except Exception as e:
        st.error(f"❌ Error conectando a Google Earth Engine: {e}")
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

def get_all_localidades():
    """Obtiene todas las localidades disponibles del asset"""
    try:
        if not st.session_state.gee_available:
            return []
            
        localidades_urbanas = ee.FeatureCollection("projects/ee-cando/assets/areas_urbanas_Tab")
        
        # Obtener lista de nombres de localidades
        localidades_list = localidades_urbanas.aggregate_array('NOMGEO').getInfo()
        
        return sorted(localidades_list) if localidades_list else []
        
    except Exception as e:
        st.error(f"Error al cargar localidades: {str(e)}")
        return []

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

def get_all_polygons_geometry():
    """Obtiene TODOS los polígonos del asset para visualización"""
    try:
        if not st.session_state.gee_available:
            return None
            
        localidades_urbanas = ee.FeatureCollection("projects/ee-cando/assets/areas_urbanas_Tab")
        return localidades_urbanas.geometry()
        
    except Exception as e:
        st.error(f"Error al cargar todos los polígonos: {str(e)}")
        return None

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
        # =================================================================================
        # PASO 1: Cargar y procesar imágenes Landsat
        # =================================================================================
        
        st.info("📡 Cargando imágenes Landsat...")
        
        # Cargar colección de imágenes Landsat 8
        coleccion = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterBounds(aoi_geometry)
                    .filterDate(fecha_inicio, fecha_fin)
                    .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                    .map(cloudMaskFunction)
                    .map(noThermalDataFunction))

        # Verificar si hay imágenes disponibles
        count = coleccion.size().getInfo()
        st.info(f"📊 Encontradas {count} imágenes Landsat")
        
        if count == 0:
            st.error("❌ No se encontraron imágenes Landsat para el rango de fechas y área seleccionados")
            return None

        # Crear mosaico con percentil 50
        st.info("🔄 Creando mosaico de imágenes...")
        mosaico = coleccion.reduce(ee.Reducer.percentile([50]))

        # =================================================================================
        # PASO 2: Calcular Temperatura Superficial (LST) en Celsius
        # =================================================================================
        
        st.info("🌡️ Calculando temperatura superficial...")
        
        banda_termica = mosaico.select("ST_B10_p50")
        lstCelsius = (banda_termica
                     .multiply(0.00341802)
                     .add(149.0)
                     .subtract(273.15)
                     .rename("LST_Celsius"))

        # =================================================================================
        # PASO 3: Detección de Islas de Calor por UMBRAL ESTADÍSTICO
        # =================================================================================
        
        st.info("🔥 Detectando islas de calor...")
        
        lstForThreshold = lstCelsius.rename("LST")
        
        # Calcular percentil para umbral
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
        
        st.info("📈 Calculando estadísticas...")
        
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

        # Obtener URLs de tiles para el mapa
        st.info("🗺️ Generando visualizaciones...")
        
        # Parámetros de visualización para LST
        vis_params_lst = {
            'min': 25,
            'max': 45,
            'palette': ['blue', 'cyan', 'green', 'yellow', 'orange', 'red']
        }
        
        # Generar mapId para LST
        lst_map_id = lstCelsius.clip(aoi_geometry).getMapId(vis_params_lst)
        lst_tiles = lst_map_id['tile_fetcher'].url_format
        
        # Generar mapId para UHI
        uhi_map_id = uhiClean.clip(aoi_geometry).getMapId({'palette': ['#d7301f']})
        uhi_tiles = uhi_map_id['tile_fetcher'].url_format

        return {
            'lstCelsius': lstCelsius,
            'lst_tiles': lst_tiles,
            'uhi_tiles': uhi_tiles,
            'aoi_geometry': aoi_geometry,
            'estadisticas': stats,
            'area_uhi_ha': areaUHI_ha,
            'area_total_ha': area_total_ha,
            'porcentaje_uhi': porcentaje_uhi,
            'severidad': sevStats,
            'umbral_uhi': umbral.getInfo(),
            'n_imagenes': count,
            'vis_params_lst': vis_params_lst
        }
        
    except Exception as e:
        st.error(f"❌ Error en el análisis: {str(e)}")
        return None

def create_map_with_layers(center, resultados, aoi_geometry, locality, show_all_polygons=False):
    """Crea un mapa Folium con las capas de GEE y polígonos VISIBLES"""
    try:
        # Crear mapa base
        m = folium.Map(
            location=[center[0], center[1]],
            zoom_start=12,
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            attr='Google Satellite'
        )
        
        # Agregar capa de LST
        if resultados and 'lst_tiles' in resultados:
            folium.TileLayer(
                tiles=resultados['lst_tiles'],
                attr='Google Earth Engine - LST',
                name='🌡️ Temperatura Superficial (°C)',
                overlay=True,
                control=True
            ).add_to(m)
        
        # Agregar capa de Islas de Calor
        if resultados and 'uhi_tiles' in resultados:
            folium.TileLayer(
                tiles=resultados['uhi_tiles'],
                attr='Google Earth Engine - UHI',
                name='🔥 Islas de Calor',
                overlay=True,
                control=True
            ).add_to(m)
        
        # 🔥 NUEVO: Cargar y mostrar TODOS los polígonos del asset
        if show_all_polygons:
            try:
                all_polygons = get_all_polygons_geometry()
                if all_polygons:
                    # Convertir la FeatureCollection a GeoJSON
                    polygons_json = all_polygons.getInfo()
                    
                    # Agregar todos los polígonos al mapa
                    folium.GeoJson(
                        polygons_json,
                        name='🗺️ Todas las Áreas Urbanas',
                        style_function=lambda x: {
                            'fillColor': 'none',
                            'color': 'yellow',
                            'weight': 2,
                            'fillOpacity': 0.1
                        },
                        tooltip=folium.GeoJsonTooltip(
                            fields=['NOMGEO'],
                            aliases=['Localidad:'],
                            localize=True
                        )
                    ).add_to(m)
            except Exception as e:
                st.warning(f"No se pudieron cargar todos los polígonos: {e}")
        
        # Agregar polígono del área de estudio seleccionada (más destacado)
        if aoi_geometry:
            try:
                # Obtener información específica del polígono seleccionado
                localidades_urbanas = ee.FeatureCollection("projects/ee-cando/assets/areas_urbanas_Tab")
                selected_feature = localidades_urbanas.filter(ee.Filter.eq("NOMGEO", locality)).first()
                
                if selected_feature:
                    feature_info = selected_feature.getInfo()
                    
                    folium.GeoJson(
                        feature_info['geometry'],
                        name=f'📍 Área de Estudio: {locality}',
                        style_function=lambda x: {
                            'fillColor': 'none',
                            'color': 'white',
                            'weight': 4,
                            'fillOpacity': 0
                        },
                        tooltip=folium.GeoJsonTooltip(
                            fields=['NOMGEO'],
                            aliases=['Localidad:'],
                            localize=True
                        )
                    ).add_to(m)
            except Exception as e:
                st.warning(f"No se pudo cargar el polígono seleccionado: {e}")
        
        # Agregar control de capas
        folium.LayerControl().add_to(m)
        
        return m
        
    except Exception as e:
        st.error(f"❌ Error creando el mapa: {str(e)}")
        return None

def show_map_panel():
    """Panel de mapas con análisis COMPLETO de islas de calor"""
    st.markdown("## 🌡️ Análisis de Islas de Calor - Áreas Urbanas de Tabasco")
    st.caption("Análisis usando los polígonos reales de áreas urbanas desde GEE Asset")

    # Verificar conexión GEE
    if not st.session_state.get('gee_available', False):
        if not connect_with_gee():
            st.error("""
            **🔐 Configuración Requerida**
            
            Para usar la aplicación, configura las credenciales de Google Earth Engine en Streamlit Cloud:
            
            1. Ve a **Settings → Secrets**
            2. Agrega:
            ```
            GEE_SERVICE_ACCOUNT = "streamlit-bot@ee-cando.iam.gserviceaccount.com"
            GEE_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\n..."
            ```
            """)
            return

    # Obtener lista de localidades disponibles
    localidades_disponibles = get_all_localidades()
    if not localidades_disponibles:
        st.error("No se pudieron cargar las localidades desde GEE")
        return

    # Configuración del análisis
    col1, col2, col3 = st.columns(3)
    with col1:
        percentil_uhi = st.slider("Percentil para UHI", 80, 95, 90)
    with col2:
        min_pix_parche = st.slider("Mínimo píxeles por parche", 1, 10, 3)
    with col3:
        mostrar_todos_poligonos = st.checkbox("Mostrar todas las áreas urbanas", value=True)

    # Selector de localidad actualizado
    st.session_state.locality = st.selectbox(
        "Selecciona localidad para análisis:",
        localidades_disponibles,
        index=localidades_disponibles.index(st.session_state.locality) if st.session_state.locality in localidades_disponibles else 0
    )

    set_coordinates()

    # Selector de fechas
    min_date, max_date = dt.date(2014, 1, 1), dt.date.today()
    date_range = st.date_input(
        "Rango de fechas para análisis",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    # Botón de ejecución
    ejecutar_analisis = st.button("🚀 Ejecutar Análisis con Geometría Real", type="primary")

    # Obtener geometría actual
    aoi_geometry, coordinates = get_localidad_geometry(st.session_state.locality)
    
    if aoi_geometry is None:
        st.error("No se pudo cargar la geometría de la localidad seleccionada")
        # Crear mapa básico sin análisis pero con polígonos
        m = create_map_with_layers(
            coordinates if coordinates else st.session_state.coordinates,
            None,
            aoi_geometry,
            st.session_state.locality,
            show_all_polygons=mostrar_todos_poligonos
        )
        if m:
            st_folium(m, width=None, height=500)
        return

    # Ejecutar análisis cuando se presiona el botón
    if ejecutar_analisis and st.session_state.gee_available:
        with st.spinner("🛰️ Realizando análisis completo de islas de calor..."):
            
            fecha_inicio = st.session_state.date_range[0].strftime("%Y-%m-%d")
            fecha_fin = st.session_state.date_range[1].strftime("%Y-%m-%d")
            
            resultados = analizar_islas_calor_completo(aoi_geometry, fecha_inicio, fecha_fin, percentil_uhi, min_pix_parche)
            
            if resultados:
                # =================================================================================
                # MOSTRAR RESULTADOS NUMÉRICOS
                # =================================================================================
                
                st.success("✅ Análisis completado exitosamente!")
                
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
                            'Métrica': ['Mínima', 'Promedio', 'Mediana', 'Máxima'],
                            'Temperatura (°C)': [
                                stats.get('LST_Celsius_min', 0),
                                stats.get('LST_Celsius_mean', 0),
                                stats.get('LST_Celsius_p50', 0),
                                stats.get('LST_Celsius_max', 0)
                            ]
                        })
                        st.dataframe(df_stats, use_container_width=True)
                    
                    with col2:
                        st.subheader("Áreas y Cobertura")
                        df_areas = pd.DataFrame({
                            'Métrica': ['Área Total', 'Área UHI', 'Porcentaje UHI', 'Imágenes Usadas'],
                            'Valor': [
                                f"{resultados['area_total_ha']:.1f} ha",
                                f"{resultados['area_uhi_ha']:.1f} ha",
                                f"{resultados['porcentaje_uhi']:.1f}%",
                                f"{resultados['n_imagenes']}"
                            ]
                        })
                        st.dataframe(df_areas, use_container_width=True)

                # =================================================================================
                # CREAR Y MOSTRAR MAPA CON POLÍGONOS VISIBLES
                # =================================================================================
                
                st.markdown("### 🗺️ Mapa de Resultados")
                
                # Crear mapa con las capas de GEE y polígonos
                map_obj = create_map_with_layers(
                    coordinates, 
                    resultados, 
                    aoi_geometry, 
                    st.session_state.locality,
                    show_all_polygons=mostrar_todos_poligonos
                )
                
                if map_obj:
                    # Mostrar el mapa
                    st_folium(map_obj, width=None, height=600)
                    
                    st.info("""
                    **💡 Instrucciones del mapa:**
                    - Usa el control de capas (ⓘ) en la esquina superior derecha para activar/desactivar capas
                    - **🌡️ Temperatura Superficial:** Mapa de calor con temperaturas en °C
                    - **🔥 Islas de Calor:** Áreas que superan el percentil establecido
                    - **📍 Área de Estudio:** Límite del área urbana seleccionada (blanco)
                    - **🗺️ Todas las Áreas Urbanas:** Polígonos de todas las localidades (amarillo)
                    """)
                else:
                    st.error("No se pudo crear el mapa con los resultados")

            else:
                st.error("No se pudieron obtener resultados del análisis")

    else:
        # Mostrar mapa básico con polígonos cuando no hay análisis
        st.info("""
        **💡 Instrucciones:**
        1. Selecciona una localidad de Tabasco
        2. Define el rango de fechas para análisis  
        3. Haz click en **'Ejecutar Análisis con Geometría Real'**
        
        *El análisis usará los polígonos exactos de áreas urbanas desde tu asset de GEE*
        """)
        
        # Mapa básico con polígonos visibles
        m = create_map_with_layers(
            coordinates,
            None,
            aoi_geometry,
            st.session_state.locality,
            show_all_polygons=mostrar_todos_poligonos
        )
        if m:
            st_folium(m, width=None, height=500)

# Sidebar simplificado
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
    
    # Estado de conexión
    if st.session_state.gee_available:
        st.success("✅ **CONECTADO A GEE**")
        st.caption("Listo para analizar")
    else:
        st.error("❌ **NO CONECTADO**")
        st.caption("Configura las credenciales")
    
    if st.button("🔄 Verificar Conexión GEE"):
        connect_with_gee()
        st.rerun()

# Router principal
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.markdown("## 📈 Gráficas")
    st.info("""
    **Próximamente:**
    - Gráficas de evolución temporal de temperaturas
    - Comparación entre diferentes localidades
    - Análisis de tendencias estacionales
    """)
elif st.session_state.window == "Reportes":
    st.markdown("## 📊 Reportes")
    st.info("""
    **Próximamente:**
    - Generación de reportes PDF automáticos
    - Exportación de datos en CSV
    - Reportes comparativos entre periodos
    """)
elif st.session_state.window == "Acerca de":
    st.markdown("## ℹ️ Acerca de")
    st.write("""
    **Dashboard para análisis de Islas de Calor Urbano en Tabasco**
    
    **Características:**
    - 🗺️ Uso de geometrías reales de áreas urbanas desde GEE
    - 🔥 Detección precisa de islas de calor por percentiles
    - 📊 Análisis estadístico dentro de polígonos urbanos
    - 🌡️ Monitoreo basado en Landsat 8/9
    
    **Asset utilizado:** `projects/ee-cando/assets/areas_urbanas_Tab`
    
    **Tecnologías:**
    - Google Earth Engine
    - Streamlit
    - Folium
    - Landsat 8/9 Collection 2
    """)
