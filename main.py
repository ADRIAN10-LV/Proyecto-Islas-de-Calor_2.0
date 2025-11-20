# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Corrección: Autenticación Service Account y optimización GEE
# --------------------------------------------------------------

import sys
import os
import ee
import datetime as dt
import streamlit as st
import folium
from streamlit_folium import st_folium
from pathlib import Path
import json

# Configuración de página al inicio para evitar errores
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# --- GESTIÓN DE ESTADO ---
if "locality" not in st.session_state:
    st.session_state.locality = "Teapa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = [17.558567, -92.948714] # Lat, Lon
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2023, 1, 1), dt.datetime.now().date())
if "gee_initialized" not in st.session_state:
    st.session_state.gee_initialized = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# Variable para el máximo de nubes
MAX_NUBES = 30

# --- FUNCIONES GEE ---

def connect_with_gee():
    """
    Conecta con GEE usando Service Account desde st.secrets.
    NO usa ee.Authenticate() para evitar pop-ups en servidor.
    """
    if st.session_state.gee_initialized:
        return True

    try:
        # Intentamos obtener las credenciales de los secretos de Streamlit
        # Se asume que en secrets.toml existe una sección [gcp_service_account]
        if "gcp_service_account" in st.secrets:
            service_account_info = dict(st.secrets["gcp_service_account"])
            
            credentials = ee.ServiceAccountCredentials(
                email=service_account_info["client_email"],
                key_data=json.dumps(service_account_info)
            )
            ee.Initialize(credentials)
            
        else:
            # Fallback: Intenta inicializar si ya hay credenciales en el entorno (local)
            ee.Initialize()
            
        st.session_state.gee_initialized = True
        st.toast("Google Earth Engine conectado exitosamente", icon="🌍")
        return True

    except Exception as e:
        st.error(f"Error conectando a GEE: {e}")
        st.warning("Asegúrate de configurar 'gcp_service_account' en .streamlit/secrets.toml")
        st.session_state.gee_initialized = False
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

# Método monkey-patch para agregar capas a Folium
def add_ee_layer(self, ee_object, vis_params, name):
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
        print(f"No se pudo mostrar la capa {name}: {e}")

# Asignar la función a la clase Folium Map
folium.Map.add_ee_layer = add_ee_layer

# --- INTERFAZ DE USUARIO ---

def get_roi_and_coords():
    """Obtiene la geometría y centra el mapa según la localidad seleccionada"""
    # Intentar leer el asset ID de secretos o usar variable de entorno
    asset_id = st.secrets.get("env", {}).get("GEE_LOCALITIES_ASSET")
    
    if not asset_id:
        # Valor fallback si no hay configuración (solo para que no crashee)
        st.error("Falta configurar 'GEE_LOCALITIES_ASSET' en secrets.toml")
        return None

    try:
        # Filtrar la colección
        fc = ee.FeatureCollection(asset_id)
        # Intentamos filtrar por NOMGEO, ajusta si tu shapefile tiene otro nombre de columna
        roi = fc.filter(ee.Filter.eq("NOMGEO", st.session_state.locality)).geometry()
        
        # Obtener centroide para centrar el mapa (operación del lado del servidor GEE -> Cliente)
        centroid = roi.centroid().coordinates().getInfo()
        # GEE devuelve [lon, lat], Folium usa [lat, lon]
        coords = [centroid[1], centroid[0]]
        st.session_state.coordinates = coords
        return roi
    except Exception as e:
        st.warning(f"No se encontró la localidad '{st.session_state.locality}' en el Asset o error de GEE: {e}")
        # Retornar un punto por defecto si falla
        p = ee.Geometry.Point([-92.948714, 17.558567])
        return p


