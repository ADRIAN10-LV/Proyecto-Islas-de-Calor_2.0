# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: Mapas Base + Gráficos Estadísticos (Altair)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
import pandas as pd
import altair as alt
from streamlit_folium import st_folium
from pathlib import Path

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="📊",
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
    qa = image.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 5).eq(0))
    return image.updateMask(mask)

def maskThermalNoData(image):
    st_band = image.select("ST_B10")
    return image.updateMask(st_band.gt(0).And(st_band.lt(65535)))

def addNDVI(image):
    ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    return image.addBands(ndvi)

def addLST(image):
    lst = (image.select("ST_B10")
           .multiply(0.00341802).add(149.0).subtract(273.15).rename("LST"))
    return image.addBands(lst)

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
        zoom_start=13, height=500, tiles=None
    )
    for name, layer in BASEMAPS.items():
        layer.add_to(m)
    return m

# --- HELPER: OBTENER ROI ---
def get_roi():
    urban_areas = ee.FeatureCollection(ASSET_ID)
    target = urban_areas.filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
    if target.size().getInfo() > 0:
        return target.geometry()
    return None

# --- 6. PANELES PRINCIPALES ---

def show_map_panel():
    st.markdown(f"### 🗺️ Monitor Urbano: {st.session_state.locality}")
    if not connect_with_gee(): return
    
    m = create_map()
    roi = get_roi()

    if roi:
        centroid = roi.centroid().coordinates().getInfo()
        m.location = [centroid[1], centroid[0]]
        
        # Contorno
        empty = ee.Image().byte()
        outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
        m.add_ee_layer(outline, {'palette': '000000'}, "Límite Urbano")

        start = st.session_state.date_range[0].strftime("%Y-%m-%d")
        end = st.session_state.date_range[1].strftime("%Y-%m-%d")
        
        col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
               .filterBounds(roi).filterDate(start, end)
               .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
               .map(cloudMaskFunction).map(maskThermalNoData).map(addNDVI).map(addLST))
        
        if col.size().getInfo() > 0:
            mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
            
            # Capas Visuales (Usamos nombres de bandas reducidas _p50)
            lst_band = mosaic.select("LST_p50")
            ndvi_band = mosaic.select("NDVI_p50")
            
            m.add_ee_layer(lst_band, {"min": 28, "max": 45, "palette": ['blue', 'cyan', 'yellow', 'red']}, "1. LST (°C)")
            m.add_ee_layer(ndvi_band, {"min": 0, "max": 0.6, "palette": ['brown', 'white', 'green']}, "2. NDVI")
            
            # UHI > p90
            p90 = lst_band.reduceRegion(ee.Reducer.percentile([90]), roi, 30).get("LST_p50")
            if p90:
                val_p90 = ee.Number(p90)
                uhi = lst_band.gte(val_p90)
                uhi_clean = uhi.updateMask(uhi.connectedPixelCount(100, True).gte(3)).selfMask()
                m.add_ee_layer(uhi_clean, {"palette": ['#d7301f']}, f"3. Hotspots (> {p90.getInfo():.1f}°C)")
        else:
            st.warning("Sin imágenes limpias.")
            
    else:
        st.error("Localidad no encontrada.")

    folium.LayerControl().add_to(m)
    st_folium(m, width="100%", height=600)


