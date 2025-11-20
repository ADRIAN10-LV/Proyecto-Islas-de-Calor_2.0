# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: Mapas Base + Gráficos + COMPARADOR (2 Ciudades)
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
    page_icon="⚖️", # Icono de balanza para comparación
    layout="wide",
)

# --- CONSTANTES ---
ASSET_ID = "projects/ee-cando/assets/areas_urbanas_Tab"
MAX_NUBES = 30

# --- MAPAS BASE ---
BASEMAPS = {
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
# Estado para el comparador
if "compare_cities" not in st.session_state:
    st.session_state.compare_cities = ["Villahermosa", "Teapa"]

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

def create_map(center=None):
    location = center if center else [st.session_state.coordinates[0], st.session_state.coordinates[1]]
    m = folium.Map(location=location, zoom_start=12, height=400, tiles=None)
    BASEMAPS["Google Hybrid"].add_to(m)
    return m

# --- HELPER: OBTENER ROI ---
def get_roi(locality_name):
    urban_areas = ee.FeatureCollection(ASSET_ID)
    target = urban_areas.filter(ee.Filter.eq("NOMGEO", locality_name))
    if target.size().getInfo() > 0:
        return target.geometry()
    return None

# --- 6. PANELES PRINCIPALES ---

def show_map_panel():
    st.markdown(f"### 🗺️ Monitor Urbano: {st.session_state.locality}")
    if not connect_with_gee(): return
    
    roi = get_roi(st.session_state.locality)

    if roi:
        m = create_map()
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
            
            # Capas Visuales
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
        
        folium.LayerControl().add_to(m)
        st_folium(m, width="100%", height=600)
    else:
        st.error("Localidad no encontrada.")


def show_graphics_panel():
    st.markdown(f"### 📊 Análisis Estadístico: {st.session_state.locality}")
    if not connect_with_gee(): return
    roi = get_roi(st.session_state.locality)
    if not roi: return

    start = st.session_state.date_range[0].strftime("%Y-%m-%d")
    end = st.session_state.date_range[1].strftime("%Y-%m-%d")

    col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterBounds(roi).filterDate(start, end)
            .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
            .map(cloudMaskFunction).map(maskThermalNoData).map(addLST).map(addNDVI))
    
    if col.size().getInfo() == 0:
        st.warning("No hay datos suficientes.")
        return

    # 1. Scatter
    mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
    sample = mosaic.select(["LST_p50", "NDVI_p50"]).sample(region=roi, scale=30, numPixels=1000, geometries=False)
    data = sample.getInfo()['features']
    if data:
        df = pd.DataFrame([x['properties'] for x in data])
        chart = alt.Chart(df).mark_circle(size=60).encode(
            x='NDVI_p50', y='LST_p50', color=alt.Color('LST_p50', scale=alt.Scale(scheme='turbo'))
        ).properties(title="Correlación LST vs NDVI").interactive()
        st.altair_chart(chart, use_container_width=True)