def show_map_panel():
    st.markdown(f"### Análisis de Islas de Calor: {st.session_state.locality}")
    
    # 1. Inicializar GEE
    connected = connect_with_gee()
    
    # 2. Crear Mapa Base
    m = folium.Map(location=st.session_state.coordinates, zoom_start=13)
    
    # Agregar Capa Satélite Base de Google
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Hybrid",
        overlay=True,
        control=True
    ).add_to(m)

    if connected:
        with st.spinner("Procesando imágenes satelitales..."):
            # Obtener ROI
            roi = get_roi_and_coords()
            
            if roi:
                # Centrar mapa dinámicamente si cambiaron las coordenadas
                m.location = st.session_state.coordinates
                
                # COLECCIÓN LANDSAT
                # Convertir fechas de python a string formato 'YYYY-MM-DD' para GEE
                start_date = st.session_state.date_range[0].strftime("%Y-%m-%d")
                end_date = st.session_state.date_range[1].strftime("%Y-%m-%d")

                collection = (
                    ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterDate(start_date, end_date)
                    .filterBounds(roi)
                    .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                    .map(cloudMaskFunction)
                    .map(noThermalDataFunction)
                )
                
                # Verificar si hay imágenes
                count = collection.size().getInfo()
                if count > 0:
                    st.caption(f"Imágenes encontradas: {count}")
                    
                    # Reducción (Mediana o Percentil)
                    mosaico = collection.median().clip(roi)

                    # CÁLCULO DE TEMPERATURA (LST)
                    bandaTermica = mosaico.select("ST_B10")
                    
                    # Landsat 8 C2 L2: ST_B10 * 0.00341802 + 149.0 = Kelvin
                    lstCelsius = (
                        bandaTermica.multiply(0.00341802)
                        .add(149.0)
                        .subtract(273.15) # A Grados Celsius
                        .rename("LST_Celsius")
                    )

                    # Visualización LST
                    visParamsLST = {
                        "palette": ["blue", "cyan", "green", "yellow", "red"],
                        "min": 24, # Ajustado para trópico
                        "max": 42,
                    }
                    m.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C)")

                    # DETECCIÓN DE ISLAS DE CALOR (Percentil 90 local)
                    # Para el umbral, usamos reduceRegion sobre la imagen de temperatura calculada
                    percentilUHI = 90
                    stats = lstCelsius.reduceRegion(
                        reducer=ee.Reducer.percentile([percentilUHI]),
                        geometry=roi,
                        scale=30,
                        maxPixels=1e9,
                        bestEffort=True
                    )
                    
                    # Obtener el valor numérico del umbral
                    key = f"LST_Celsius" # El reducer mantiene el nombre de la banda
                    val_umbral = stats.get(key)
                    
                    # Crear máscara si el valor existe
                    # Usamos ee.Algorithms.If para seguridad, aunque en Python directo podemos validar si val_umbral no es None
                    uh_image = ee.Image(0) # Placeholder
                    
                    if val_umbral:
                        umbral_num = ee.Number(val_umbral)
                        uhiMask = lstCelsius.gte(umbral_num)
                        
                        # Limpieza de ruido (mínimo 3 pixeles conectados)
                        minPixParche = 3
                        compCount = uhiMask.connectedPixelCount(maxSize=128, eightConnected=True)
                        uhiClean = uhiMask.updateMask(compCount.gte(minPixParche)).selfMask()
                        
                        m.add_ee_layer(
                            uhiClean,
                            {"palette": ["#d7301f"]}, # Rojo intenso
                            f"Hotspots (> p{percentilUHI})"
                        )
                    
                    # Dibujar el borde de la zona de interés
                    empty = ee.Image().byte()
                    outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
                    m.add_ee_layer(outline, {"palette": "black"}, "Límite Localidad")

                else:
                    st.warning("No se encontraron imágenes Landsat válidas en este rango de fechas y nubosidad.")

    # Control de capas
    folium.LayerControl().add_to(m)
    
    # Renderizar mapa en Streamlit
    st_folium(m, width="100%", height=600)

# --- SIDEBAR Y NAVEGACIÓN ---

with st.sidebar:
    st.title("Tabasco Heat Watch 🔥")
    st.markdown("---")
    
    st.session_state.window = st.radio(
        "Navegación",
        ["Mapas", "Gráficas", "Acerca de"]
    )
    
    st.markdown("### Configuración")
    
    # Lista de municipios/localidades
    localidades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", 
        "Paraíso", "Frontera", "Macuspana", "Tenosique de Pino Suárez"
    ]
    
    st.session_state.locality = st.selectbox("Localidad", localidades, index=1)
    
    # Fechas
    min_d = dt.date(2014, 1, 1)
    max_d = dt.date.today()
    
    dates = st.date_input(
        "Rango de Análisis",
        value=st.session_state.date_range,
        min_value=min_d,
        max_value=max_d
    )
    if len(dates) == 2:
        st.session_state.date_range = dates

# --- ROUTER PRINCIPAL ---

if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Módulo de gráficas en desarrollo.")
else:
    st.markdown("""
    ### Acerca de
    Esta aplicación utiliza **Google Earth Engine** y **Landsat 8** para monitorear la temperatura superficial terrestre (LST).
    
    **Metodología:**
    1. Filtrado de nubes y sombras (QA_PIXEL).
    2. Cálculo de LST usando banda térmica B10 (Algoritmo Single Channel).
    3. Detección de anomalías térmicas usando el percentil 90 estadístico sobre la región de interés (ROI).
    """)