def show_graphics_panel():
    st.markdown(f"### 📊 Análisis Estadístico: {st.session_state.locality}")
    if not connect_with_gee(): return

    roi = get_roi()
    if not roi:
        st.error("Localidad no encontrada.")
        return

    start = st.session_state.date_range[0].strftime("%Y-%m-%d")
    end = st.session_state.date_range[1].strftime("%Y-%m-%d")

    with st.spinner("Calculando estadísticas espaciales y temporales... (Esto puede tardar unos segundos)"):
        # Preparar colección
        col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
               .filterBounds(roi).filterDate(start, end)
               .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
               .map(cloudMaskFunction).map(maskThermalNoData).map(addNDVI).map(addLST))
        
        count = col.size().getInfo()
        if count == 0:
            st.warning("No hay datos suficientes para generar gráficas.")
            return

        # 1. GRÁFICA DE DISPERSIÓN (LST vs NDVI)
        # Muestreamos la imagen compuesta (mediana) para ver la correlación espacial
        mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
        
        # Extraemos 1000 puntos aleatorios dentro de la ciudad
        sample = mosaic.select(["LST_p50", "NDVI_p50"]).sample(
            region=roi, scale=30, numPixels=1000, geometries=False
        )
        
        # Convertimos a DataFrame (Client-side)
        data_points = sample.getInfo()['features']
        if data_points:
            df_scatter = pd.DataFrame([x['properties'] for x in data_points])
            df_scatter.columns = ["LST (°C)", "NDVI"] # Renombrar para el gráfico
            
            # Altair Scatter Plot
            scatter_chart = alt.Chart(df_scatter).mark_circle(size=60, opacity=0.5).encode(
                x=alt.X('NDVI', title='Índice de Vegetación (NDVI)'),
                y=alt.Y('LST (°C)', title='Temperatura Superficial (°C)', scale=alt.Scale(zero=False)),
                color=alt.Color('LST (°C)', scale=alt.Scale(scheme='turbo')),
                tooltip=['NDVI', 'LST (°C)']
            ).properties(
                title="Correlación: Vegetación vs. Calor",
                height=400
            ).interactive()
            
            st.altair_chart(scatter_chart, use_container_width=True)
            
            # Correlación simple
            corr = df_scatter['LST (°C)'].corr(df_scatter['NDVI'])
            st.info(f"📉 **Coeficiente de Correlación:** {corr:.2f} (Un valor cercano a -1 indica que más árboles reducen significativamente el calor).")

        st.markdown("---")

        # 2. SERIE DE TIEMPO (Evolución LST)
        # Función para reducir cada imagen a un valor promedio
        def get_mean_lst(img):
            mean = img.reduceRegion(ee.Reducer.mean(), roi, 100).get("LST")
            date = img.date().format("YYYY-MM-dd")
            return ee.Feature(None, {'date': date, 'LST_mean': mean})
        
        # Mapeamos sobre la colección original (sin reducir)
        time_series = col.map(get_mean_lst).filter(ee.Filter.notNull(['LST_mean']))
        
        ts_info = time_series.getInfo()
        if ts_info['features']:
            df_ts = pd.DataFrame([x['properties'] for x in ts_info['features']])
            df_ts['date'] = pd.to_datetime(df_ts['date'])
            
            line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                x=alt.X('date', title='Fecha'),
                y=alt.Y('LST_mean', title='LST Promedio (°C)', scale=alt.Scale(zero=False)),
                tooltip=['date', 'LST_mean']
            ).properties(
                title="Evolución Temporal de la Temperatura Promedio",
                height=350
            ).interactive()
            
            st.altair_chart(line_chart, use_container_width=True)
        
        st.markdown("---")
        
        # 3. HISTOGRAMA (Distribución de Calor)
        if data_points: # Reutilizamos los puntos muestreados para el histograma
            hist_chart = alt.Chart(df_scatter).mark_bar().encode(
                x=alt.X('LST (°C)', bin=alt.Bin(maxbins=20), title='Rango de Temperatura'),
                y=alt.Y('count()', title='Frecuencia (Píxeles)'),
                color=alt.value('orange')
            ).properties(
                title="Distribución de Temperaturas en la Ciudad",
                height=300
            )
            st.altair_chart(hist_chart, use_container_width=True)


# --- 7. SIDEBAR ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Info"])
    
    ciudades = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", 
        "Frontera", "Macuspana", "Tenosique", "Huimanguillo", "Cunduacán", 
        "Jalpa de Méndez", "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata", 
        "Jonuta", "Balancán"
    ]
    st.session_state.locality = st.selectbox("Ciudad", ciudades)
    
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
    show_graphics_panel()
else:
    st.markdown("### Acerca de\nPlataforma de análisis geoespacial de Islas de Calor Urbano en Tabasco.")
