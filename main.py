# --------------------------------------------------------------
# main.py — Streamlit para Islas de Calor Urbano (ICU)
# Versión: Mapas Base
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
from streamlit_folium import st_folium
from pathlib import Path

# --- 1. CONFIGURACIÓN DE PÁGINA (Debe ir primero) ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)

# --- CONSTANTES ---
ASSET_ID = "projects/ee-cando/assets/areas_urbanas_Tab"
MAX_NUBES = 30

# --- MAPAS BASE ---
# Definimos las capas base con overlay=False para que sean mutuamente excluyentes
BASEMAPS = {
    "Google Maps": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Maps",
        overlay=False,
        control=True,
    ),
    "Google Satellite": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite",
        overlay=False,
        control=True,
    ),
    "Google Terrain": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Terrain",
        overlay=False,
        control=True,
    ),
    "Google Satellite Hybrid": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Hybrid",
        overlay=False,
        control=True,
    ),
    "Esri Satellite": folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Satellite",
        overlay=False,
        control=True,
    ),
}

# --- 2. GESTIÓN DE ESTADO ---
if "locality" not in st.session_state:
    st.session_state.locality = "Villahermosa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.9895, -92.9183)
if "date_range" not in st.session_state:
    # Default: Época seca/cálida (Abril-Mayo)
    st.session_state.date_range = (dt.date(2024, 4, 1), dt.date(2024, 5, 30))
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# --- 3. CONEXIÓN GEE ---
def connect_with_gee():
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
    cloud_shadow_bit_mask = (1 << 3)
    cloud_bit_mask = (1 << 5)
    mask = qa.bitwiseAnd(cloud_shadow_bit_mask).eq(0).And(
           qa.bitwiseAnd(cloud_bit_mask).eq(0))
    return image.updateMask(mask)

def maskThermalNoData(image):
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
    """Crea el mapa base e inyecta todas las opciones de BASEMAPS"""
    m = folium.Map(
        location=[st.session_state.coordinates[0], st.session_state.coordinates[1]], 
        zoom_start=13,
        height=500,
        tiles=None # Desactivar OSM por defecto para usar los nuestros
    )
    
    # Agregar todas las capas base definidas arriba
    for name, layer in BASEMAPS.items():
        layer.add_to(m)
        
    return m

# --- 6. LÓGICA PRINCIPAL DEL MAPA ---
def show_map_panel():
    st.markdown(f"### 🗺️ Análisis Urbano Robusto: {st.session_state.locality}")
    st.caption("Algoritmo: Landsat 8 C2 L2 | Reducción Percentil 50 | Limpieza Morfológica")
    
    if not connect_with_gee():
        st.warning("Sin conexión a GEE.")
        return

    m = create_map()

    try:
        # 1. Obtener Polígono del Asset
        urban_areas = ee.FeatureCollection(ASSET_ID)
        target_feature = urban_areas.filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
        
        roi = None
        if target_feature.size().getInfo() > 0:
            roi = target_feature.geometry()
            centroid = roi.centroid().coordinates().getInfo()
            m.location = [centroid[1], centroid[0]]
            
            # Visualizar borde AOI en Rojo
            empty = ee.Image().byte()
            outline = empty.paint(featureCollection=target_feature, color=1, width=2)
            m.add_ee_layer(outline, {'palette': 'FF0000'}, f"AOI: {st.session_state.locality}")
        else:
            st.error(f"Localidad '{st.session_state.locality}' no encontrada en el Asset.")
            st.info("Usando punto central por defecto.")
            roi = ee.Geometry.Point([st.session_state.coordinates[1], st.session_state.coordinates[0]]).buffer(3000)

        if roi:
            # 2. Parámetros
            start = st.session_state.date_range[0].strftime("%Y-%m-%d")
            end = st.session_state.date_range[1].strftime("%Y-%m-%d")
            
            # 3. Colección y Proceso
            col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                   .filterBounds(roi)
                   .filterDate(start, end)
                   .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                   .map(cloudMaskFunction)
                   .map(maskThermalNoData))
            
            count = col.size().getInfo()
            if count > 0:
                st.success(f"✅ Procesando {count} imágenes válidas.")
                
                # 4. Reducción Percentil 50
                mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
                
                # 5. LST
                thermal_band = mosaic.select("ST_B10_p50")
                lst_celsius = (thermal_band.multiply(0.00341802)
                               .add(149.0).subtract(273.15).rename("LST_Celsius"))
                
                # Visualización LST
                vis_params = {
                    "min": 28, "max": 48, 
                    "palette": ['blue', 'cyan', 'green', 'yellow', 'red']
                }
                m.add_ee_layer(lst_celsius, vis_params, "Temperatura Superficial (°C) p50")
                
                # 6. UHI (Islas de Calor)
                percentile_uhi = 90
                stats = lst_celsius.reduceRegion(
                    reducer=ee.Reducer.percentile([percentile_uhi]),
                    geometry=roi, scale=30, maxPixels=1e9, bestEffort=True
                )
                
                p90_val = stats.get("LST_Celsius")
                
                if p90_val:
                    umbral = ee.Number(p90_val)
                    uhi_mask = lst_celsius.gte(umbral)
                    
                    # Limpieza (connectedPixelCount)
                    min_pix_parche = 3
                    comp_count = uhi_mask.connectedPixelCount(maxSize=1024, eightConnected=True)
                    uhi_clean = uhi_mask.updateMask(comp_count.gte(min_pix_parche)).selfMask()
                    
                    m.add_ee_layer(uhi_clean, {"palette": ['#d7301f']}, f"Islas de Calor (≥ {p90_val.getInfo():.1f}°C)")
                    st.metric(label="Umbral Crítico (p90)", value=f"{p90_val.getInfo():.2f} °C")
                
            else:
                st.warning("No hay imágenes limpias en este rango.")

    except Exception as e:
        st.error(f"Error en procesamiento: {e}")

    # Añadimos el control de capas al final para que detecte tanto los basemaps como las capas GEE
    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=600)

# --- 7. SIDEBAR ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Info"])
    
    st.markdown("### Selección de Zona")
    ciudades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", 
        "Paraíso", "Frontera", "Macuspana", "Tenosique",
        "Huimanguillo", "Cunduacán", "Jalpa de Méndez", 
        "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata", 
        "Jonuta", "Balancán"
    ]
    st.session_state.locality = st.selectbox("Ciudad / Localidad", ciudades, index=0)
    
    coords_base = {"Villahermosa": (17.98, -92.92), "Teapa": (17.55, -92.95)}
    if st.session_state.locality in coords_base:
        st.session_state.coordinates = coords_base[st.session_state.locality]
    
    st.caption("Sugerencia: Abril-Mayo (Época Seca).")
    fechas = st.date_input("Periodo de Análisis", value=st.session_state.date_range)
    if len(fechas) == 2: st.session_state.date_range = fechas
    
    st.markdown("---")
    if st.button("Recargar Conexión"):
        st.session_state.gee_available = False
        st.rerun()

# --- 8. ROUTER ---
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Gráficas en desarrollo...")
else:
    st.markdown("### Acerca de\nAnálisis robusto de LST usando limpieza morfológica y percentiles.")
