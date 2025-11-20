# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: Integración con Asset de Polígonos (areas_urbanas_Tab)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
from streamlit_folium import st_folium
from pathlib import Path

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# --- CONSTANTES ---
# Asset ID proporcionado por el usuario
ASSET_ID = "projects/ee-cando/assets/areas_urbanas_Tab"
MAX_NUBES = 30

# --- 2. GESTIÓN DE ESTADO ---
if "locality" not in st.session_state:
    st.session_state.locality = "Villahermosa" # Default
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.9895, -92.9183) # Default Villahermosa
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.date.today())
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# --- 3. CONEXIÓN GEE ---
def connect_with_gee():
    """Conecta usando Secrets"""
    if st.session_state.gee_available:
        return True

    try:
        if 'GEE_SERVICE_ACCOUNT' in st.secrets and 'GEE_PRIVATE_KEY' in st.secrets:
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            raw_key = st.secrets["GEE_PRIVATE_KEY"]
            private_key = raw_key.strip().replace('\\n', '\n')
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            st.toast("Conexión exitosa con GEE", icon="✅")
            return True
        else:
            # Intento local (fallback)
            ee.Initialize()
            st.session_state.gee_available = True
            return True
    except Exception as e:
        st.error(f"Error de conexión GEE: {e}")
        st.session_state.gee_available = False
        return False

# --- 4. FUNCIONES DE PROCESAMIENTO ---
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
        elif isinstance(ee_object, ee.geometry.Geometry) or isinstance(ee_object, ee.featurecollection.FeatureCollection):
            # Para geometrías, usamos GeoJson de Folium para que se vea el borde
            # Ojo: getInfo() puede ser pesado si la geometría es muy compleja, 
            # pero para polígonos urbanos suele estar bien.
            folium.GeoJson(
                data=ee_object.getInfo(),
                name=name,
                style_function=lambda x: {'color': 'black', 'fillColor': 'transparent', 'weight': 2},
                overlay=True, 
                control=True
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

# --- 6. LÓGICA PRINCIPAL DEL MAPA ---
def show_map_panel():
    st.markdown(f"### 🗺️ Análisis Urbano: {st.session_state.locality}")
    
    if not connect_with_gee():
        st.warning("Sin conexión a GEE.")
        return

    m = create_map()

    try:
        # 1. Obtener el POLÍGONO exacto del Asset
        # Cargamos la colección completa
        urban_areas = ee.FeatureCollection(ASSET_ID)
        
        # Filtramos por el nombre seleccionado (Columna NOMGEO)
        target_feature = urban_areas.filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
        
        # Verificamos si existe el polígono
        info_size = target_feature.size().getInfo()
        
        roi = None
        if info_size > 0:
            # Obtener geometría
            roi = target_feature.geometry()
            
            # Centrar el mapa en el polígono automáticamente
            centroid = roi.centroid().coordinates().getInfo()
            m.location = [centroid[1], centroid[0]] # Folium usa [Lat, Lon]
            
            # Dibujar el contorno del polígono en el mapa
            # Usamos paint() para convertir FeatureCollection a Imagen de bordes
            empty = ee.Image().byte()
            outline = empty.paint(
                featureCollection=target_feature,
                color=1,
                width=2
            )
            m.add_ee_layer(outline, {'palette': 'FF0000'}, "Límite Urbano")
            st.success(f"Polígono cargado: {st.session_state.locality}")
            
        else:
            st.error(f"No se encontró la ciudad '{st.session_state.locality}' en el asset '{ASSET_ID}'.")
            st.caption("Intenta seleccionar otra ciudad o verifica los nombres en la columna NOMGEO de tu asset.")
            # Fallback a punto central si falla
            roi = ee.Geometry.Point([st.session_state.coordinates[1], st.session_state.coordinates[0]]).buffer(3000)

        # 2. Procesar Imágenes SOLO dentro del ROI
        if roi:
            start = st.session_state.date_range[0].strftime("%Y-%m-%d")
            end = st.session_state.date_range[1].strftime("%Y-%m-%d")
            
            col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                   .filterDate(start, end)
                   .filterBounds(roi)  # Filtro espacial clave
                   .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                   .map(cloudMaskFunction)
                   .map(noThermalDataFunction))

            count = col.size().getInfo()
            if count > 0:
                # Reducir colección a una imagen (Mediana) y RECORTAR al polígono
                img = col.median().clip(roi)
                
                # Cálculo LST (Celsius)
                lst = (img.select("ST_B10").multiply(0.00341802)
                       .add(149.0).subtract(273.15).rename("LST_Celsius"))
                
                vis_params = {
                    "min": 24, 
                    "max": 42, 
                    "palette": ["blue", "cyan", "green", "yellow", "orange", "red"]
                }
                m.add_ee_layer(lst, vis_params, "Temperatura Superficial (°C)")
                
                # Hotspots: Zonas por encima del percentil 90 DE ESTE POLÍGONO
                stats = lst.reduceRegion(
                    reducer=ee.Reducer.percentile([90]),
                    geometry=roi,
                    scale=30,
                    bestEffort=True
                )
                p90 = stats.get("LST_Celsius")
                
                if p90:
                    val_p90 = ee.Number(p90)
                    hotspots = lst.gte(val_p90).selfMask()
                    m.add_ee_layer(hotspots, {"palette": ["black"]}, "Puntos Críticos (>P90)")
                    st.caption(f"🔥 Umbral de calor crítico calculado para esta zona: > {p90.getInfo():.1f}°C")
            else:
                st.warning("No se encontraron imágenes limpias en este periodo.")

    except Exception as e:
        st.error(f"Error procesando asset o GEE: {e}")

    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=600)

# --- 7. LAYOUT LATERAL ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Info"])
    
    st.markdown("### Selección de Zona")
    
    # LISTA DE MUNICIPIOS: 
    # IMPORTANTE: Estos nombres deben coincidir EXACTAMENTE con la columna NOMGEO de tu asset
    ciudades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", 
        "Paraíso", "Frontera", "Macuspana", "Tenosique",
        "Huimanguillo", "Cunduacán", "Jalpa de Méndez", 
        "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata", 
        "Jonuta", "Balancán"
    ]
    
    st.session_state.locality = st.selectbox("Ciudad / Localidad", ciudades, index=0)
    
    # Coordenadas base solo para centrado inicial (luego el asset las sobrescribe)
    # Diccionario simplificado para referencia rápida
    coords_base = {
        "Villahermosa": (17.98, -92.92),
        "Teapa": (17.55, -92.95)
    }
    if st.session_state.locality in coords_base:
        st.session_state.coordinates = coords_base[st.session_state.locality]
    
    fechas = st.date_input("Periodo de Análisis", value=st.session_state.date_range)
    if len(fechas) == 2: st.session_state.date_range = fechas
    
    st.markdown("---")
    if st.button("Recargar Conexión"):
        st.session_state.gee_available = False
        st.rerun()

if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Gráficas en desarrollo...")
else:
    st.markdown("### Acerca de\nAnálisis de LST usando polígonos urbanos oficiales.")
