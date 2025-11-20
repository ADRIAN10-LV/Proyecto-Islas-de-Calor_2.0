# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: LST Robusto + Análisis de Vegetación (NDVI p95)
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
    page_icon="🌱", # Cambiado a brote para reflejar vegetación
    layout="wide",
)

# --- CONSTANTES ---
ASSET_ID = "projects/ee-cando/assets/areas_urbanas_Tab"
MAX_NUBES = 30

# --- MAPAS BASE ---
BASEMAPS = {
    "Google Maps": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google", name="Google Maps", overlay=False, control=True,
    ),
    "Google Satellite": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google", name="Google Satellite", overlay=False, control=True,
    ),
    "Google Hybrid": folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google", name="Google Hybrid", overlay=False, control=True,
    ),
    "Esri Satellite": folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Esri Satellite", overlay=False, control=True,
    ),
}

# --- 2. GESTIÓN DE ESTADO ---
if "locality" not in st.session_state:
    st.session_state.locality = "Villahermosa"
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.9895, -92.9183)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 4, 1), dt.date(2024, 5, 30))
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# --- 3. CONEXIÓN GEE ---
def connect_with_gee():
    if st.session_state.gee_available: return True
    try:
        if 'GEE_SERVICE_ACCOUNT' in st.secrets and 'GEE_PRIVATE_KEY' in st.secrets:
            service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
            raw_key = st.secrets["GEE_PRIVATE_KEY"]
            private_key = raw_key.strip().replace('\\n', '\n')
            credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
            ee.Initialize(credentials)
            st.session_state.gee_available = True
            st.toast("Conexión GEE Establecida", icon="✅")
            return True
        else:
            ee.Initialize()
            st.session_state.gee_available = True
            return True
    except Exception as e:
        st.error(f"Error GEE: {e}")
        st.session_state.gee_available = False
        return False

# --- 4. FUNCIONES DE PROCESAMIENTO ---

def cloudMaskFunction(image):
    """Máscara de nubes Landsat 8"""
    qa = image.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 5).eq(0))
    return image.updateMask(mask)

def maskThermalNoData(image):
    """Limpieza banda térmica"""
    st_band = image.select("ST_B10")
    return image.updateMask(st_band.gt(0).And(st_band.lt(65535)))

def addNDVI(image):
    """Calcula NDVI y lo agrega como banda nueva"""
    ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    return image.addBands(ndvi)

# --- 5. INTEGRACIÓN FOLIUM ---
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine", name=name, overlay=True, control=True,
            ).add_to(self)
        elif isinstance(ee_object, ee.geometry.Geometry) or isinstance(ee_object, ee.featurecollection.FeatureCollection):
            folium.GeoJson(
                data=ee_object.getInfo(), name=name,
                style_function=lambda x: {'color': 'black', 'fillColor': 'transparent', 'weight': 2},
                overlay=True, control=True
            ).add_to(self)
    except Exception as e:
        print(f"Error capa {name}: {e}")

folium.Map.add_ee_layer = add_ee_layer

def create_map():
    m = folium.Map(
        location=[st.session_state.coordinates[0], st.session_state.coordinates[1]], 
        zoom_start=13, height=600, tiles=None
    )
    for name, layer in BASEMAPS.items():
        layer.add_to(m)
    return m

