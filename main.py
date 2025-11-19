# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Autor: Adrian Lara (estructura base generada con ayuda de IA)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import pandas as pd
import folium
from streamlit_folium import st_folium
from pathlib import Path

# Eliminé estas importaciones problemáticas para Streamlit Cloud:
# import sys
# import os
# import matplotlib.pyplot as plt
# from dotenv import load_dotenv

# Carpetas de trabajo (modificado para Streamlit Cloud)
BASE_DIR = Path(__file__).parent
# En Streamlit Cloud no podemos crear directorios, así que comentamos esto:
# DATA_DIR = BASE_DIR / "data"
# REPORTS_DIR = DATA_DIR / "reports"
# TEMP_DIR = DATA_DIR / "temp"
# for d in (DATA_DIR, REPORTS_DIR, TEMP_DIR):
#     d.mkdir(parents=True, exist_ok=True)

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
    """Conexión simplificada para Streamlit Cloud"""
    try:
        # Opción 1: Service Account desde Secrets
        if all(key in st.secrets for key in ['GEE_SERVICE_ACCOUNT', 'GEE_PRIVATE_KEY']):
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            private_key = st.secrets["GEE_PRIVATE_KEY"].replace('\\n', '\n')
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            return True
    except Exception as e:
        st.warning(f"Service Account no disponible: {e}")
    
    # Opción 2: Inicialización estándar
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
    """Método para agregar capas de GEE a Folium - CORREGIDO"""
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

def create_map(center=None, zoom_start=13):
    """Crea un mapa base Folium - CORREGIDO"""
    if center is None:
        center = st.session_state.coordinates
    
    map_obj = folium.Map(
        location=[center[0], center[1]], 
        zoom_start=zoom_start, 
        height=500
    )
    return map_obj

def set_coordinates():
    """Función simplificada - las coordenadas ya están definidas"""
    # En Streamlit Cloud mantenemos coordenadas fijas por simplicidad
    coordenadas_ciudades = {
        "Balancán": (17.8, -91.5333),
        "Cárdenas": (17.9869, -93.3750),
        "Frontera": (18.5333, -92.65),
        "Villahermosa": (17.9895, -92.9183),
        "Comalcalco": (18.2631, -93.2119),
        "Cunduacán": (18.0656, -93.1731),
        "Emiliano Zapata": (17.7406, -91.7669),
        "Huimanguillo": (17.8333, -93.3892),
        "Jalapa": (17.7219, -92.8125),
        "Jalpa de Méndez": (18.1764, -93.0631),
        "Jonuta": (18.0897, -92.1381),
        "Macuspana": (17.7581, -92.5989),
        "Nacajuca": (18.0653, -93.0172),
        "Paraíso": (18.3981, -93.2150),
        "Tacotalpa": (17.5833, -92.8167),
        "Teapa": (17.558567, -92.948714),
        "Tenosique de Pino Suárez": (17.4742, -91.4269)
    }
    
    if st.session_state.locality in coordenadas_ciudades:
        st.session_state.coordinates = coordenadas_ciudades[st.session_state.locality]

def show_map_panel():
    """Panel de mapas - CORREGIDO para Streamlit Cloud"""
    st.markdown("## Islas de calor por localidades de Tabasco")
    st.caption("Visualización de LST desde Google Earth Engine.")

    if not connect_with_gee():
        st.error("No se pudo conectar con Google Earth Engine")
        return

    map_obj = create_map()
    if map_obj is None:
        st.error("Error al crear el mapa")
        return

    # Agregar base map
    BASEMAPS["Google Satellite Hybrid"].add_to(map_obj)

    # Mostrar mensaje informativo
    st.info(f"🗺️ Visualizando: {st.session_state.locality}")
    
    # Aquí puedes agregar gradualmente las funcionalidades de GEE
    # una vez que la conexión esté funcionando
    
    st_folium(map_obj, width=None, height=600)

def show_graphics_panel():
    """Panel de gráficas - CORREGIDO para funcionamiento básico"""
    st.markdown("### 🌡️ Análisis de Temperatura Superficial (LST)")
    st.caption(
        f"Localidad seleccionada: **{st.session_state.locality}** | "
        f"Periodo: {st.session_state.date_range[0]} — {st.session_state.date_range[1]}"
    )

    if not connect_with_gee():
        st.error("No se pudo conectar con Google Earth Engine.")
        return

    # Mostrar interfaz básica mientras se implementa la funcionalidad completa
    st.warning("🚧 Funcionalidad en desarrollo")
    st.info("""
    **Próximamente:**
    - Gráficas de evolución temporal de LST
    - Comparación entre municipios
    - Análisis de tendencias
    """)
    
    # Placeholder para futura implementación
    tipo_grafica = st.radio(
        "Tipo de gráfica:",
        ["Evolución temporal", "Comparación entre municipios"],
        horizontal=True,
    )
    
    if st.button("Generar gráfica de ejemplo"):
        # Datos de ejemplo
        data = {
            'Año': [2018, 2019, 2020, 2021, 2022, 2023, 2024],
            'LST_media': [28.5, 29.1, 29.8, 30.2, 29.9, 30.5, 31.2]
        }
        df = pd.DataFrame(data)
        st.line_chart(df, x='Año', y='LST_media')
        st.caption("Gráfica de ejemplo - Datos simulados")

# Configuración de Streamlit
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# Sidebar
with st.sidebar:
    st.markdown("# Islas de calor Tabasco")
    st.caption("Dashboard para análisis de islas de calor urbano (LST)")

    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )
    st.session_state.window = section

    st.markdown("---")
    st.markdown("### Opciones")

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
        "Rango de fechas",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    st.markdown("---")
    if st.button("🔗 Conectar con Google Earth Engine", type="secondary"):
        connect_with_gee()
        st.rerun()

# Router principal
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    show_graphics_panel()
elif st.session_state.window == "Reportes":
    st.markdown("## 📊 Reportes")
    st.info("Módulo de reportes en desarrollo")
elif st.session_state.window == "Acerca de":
    st.markdown("## ℹ️ Acerca de")
    st.write("""
    **Dashboard para análisis de Islas de Calor Urbano en Tabasco**
    
    Desarrollado para el monitoreo de temperaturas superficiales (LST) 
    usando Google Earth Engine y Streamlit.
    
    *Autor: Adrian Lara*
    """)

