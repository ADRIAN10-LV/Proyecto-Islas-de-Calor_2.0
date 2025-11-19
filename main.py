# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Autor: Adrian Lara (estructura base generada con ayuda de IA)
# --------------------------------------------------------------

import sys
import os
import ee
import datetime as dt
import streamlit as st
import folium
from folium import plugins
from streamlit_folium import st_folium
from pathlib import Path
from dotenv import load_dotenv
import json

# Cargamos el archivo de variables de entorno
load_dotenv()

# Carpetas de trabajo
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
TEMP_DIR = DATA_DIR / "temp"
for d in (DATA_DIR, REPORTS_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Estado inicial
if "locality" not in st.session_state:
    st.session_state.locality = "Teapa"  # Área de estudio
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.558567, -92.948714)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.datetime.now().date())
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# Variable para el máximo de nubes
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
    "Google Satellite": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite",
        overlay=True,
        control=True,
    ),
    "Google Terrain": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Terrain",
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
    "Esri Satellite": folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Satellite",
        overlay=True,
        control=True,
    ),
}

def connect_with_gee():
    """Conecta con Google Earth Engine usando las credenciales de Streamlit secrets"""
    if not st.session_state.get("gee_available", False):
        try:
            # Verificar si estamos usando service account o autenticación normal
            if "google" in st.secrets and "ee_service_account" in st.secrets["google"]:
                # Método Service Account
                service_account = st.secrets["google"]["ee_service_account"]
                key_data = st.secrets["google"]["ee_private_key"]
                
                credentials = ee.ServiceAccountCredentials(service_account, key_data=key_data)
                ee.Initialize(credentials)
                st.toast("✅ Google Earth Engine inicializado con Service Account")
            else:
                # Método de autenticación normal (para desarrollo)
                ee.Initialize(project='islas-calor-tabasco')
                st.toast("✅ Google Earth Engine inicializado")
            
            st.session_state.gee_available = True
            return True
            
        except Exception as e:
            st.error(f"❌ Error conectando con GEE: {str(e)}")
            st.session_state.gee_available = False
            return False
    return True

def cloudMaskFunction(image):
    qa = image.select("QA_PIXEL")
    cloud_mask = qa.bitwiseAnd(1 << 5)
    shadow_mask = qa.bitwiseAnd(1 << 3)
    combined_mask = cloud_mask.Or(shadow_mask).eq(0)
    return image.updateMask(combined_mask)

def noThermalDataFunction(image):
    st = image.select("ST_B10")
    valid = st.gt(0).And(st.lt(65535))
    return image.updateMask(valid)

def applyScale(image):
    opticalBands = image.select(["SR_B2", "SR_B3", "SR_B4"]).multiply(0.0000275).add(-0.2)
    return image.addBands(opticalBands, None, True)

# Método para agregar las imágenes de GEE a los mapas de folium
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        # display ee.Image()
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
            ).add_to(self)
        # display ee.ImageCollection()
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
        # display ee.Geometry()
        elif isinstance(ee_object, ee.geometry.Geometry):
            folium.GeoJson(
                data=ee_object.getInfo(), name=name, overlay=True, control=True
            ).add_to(self)
        # display ee.FeatureCollection()
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
        st.error(f"Error mostrando capa {name}: {str(e)}")

folium.Map.add_ee_layer = add_ee_layer

# Método para generar el mapa base
def create_map(center=None, zoom_start=13):
    if center is None:
        center = st.session_state.coordinates
    
    map = folium.Map(location=center, zoom_start=zoom_start)
    return map

def set_coordinates():
    """Establece las coordenadas basadas en la localidad seleccionada"""
    # Coordenadas aproximadas de las localidades de Tabasco
    coordinates_map = {
        "Balancán": (17.8086, -91.5364),
        "Cárdenas": (18.0014, -93.3756),
        "Frontera": (18.5431, -92.6453),
        "Villahermosa": (17.9892, -92.9281),
        "Comalcalco": (18.2639, -93.2236),
        "Cunduacán": (18.0656, -93.1731),
        "Emiliano Zapata": (17.7406, -91.7664),
        "Huimanguillo": (17.8339, -93.3886),
        "Jalapa": (17.7217, -92.8125),
        "Jalpa de Méndez": (18.1764, -93.0508),
        "Jonuta": (18.0892, -92.1381),
        "Macuspana": (17.7608, -92.5958),
        "Nacajuca": (18.1731, -92.9992),
        "Paraíso": (18.3964, -93.2142),
        "Tacotalpa": (17.6119, -92.8247),
        "Teapa": (17.5586, -92.9487),
        "Tenosique de Pino Suárez": (17.4742, -91.4236)
    }
    
    if st.session_state.locality in coordinates_map:
        st.session_state.coordinates = coordinates_map[st.session_state.locality]