# --- 7. NUEVO PANEL: COMPARATIVA ---
def show_comparison_panel():
    st.markdown("### ⚖️ Comparativa de Ciudades")
    if not connect_with_gee(): return

    # 1. Selector Múltiple
    ciudades_disp = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", 
        "Frontera", "Macuspana", "Tenosique", "Huimanguillo", "Cunduacán", 
        "Jalpa de Méndez", "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata"
    ]
    
    selected = st.multiselect(
        "Selecciona 2 ciudades para comparar:", 
        ciudades_disp, 
        default=st.session_state.compare_cities[:2],
        max_selections=2
    )

    if len(selected) != 2:
        st.info("Por favor selecciona exactamente 2 ciudades para iniciar la comparación.")
        return

    start = st.session_state.date_range[0].strftime("%Y-%m-%d")
    end = st.session_state.date_range[1].strftime("%Y-%m-%d")
    
    # Contenedores de datos para graficar luego
    stats_data = []
    timeseries_data = []

    # Layout de Mapas (Columnas)
    c1, c2 = st.columns(2)
    cols = [c1, c2]

    for idx, city in enumerate(selected):
        with cols[idx]:
            st.subheader(f"📍 {city}")
            roi = get_roi(city)
            
            if roi:
                # Procesamiento Express
                col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                       .filterBounds(roi).filterDate(start, end)
                       .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                       .map(cloudMaskFunction).map(maskThermalNoData).map(addLST))
                
                if col.size().getInfo() > 0:
                    # MAPA
                    mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
                    lst = mosaic.select("LST_p50")
                    
                    # Estadísticas Globales
                    stats = lst.reduceRegion(
                        reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.max(), sharedInputs=True),
                        geometry=roi, scale=100, bestEffort=True
                    ).getInfo()
                    
                    stats_data.append({
                        "Ciudad": city,
                        "LST Promedio (°C)": stats.get("LST_p50_mean"),
                        "LST Máxima (°C)": stats.get("LST_p50_max")
                    })
                    
                    # Crear Mapa Miniatura
                    centroid = roi.centroid().coordinates().getInfo()
                    m = create_map(center=[centroid[1], centroid[0]])
                    # Estandarizamos visualización para comparar peras con peras
                    vis_params = {"min": 28, "max": 42, "palette": ['blue', 'cyan', 'yellow', 'red']}
                    m.add_ee_layer(lst, vis_params, "Temperatura")
                    
                    # Borde
                    empty = ee.Image().byte()
                    outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
                    m.add_ee_layer(outline, {'palette': 'black'}, "Límite")
                    
                    st_folium(m, width="100%", height=350, key=f"map_{city}")
                    
                    # Datos para serie de tiempo (Simplificado)
                    def get_ts(img):
                        mean_val = img.reduceRegion(ee.Reducer.mean(), roi, 200).get("LST")
                        return ee.Feature(None, {'date': img.date().format("YYYY-MM-dd"), 'val': mean_val, 'city': city})
                    
                    ts_feats = col.map(get_ts).filter(ee.Filter.notNull(['val'])).getInfo()['features']
                    for f in ts_feats:
                        timeseries_data.append(f['properties'])

                else:
                    st.warning("Sin datos para este periodo.")
            else:
                st.error("Geometría no encontrada.")

    st.markdown("---")
    st.subheader("📊 Gráficos Comparativos")

    if stats_data:
        df_stats = pd.DataFrame(stats_data)
        df_ts = pd.DataFrame(timeseries_data)
        
        gc1, gc2 = st.columns(2)
        
        with gc1:
            st.markdown("**Comparativa de Temperaturas**")
            # Transformar para gráfico agrupado
            df_melt = df_stats.melt("Ciudad", var_name="Métrica", value_name="Temperatura")
            
            bar_chart = alt.Chart(df_melt).mark_bar().encode(
                x=alt.X('Métrica', axis=None),
                y=alt.Y('Temperatura', title='Grados Celsius'),
                color='Métrica',
                column='Ciudad',
                tooltip=['Ciudad', 'Métrica', alt.Tooltip('Temperatura', format='.1f')]
            ).properties(height=300)
            st.altair_chart(bar_chart)
            
        with gc2:
            if not df_ts.empty:
                st.markdown("**Evolución Temporal Simultánea**")
                df_ts['date'] = pd.to_datetime(df_ts['date'])
                
                line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                    x='date',
                    y=alt.Y('val', title='LST Promedio (°C)', scale=alt.Scale(zero=False)),
                    color='city',
                    tooltip=['date', 'city', 'val']
                ).properties(height=300).interactive()
                st.altair_chart(line_chart, use_container_width=True)
            else:
                st.info("No hay suficientes datos temporales para graficar.")


# --- 8. SIDEBAR ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Comparativa", "Info"])
    
    if st.session_state.window != "Comparativa":
        ciudades = [
            "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", 
            "Frontera", "Macuspana", "Tenosique", "Huimanguillo", "Cunduacán", 
            "Jalpa de Méndez", "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata"
        ]
        st.session_state.locality = st.selectbox("Ciudad Principal", ciudades)
    
    st.caption("Periodo de Análisis")
    fechas = st.date_input("Fechas", value=st.session_state.date_range)
    if len(fechas) == 2: st.session_state.date_range = fechas
    
    st.markdown("---")
    if st.button("🔄 Recargar"):
        st.session_state.gee_available = False
        st.rerun()

# --- 9. ROUTER ---
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    show_graphics_panel()
elif st.session_state.window == "Comparativa":
    show_comparison_panel()
else:
    st.markdown("### Acerca de\nPlataforma integral de monitoreo térmico urbano.")
