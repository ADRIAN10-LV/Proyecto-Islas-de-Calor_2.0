# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
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
    st.session_state.locality = "Teapa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.558567, -92.948714)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.datetime.now().date())
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
    """Conecta con Google Earth Engine usando Service Account de Streamlit Secrets"""
    if not st.session_state.get("gee_available", False):
        try:
            # Verificar si los secrets están configurados
            if "google" in st.secrets:
                # Opción 1: Formato con service account y private key
                if "ee_service_account" in st.secrets["google"] and "ee_private_key" in st.secrets["google"]:
                    service_account = st.secrets["google"]["ee_service_account"]
                    private_key = st.secrets["google"]["ee_private_key"]
                    
                    credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
                    ee.Initialize(credentials)
                    st.session_state.gee_available = True
                    st.success("✅ Google Earth Engine inicializado con Service Account")
                    return True
                
                # Opción 2: Formato con credenciales en JSON
                elif "gee_credentials" in st.secrets["google"]:
                    creds_dict = st.secrets["google"]["gee_credentials"]
                    credentials = ee.ServiceAccountCredentials.from_json_keyfile_dict(creds_dict)
                    ee.Initialize(credentials)
                    st.session_state.gee_available = True
                    st.success("✅ Google Earth Engine inicializado con credenciales JSON")
                    return True
                
                else:
                    st.error("""
                    ❌ Credenciales de GEE no encontradas en los secrets.
                    
                    Por favor, configura tus secrets en Streamlit Cloud con uno de estos formatos:
                    
                    **Formato 1:**
                    ```toml
                    [google]
                    ee_service_account = "tu-service-account@proyecto.iam.gserviceaccount.com"
                    ee_private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
                    ```
                    
                    **Formato 2:**
                    ```toml
                    [google]
                    gee_credentials = {"type": "service_account", "project_id": "...", "private_key_id": "...", ...}
                    ```
                    """)
                    return False
            else:
                st.error("No se encontró la sección 'google' en los secrets de Streamlit")
                return False
                
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
    st_band = image.select("ST_B10")
    valid = st_band.gt(0).And(st_band.lt(65535))
    return image.updateMask(valid)

# Método para agregar las imágenes de GEE a los mapas de folium
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
    except Exception as e:
        st.error(f"Error mostrando capa {name}: {str(e)}")

folium.Map.add_ee_layer = add_ee_layer

def create_map(center=None, zoom_start=13):
    if center is None:
        center = st.session_state.coordinates
    map = folium.Map(location=center, zoom_start=zoom_start)
    return map

def set_coordinates():
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

def show_map_panel():
    st.markdown("Islas de calor por localidades de Tabasco")
    st.caption("Visualización de LST desde Google Earth Engine.")

    # Intentar conectar con GEE
    if not connect_with_gee():
        # Mostrar mapa base sin GEE
        map = create_map()
        BASEMAPS["Google Satellite Hybrid"].add_to(map)
        st_folium(map, width=None, height=600)
        return

    map = create_map()
    BASEMAPS["Google Satellite Hybrid"].add_to(map)

    try:
        # Crear geometría rectangular
        lat, lon = st.session_state.coordinates
        roi = ee.Geometry.Rectangle([
            lon - 0.05, lat - 0.05,
            lon + 0.05, lat + 0.05
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

        image_count = collection.size().getInfo()
        if image_count == 0:
            st.warning("No se encontraron imágenes Landsat para el rango de fechas y área seleccionados.")
            st_folium(map, width=None, height=600)
            return

        mosaico = collection.median().clip(roi)

        # Calcular LST
        bandaTermica = mosaico.select("ST_B10")
        lstCelsius = bandaTermica.multiply(0.00341802).add(149.0).subtract(273.15).rename("LST_Celsius")

        visParamsLST = {
            "palette": ["blue", "cyan", "green", "yellow", "red"],
            "min": 28,
            "max": 48,
        }

        map.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C)")

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

    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )
    st.session_state.window = section

    st.markdown("Opciones")
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