# --- 6. LÓGICA PRINCIPAL ---
def show_map_panel():
    st.markdown(f"### 🌿 Análisis Térmico y Vegetal: {st.session_state.locality}")
    
    if not connect_with_gee(): return
    m = create_map()

    try:
        # 1. ROI
        urban_areas = ee.FeatureCollection(ASSET_ID)
        target = urban_areas.filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
        
        roi = None
        if target.size().getInfo() > 0:
            roi = target.geometry()
            centroid = roi.centroid().coordinates().getInfo()
            m.location = [centroid[1], centroid[0]]
            
            # Contorno AOI
            empty = ee.Image().byte()
            outline = empty.paint(featureCollection=target, color=1, width=2)
            m.add_ee_layer(outline, {'palette': '000000'}, "Límite Urbano")
        else:
            st.error("Localidad no encontrada en Asset.")
            roi = ee.Geometry.Point([st.session_state.coordinates[1], st.session_state.coordinates[0]]).buffer(3000)

        if roi:
            start = st.session_state.date_range[0].strftime("%Y-%m-%d")
            end = st.session_state.date_range[1].strftime("%Y-%m-%d")
            
            # 2. Colección (LST + NDVI)
            col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                   .filterBounds(roi)
                   .filterDate(start, end)
                   .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                   .map(cloudMaskFunction)
                   .map(maskThermalNoData)
                   .map(addNDVI)) # <-- Agregamos cálculo NDVI aquí
            
            count = col.size().getInfo()
            if count > 0:
                # 3. Reducción (Percentil 50)
                # Genera bandas: 'ST_B10_p50', 'NDVI_p50', etc.
                mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
                
                # --- PROCESAMIENTO LST (CALOR) ---
                lst = (mosaic.select("ST_B10_p50")
                       .multiply(0.00341802).add(149.0).subtract(273.15).rename("LST"))
                
                # Capa LST
                vis_lst = {"min": 28, "max": 45, "palette": ['blue', 'cyan', 'yellow', 'red']}
                m.add_ee_layer(lst, vis_lst, "1. Temperatura Superficial (°C)")
                
                # Islas de Calor (> p90)
                p90_lst = lst.reduceRegion(ee.Reducer.percentile([90]), roi, 30).get("LST")
                if p90_lst:
                    val_p90 = ee.Number(p90_lst)
                    uhi_mask = lst.gte(val_p90)
                    # Limpieza 3px
                    uhi_clean = uhi_mask.updateMask(uhi_mask.connectedPixelCount(100, True).gte(3)).selfMask()
                    m.add_ee_layer(uhi_clean, {"palette": ['#d7301f']}, f"2. Islas de Calor (> {p90_lst.getInfo():.1f}°C)")

                # --- PROCESAMIENTO NDVI (VEGETACIÓN) ---
                ndvi = mosaic.select("NDVI_p50")
                
                # Capa NDVI General
                vis_ndvi = {"min": 0.0, "max": 0.6, "palette": ['brown', 'white', 'green']}
                m.add_ee_layer(ndvi, vis_ndvi, "3. Índice de Vegetación (NDVI)")
                
                # Zonas Más Verdes (> p95)
                # Calculamos el percentil 95 del NDVI dentro de la ciudad
                p95_ndvi = ndvi.reduceRegion(ee.Reducer.percentile([95]), roi, 30).get("NDVI_p50")
                
                if p95_ndvi:
                    val_p95_veg = ee.Number(p95_ndvi)
                    # Máscara: NDVI mayor o igual al top 5%
                    veg_mask = ndvi.gte(val_p95_veg).selfMask()
                    
                    # Capa de "Refugios Verdes" (Color Verde Neón)
                    m.add_ee_layer(veg_mask, {"palette": ['#00FF00']}, f"4. Refugios Verdes (Top 5% > {p95_ndvi.getInfo():.2f})")
                
                # --- MÉTRICAS EN PANTALLA ---
                st.success(f"Análisis basado en {count} imágenes.")
                c1, c2 = st.columns(2)
                c1.metric("🔥 Umbral Calor Crítico (p90)", f"{p90_lst.getInfo():.1f} °C")
                if p95_ndvi:
                    c2.metric("🌳 Umbral Alta Vegetación (p95)", f"{p95_ndvi.getInfo():.2f} NDVI")
                
            else:
                st.warning("Sin imágenes limpias en este periodo.")

    except Exception as e:
        st.error(f"Error: {e}")

    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=600)

# --- 7. SIDEBAR ---
with st.sidebar:
    st.title("🌱 Tabasco Heat & Green")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Info"])
    
    ciudades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", 
        "Frontera", "Macuspana", "Tenosique", "Huimanguillo", "Cunduacán", 
        "Jalpa de Méndez", "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata", 
        "Jonuta", "Balancán"
    ]
    st.session_state.locality = st.selectbox("Ciudad", ciudades)
    
    # Coordenadas referenciales
    coord_ref = {"Villahermosa": (17.98, -92.92), "Teapa": (17.55, -92.95)}
    if st.session_state.locality in coord_ref:
        st.session_state.coordinates = coord_ref[st.session_state.locality]
    
    st.caption("Periodo (Sug.: Abril-Mayo)")
    fechas = st.date_input("Fechas", value=st.session_state.date_range)
    if len(fechas) == 2: st.session_state.date_range = fechas
    
    st.markdown("---")
    if st.button("🔄 Recargar"):
        st.session_state.gee_available = False
        st.rerun()

# --- 8. ROUTER ---
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    st.info("Próximamente: Correlación LST vs NDVI")
else:
    st.markdown("### Acerca de\nAnálisis cruzado de Islas de Calor y Cobertura Vegetal.")
