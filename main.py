# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: Conexión Directa (Compatible con tus Secrets actuales)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
from streamlit_folium import st_folium
from pathlib import Path
import os

# --- 1. CONFIGURACIÓN DE PÁGINA (Siempre va primero) ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# --- 2. GESTIÓN DE ESTADO ---
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

# --- 3. FUNCIONES DE CONEXIÓN ---
def connect_with_gee():
    """Conecta usando GEE_SERVICE_ACCOUNT y GEE_PRIVATE_KEY de tus secrets"""
    if st.session_state.gee_available:
        return True

    try:
        # Verificamos que las claves existan en los secretos
        if 'GEE_SERVICE_ACCOUNT' in st.secrets and 'GEE_PRIVATE_KEY' in st.secrets:
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            raw_key = st.secrets["GEE_PRIVATE_KEY"]
            
            # Limpieza de la clave (quita espacios extra y arregla saltos de línea)
            private_key = raw_key.strip()
            if '\\n' in private_key:
                private_key = private_key.replace('\\n', '\n')
                
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            
            st.session_state.gee_available = True
            st.toast("¡Conexión a Google Earth Engine exitosa!", icon="✅")
            return True
        else:
            # Si no encuentra las claves específicas, intenta inicialización local
            try:
                ee.Initialize()
                st.session_state.gee_available = True
                return True
            except:
                st.error("Faltan 'GEE_SERVICE_ACCOUNT' o 'GEE_PRIVATE_KEY' en secrets.toml")
                # Ayuda para depurar: Mostrar qué claves sí detecta (sin mostrar valores)
                st.caption(f"Claves detectadas en secrets: {list(st.secrets.keys())}")
                return False

    except Exception as e:
        st.error(f"Error de credenciales: {e}")
        st.session_state.gee_available = False
        return False

# --- 4. FUNCIONES DE PROCESAMIENTO GEE ---
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

# --- 5. INTEGRACIÓN FOLIUM ---
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
    except Exception as e:
        print(f"Error capa {name}: {e}")

folium.Map.add_ee_layer = add_ee_layer

def create_map():
    m = folium.Map(
        location=[st.session_state.coordinates[0], st.session_state.coordinates[1]], 
        zoom_start=13,
        height=500
    )
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite Hybrid",
        overlay=True,
        control=True
    ).add_to(m)
    return m

# --- 6. INTERFAZ DE USUARIO (PANELES) ---
def set_coordinates():
    coords = {
        "Villahermosa": (17.9895, -92.9183), "Teapa": (17.558567, -92.948714),
        "Cárdenas": (17.9869, -93.3750), "Comalcalco": (18.2631, -93.2119),
        "Paraíso": (18.3981, -93.2150), "Frontera": (18.5333, -92.65),
        "Macuspana": (17.7581, -92.5989), "Tenosique": (17.4742, -91.4269)
    }
    if st.session_state.locality in coords:
        st.session_state.coordinates = coords[st.session_state.locality]

def show_map_panel():
    st.markdown(f"### 🗺️ Monitor de Calor: {st.session_state.locality}")
    
    if not connect_with_gee():
        st.warning("No hay conexión a GEE. Mostrando mapa base.")
        m = create_map()
        st_folium(m, width="100%", height=600)
        return

    # Si conecta, procesamos:
    try:
        m = create_map()
        
        # 1. Definir ROI (Region of Interest)
        roi = None
        # Intentar obtener Asset si existe variable
        asset_id = st.secrets.get("env", {}).get("GEE_LOCALITIES_ASSET")
        if asset_id:
            try:
                fc = ee.FeatureCollection(asset_id)
                roi = fc.filter(ee.Filter.eq("NOMGEO", st.session_state.locality)).geometry()
                # Centrar mapa
                center = roi.centroid().coordinates().getInfo()
                m.location = [center[1], center[0]]
            except:
                pass
        
        # Fallback si no hay asset
        if not roi:
            lat, lon = st.session_state.coordinates
            roi = ee.Geometry.Point([lon, lat]).buffer(5000)

        # 2. Cargar Landsat 8
        start = st.session_state.date_range[0].strftime("%Y-%m-%d")
        end = st.session_state.date_range[1].strftime("%Y-%m-%d")
        
        col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
               .filterDate(start, end)
               .filterBounds(roi)
               .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
               .map(cloudMaskFunction)
               .map(noThermalDataFunction))

        if col.size().getInfo() > 0:
            img = col.median().clip(roi)
            
            # LST Celsius
            lst = (img.select("ST_B10").multiply(0.00341802)
                   .add(149.0).subtract(273.15).rename("LST_Celsius"))
            
            vis = {"min": 24, "max": 40, "palette": ["blue", "cyan", "green", "yellow", "red"]}
            m.add_ee_layer(lst, vis, "Temperatura (°C)")
            
            # Hotspots > P90
            stats = lst.reduceRegion(ee.Reducer.percentile([90]), roi, 30)
            p90 = stats.get("LST_Celsius")
            if p90:
                hotspots = lst.gte(ee.Number(p90)).selfMask()
                m.add_ee_layer(hotspots, {"palette": ["#d7301f"]}, "Puntos Calientes (>P90)")
        else:
            st.info(f"No se encontraron imágenes limpias para {st.session_state.locality} en estas fechas.")

        folium.LayerControl().add_to(m)
        st_folium(m, width="100%", height=600)

    except Exception as e:
        st.error(f"Error procesando mapa: {e}")

# --- 7. LAYOUT PRINCIPAL ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Info"])
    
    st.markdown("### Configuración")
    st.session_state.locality = st.selectbox("Municipio", 
        ["Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", "Frontera", "Macuspana", "Tenosique"])
    set_coordinates()
    
    fechas = st.date_input("Periodo", value=st.session_state.date_range)
    if len(fechas) == 2: st.session_state.date_range = fechas
    
    st.markdown("---")
    if st.button("Reconectar"):
        st.session_state.gee_available = False
        st.rerun()

if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Gráficas en construcción...")
else:
    st.markdown("### Acerca de\nMonitor de islas de calor urbano usando Landsat 8.")