# Método para mostrar el panel del mapa
def show_map_panel():
    st.markdown("Islas de calor por localidades de Tabasco")
    st.caption("Visualización de LST desde Google Earth Engine.")

    # Conectar con GEE primero
    if not connect_with_gee():
        st.error("No se pudo conectar con Google Earth Engine. Verifica las credenciales.")
        return

    map = create_map()
    if map is None:
        st.error("Error creando el mapa base")
        return

    # Add custom BASEMAPS
    BASEMAPS["Google Satellite Hybrid"].add_to(map)

    try:
        # Crear geometría rectangular alrededor de las coordenadas
        lat, lon = st.session_state.coordinates
        roi = ee.Geometry.Rectangle([
            lon - 0.05, lat - 0.05,  # SO
            lon + 0.05, lat + 0.05   # NE
        ])

        # Obtener colección de Landsat
        collection = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterDate(
                st.session_state.date_range[0].strftime("%Y-%m-%d"),
                st.session_state.date_range[1].strftime("%Y-%m-%d")
            )
            .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
            .filterBounds(roi)
            .map(cloudMaskFunction)
            .map(noThermalDataFunction)
        )

        # Verificar si hay imágenes disponibles
        image_count = collection.size().getInfo()
        if image_count == 0:
            st.warning("No se encontraron imágenes Landsat para el rango de fechas y área seleccionados.")
            # Mostrar mapa base sin capas GEE
            st_folium(map, width=None, height=600)
            return

        mosaico = collection.median().clip(roi)

        # Calcular LST en Celsius
        bandaTermica = mosaico.select("ST_B10")
        lstCelsius = bandaTermica.multiply(0.00341802).add(149.0).subtract(273.15).rename("LST_Celsius")

        visParamsLST = {
            "palette": ["blue", "cyan", "green", "yellow", "red"],
            "min": 28,
            "max": 48,
        }

        # Añadir capa LST al mapa
        map.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C)")

        # Detectar islas de calor (percentil 90)
        percentilUHI = 90
        lstForThreshold = lstCelsius.rename("LST")
        
        pctValue = lstForThreshold.reduceRegion(
            reducer=ee.Reducer.percentile([percentilUHI]),
            geometry=roi,
            scale=30,
            maxPixels=1e9
        ).get("LST").getInfo()

        uhiMask = lstForThreshold.gte(pctValue)
        uhiClean = uhiMask.selfMask()

        # Añadir capas de islas de calor
        map.add_ee_layer(
            uhiClean,
            {"palette": ["#d7301f"]},
            f"Islas de calor (>= p{percentilUHI})"
        )

        folium.LayerControl().add_to(map)

    except Exception as e:
        st.error(f"Error procesando datos de GEE: {str(e)}")

    st_folium(map, width=None, height=600)

# Configuración de streamlit
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# Configuración del sidebar
with st.sidebar:
    st.markdown("Islas de calor Tabasco")
    st.caption("Dashboard base para análisis de islas de calor urbano (LST/NDVI)")

    # Selector de sección
    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )
    st.session_state.window = section

    # Filtros globales
    st.markdown("Opciones")

    st.markdown("Área de estudio (localidad)")
    st.session_state.locality = st.selectbox(
        "Definir localidad",
        [
            "Balancán", "Cárdenas", "Frontera", "Villahermosa", "Comalcalco",
            "Cunduacán", "Emiliano Zapata", "Huimanguillo", "Jalapa", 
            "Jalpa de Méndez", "Jonuta", "Macuspana", "Nacajuca", "Paraíso",
            "Tacotalpa", "Teapa", "Tenosique de Pino Suárez"
        ],
    )

    set_coordinates()

    min_date, max_date = dt.date(2014, 1, 1), dt.datetime.now().date()
    date_range = st.date_input(
        "Rango de fechas",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
        help="Periodo de análisis",
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

# Router de las ventanas
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.write("Gráficas (placeholder)")
elif st.session_state.window == "Reportes":
    st.write("Reportes (placeholder)")
else:
    st.write("Acerca de (placeholder)")
