# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: Conexión GEE Blindada para cualquier formato de Secret
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import pandas as pd
import folium
from streamlit_folium import st_folium
from pathlib import Path
import os

# --- CONFIGURACIÓN DE PÁGINA (Debe ir AL PRINCIPIO) ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# Carpetas de trabajo (modificado para Streamlit Cloud)
BASE_DIR = Path(__file__).parent

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
    """Conexión simplificada y ROBUSTA para Streamlit Cloud"""
    # Si ya está conectado, no reintentar
    if st.session_state.gee_available:
        return True

    try:
        # Opción 1: Service Account desde Secrets
        if all(key in st.secrets for key in ['GEE_SERVICE_ACCOUNT', 'GEE_PRIVATE_KEY']):
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            
            # --- LÓGICA DE LIMPIEZA DE CLAVE ---
            # Esta sección ahora maneja tanto comillas triples (""") como una sola línea
            raw_key = st.secrets["GEE_PRIVATE_KEY"]
            
            # 1. Eliminar espacios en blanco al inicio/final (común en copy-paste)
            private_key = raw_key.strip()
            
            # 2. Si la clave tiene \n literales (es decir, caracteres escapados), los convertimos a saltos reales
            if '\\n' in private_key:
                private_key = private_key.replace('\\n', '\n')
            
            # 3. Asegurarnos que empiece y termine correctamente (si se cortó al copiar)
            if not private_key.startswith("-----BEGIN PRIVATE KEY-----"):
                st.error("La clave privada no tiene el formato correcto (Falta el encabezado BEGIN).")
                return False
                
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            st.toast("Conexión GEE Exitosa", icon="✅")
            return True
            
        # Opción 2: Inicialización estándar (Entorno local)
        else:
            ee.Initialize()
            st.session_state.gee_available = True
            return True

    except Exception as e:
        st.error(f"Error de conexión: {e}")
        st.warning("Revisa 'GEE_PRIVATE_KEY' en secrets.toml. Asegúrate que no tenga espacios extra al inicio.")
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
        # Mensaje silencioso en consola para no saturar la UI
        print(f"Error capa {name}: {e}")

# Asignar el método a Folium
folium.Map.add_ee_layer = add_ee_layer

def create_map(center=None, zoom_start=13):
    """Crea un mapa base Folium"""
    if center is None:
        center = st.session_state.coordinates
    
    map_obj = folium.Map(
        location=[center[0], center[1]], 
        zoom_start=zoom_start, 
        height=500
    )
    return map_obj

def set_coordinates():
    """Establece coordenadas basadas en la localidad"""
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
    """Panel de mapas"""
    st.markdown(f"## Islas de calor: {st.session_state.locality}")
    st.caption("Visualización de LST desde Google Earth Engine.")

    if not connect_with_gee():
        st.error("Error de credenciales. Revisa tus Secrets.")
        return

    map_obj = create_map()
    BASEMAPS["Google Satellite Hybrid"].add_to(map_obj)

    # --- Lógica GEE ---
    try:
        # 1. ROI (Región de interés)
        roi = None
        # Verificar si existe un Asset ID configurado
        asset_id = st.secrets.get("env", {}).get("GEE_LOCALITIES_ASSET")
        
        if asset_id:
            try:
                fc = ee.FeatureCollection(asset_id)
                roi = fc.filter(ee.Filter.eq("NOMGEO", st.session_state.locality)).geometry()
                # Centrado dinámico
                center_info = roi.centroid().coordinates().getInfo()
                map_obj.location = [center_info[1], center_info[0]]
            except Exception:
                # Si falla el asset, no detener la app
                pass
        
        # Fallback: Si no hay ROI del asset, usar un punto con buffer
        if not roi:
            lat, lon = st.session_state.coordinates
            roi = ee.Geometry.Point([lon, lat]).buffer(5000)

        # 2. Procesamiento de imágenes
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

        # Verificar si tenemos imágenes antes de procesar
        if collection.size().getInfo() > 0:
            mosaico = collection.median().clip(roi)
            bandaTermica = mosaico.select("ST_B10")
            
            # Kelvin a Celsius
            lstCelsius = (
                bandaTermica.multiply(0.00341802)
                .add(149.0)
                .subtract(273.15)
                .rename("LST_Celsius")
            )
            
            visParamsLST = {
                "palette": ["blue", "cyan", "green", "yellow", "red"],
                "min": 24, "max": 40,
            }
            
            map_obj.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C)")
            
            # Hotspots (Percentil 90)
            stats = lstCelsius.reduceRegion(
                reducer=ee.Reducer.percentile([90]),
                geometry=roi,
                scale=30,
                bestEffort=True
            )
            p90 = stats.get("LST_Celsius")
            
            # Validar que p90 no sea None
            if p90:
                val_p90 = ee.Number(p90)
                hotspots = lstCelsius.gte(val_p90).selfMask()
                map_obj.add_ee_layer(hotspots, {"palette": ["#d7301f"]}, "Hotspots (>P90)")
                
        else:
            st.warning(f"No se encontraron imágenes limpias entre {start_date} y {end_date} con <{MAX_NUBES}% nubes.")

    except Exception as e:
        st.error(f"Error en cálculo GEE: {e}")

    folium.LayerControl().add_to(map_obj)
    st_folium(map_obj, width="100%", height=600)

def show_graphics_panel():
    """Panel de gráficas"""
    st.markdown("### 🌡️ Análisis Estadístico")
    if not connect_with_gee():
        return
    st.info("🚧 Generación de gráficas temporales en construcción.")

# Sidebar
with st.sidebar:
    st.markdown("# Islas de calor Tabasco")
    
    section = st.radio("Secciones", ["Mapas", "Gráficas", "Acerca de"])
    st.session_state.window = section

    st.markdown("---")
    st.session_state.locality = st.selectbox(
        "Localidad",
        [
            "Balancán", "Cárdenas", "Frontera", "Villahermosa", "Comalcalco",
            "Cunduacán", "Emiliano Zapata", "Huimanguillo", "Jalapa",
            "Jalpa de Méndez", "Jonuta", "Macuspana", "Nacajuca", "Paraíso",
            "Tacotalpa", "Teapa", "Tenosique de Pino Suárez"
        ],
        index=15
    )

    set_coordinates()

    dates = st.date_input(
        "Rango de fechas",
        value=st.session_state.date_range,
        min_value=dt.date(2014, 1, 1),
        max_value=dt.date.today()
    )
    if isinstance(dates, tuple) and len(dates) == 2:
        st.session_state.date_range = dates

    st.markdown("---")
    if st.button("🔄 Reconectar"):
        st.session_state.gee_available = False
        st.rerun()

# Router
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    show_graphics_panel()
else:
    st.markdown("### Acerca de\nProyecto de monitoreo de islas de calor urbano usando Landsat 8 y GEE.")
