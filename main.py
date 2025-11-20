# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Corrección: Manejo robusto de secretos y clave privada
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

# Configuración de página
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# --- GESTIÓN DE ESTADO ---
if "locality" not in st.session_state:
    st.session_state.locality = "Teapa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = [17.558567, -92.948714]
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2023, 1, 1), dt.datetime.now().date())
if "gee_initialized" not in st.session_state:
    st.session_state.gee_initialized = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

MAX_NUBES = 30

# --- FUNCIONES GEE ---

def get_credentials_from_secrets():
    """
    Busca credenciales de servicio en varias ubicaciones posibles de st.secrets
    y corrige el formato de la clave privada si es necesario.
    """
    # 1. Buscar en la raíz (si se pegó el JSON directamente fuera de secciones)
    if "type" in st.secrets and st.secrets["type"] == "service_account":
        return dict(st.secrets)
    
    # 2. Buscar en secciones comunes
    posibles_secciones = ["gcp_service_account", "google", "gee", "credentials"]
    for seccion in posibles_secciones:
        if seccion in st.secrets:
            # A veces la sección contiene el JSON completo
            secret_data = st.secrets[seccion]
            # Verificar si tiene los campos clave
            if "client_email" in secret_data and "private_key" in secret_data:
                return dict(secret_data)
            # A veces el usuario anida: st.secrets["google"]["gee_api_key"]
            if "gee_api_key" in secret_data:
                return dict(secret_data["gee_api_key"])

    return None

def connect_with_gee():
    """Conecta con GEE usando Service Account de forma robusta."""
    if st.session_state.gee_initialized:
        return True

    try:
        secret_dict = get_credentials_from_secrets()

        if secret_dict:
            # --- CORRECCIÓN CRÍTICA DE CLAVE PRIVADA ---
            # Streamlit secrets a veces escapa los \n como \\n literal.
            # Esto lo revierte para que sea una clave RSA válida.
            if "private_key" in secret_dict:
                secret_dict["private_key"] = secret_dict["private_key"].replace("\\n", "\n")

            credentials = ee.ServiceAccountCredentials(
                email=secret_dict["client_email"],
                key_data=json.dumps(secret_dict)
            )
            ee.Initialize(credentials)
            st.session_state.gee_initialized = True
            st.toast("Conexión exitosa a Google Earth Engine", icon="✅")
            return True
        else:
            # Último intento: entorno local o autenticación preexistente
            try:
                ee.Initialize()
                st.session_state.gee_initialized = True
                return True
            except:
                pass
            
            st.error("⛔ No se encontraron credenciales válidas en st.secrets.")
            st.warning("""
            **Depuración:**
            El código buscó secciones como `[gcp_service_account]`, `[google]`, o `[gee]` en secrets.toml pero no halló las claves `client_email` y `private_key`.
            
            Asegúrate de que tu `secrets.toml` se vea así:
            ```toml
            [gcp_service_account]
            type = "service_account"
            project_id = "..."
            private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
            client_email = "..."
            ...
            ```
            """)
            return False

    except Exception as e:
        st.error(f"Error crítico conectando a GEE: {e}")
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

# Monkey-patch para Folium
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
        print(f"Error capa {name}: {e}")

folium.Map.add_ee_layer = add_ee_layer

# --- INTERFAZ DE USUARIO ---

def get_roi_and_coords():
    # Intentar leer asset ID de varias fuentes posibles
    asset_id = None
    if "env" in st.secrets and "GEE_LOCALITIES_ASSET" in st.secrets["env"]:
        asset_id = st.secrets["env"]["GEE_LOCALITIES_ASSET"]
    elif "GEE_LOCALITIES_ASSET" in os.environ:
        asset_id = os.environ["GEE_LOCALITIES_ASSET"]
    
    if not asset_id:
        st.warning("⚠️ 'GEE_LOCALITIES_ASSET' no configurado. Usando punto predeterminado.")
        return None

    try:
        fc = ee.FeatureCollection(asset_id)
        # Asegúrate que "NOMGEO" es la columna correcta en tu Shapefile/Asset
        roi = fc.filter(ee.Filter.eq("NOMGEO", st.session_state.locality)).geometry()
        
        # Forzar evaluación para verificar que existe
        info = roi.centroid().coordinates().getInfo() 
        st.session_state.coordinates = [info[1], info[0]] # Lat, Lon
        return roi
    except Exception as e:
        st.info(f"No se pudo cargar geometría exacta para {st.session_state.locality} (Revisa el Asset ID o nombre). Se usará vista general.")
        return None # Retorna None para manejarlo suavemente

def show_map_panel():
    st.markdown(f"### Análisis de Islas de Calor: {st.session_state.locality}")
    
    connected = connect_with_gee()
    
    # Mapa base
    m = folium.Map(location=st.session_state.coordinates, zoom_start=13)
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Hybrid",
        overlay=True,
        control=True
    ).add_to(m)

    if connected:
        with st.spinner("Consultando Earth Engine..."):
            roi = get_roi_and_coords()
            
            # Si hay ROI válida, centrar y procesar
            if roi:
                m.location = st.session_state.coordinates
                
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
                
                # Comprobación rápida
                if collection.size().getInfo() > 0:
                    mosaico = collection.median().clip(roi)
                    
                    # LST
                    bandaTermica = mosaico.select("ST_B10")
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
                    m.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C)")

                    # Cálculo de Hotspots
                    percentilUHI = 90
                    stats = lstCelsius.reduceRegion(
                        reducer=ee.Reducer.percentile([percentilUHI]),
                        geometry=roi,
                        scale=30,
                        maxPixels=1e9,
                        bestEffort=True
                    )
                    
                    val_umbral = stats.get("LST_Celsius")
                    # Validar si es nulo en el lado del cliente
                    if val_umbral is not None:
                        # Usar ee.Algorithms.If o casting seguro
                        # Pero como ya trajimos stats.get (que dispara getInfo implícitamente si imprimimos, pero aquí es objeto computed),
                        # Mejor usar server-side check:
                        umbral_num = ee.Number(val_umbral)
                        uhiMask = lstCelsius.gte(umbral_num)
                        
                        # Limpieza
                        compCount = uhiMask.connectedPixelCount(maxSize=128, eightConnected=True)
                        uhiClean = uhiMask.updateMask(compCount.gte(3)).selfMask()
                        
                        m.add_ee_layer(uhiClean, {"palette": ["#d7301f"]}, "Hotspots (> p90)")
                    
                    # Contorno
                    empty = ee.Image().byte()
                    outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
                    m.add_ee_layer(outline, {"palette": "black"}, "Límite")
                else:
                    st.warning("No se encontraron imágenes sin nubes en este periodo.")

    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=600)

# --- SIDEBAR ---

with st.sidebar:
    st.title("Tabasco Heat Watch 🔥")
    
    st.session_state.window = st.radio("Navegación", ["Mapas", "Gráficas", "Acerca de"])
    
    st.markdown("---")
    st.markdown("### Configuración")
    
    # Lista de prueba
    localidades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", 
        "Paraíso", "Frontera", "Macuspana", "Tenosique de Pino Suárez"
    ]
    
    st.session_state.locality = st.selectbox("Localidad", localidades, index=1)
    
    dates = st.date_input(
        "Rango de Análisis",
        value=st.session_state.date_range,
        min_value=dt.date(2014, 1, 1),
        max_value=dt.date.today()
    )
    if len(dates) == 2:
        st.session_state.date_range = dates

# --- ROUTER ---

if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Módulo de gráficas en desarrollo.")
else:
    st.markdown("### Acerca de\nMonitor de islas de calor urbano usando Landsat 8.")

