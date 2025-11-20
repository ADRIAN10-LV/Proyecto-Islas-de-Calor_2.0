# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Versión: FINAL ESTABLE (Sin parches de instalación)
# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
import pandas as pd
import altair as alt
from streamlit_folium import st_folium
from pathlib import Path
import base64
from fpdf import FPDF  # Importación estándar

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🗺️",
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

def create_map(center=None, height=500):
    location = center if center else [st.session_state.coordinates[0], st.session_state.coordinates[1]]
    m = folium.Map(location=location, zoom_start=12, height=height, tiles=None)
    for name, layer in BASEMAPS.items():
        layer.add_to(m)
    return m

# --- HELPER: OBTENER ROI ---
def get_roi(locality_name):
    urban_areas = ee.FeatureCollection(ASSET_ID)
    target = urban_areas.filter(ee.Filter.eq("NOMGEO", locality_name))
    if target.size().getInfo() > 0:
        return target.geometry()
    return None

# --- CLASE PDF ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Reporte de Monitoreo Termico - Tabasco Heat Watch', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

# --- 6. PANELES PRINCIPALES ---

def show_map_panel():
    st.markdown(f"### 🗺️ Monitor Urbano: {st.session_state.locality}")
    if not connect_with_gee(): return
    
    roi = get_roi(st.session_state.locality)

    if roi:
        m = create_map()
        centroid = roi.centroid().coordinates().getInfo()
        m.location = [centroid[1], centroid[0]]
        
        empty = ee.Image().byte()
        outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
        m.add_ee_layer(outline, {'palette': '000000'}, "Límite Urbano")

        start = st.session_state.date_range[0].strftime("%Y-%m-%d")
        end = st.session_state.date_range[1].strftime("%Y-%m-%d")
        
        col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
               .filterBounds(roi).filterDate(start, end)
               .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
               .map(cloudMaskFunction).map(maskThermalNoData).map(addNDVI).map(addLST))
        
        count = col.size().getInfo()
        if count > 0:
            mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
            
            lst_band = mosaic.select("LST_p50")
            ndvi_band = mosaic.select("NDVI_p50")
            
            m.add_ee_layer(lst_band, {"min": 28, "max": 45, "palette": ['blue', 'cyan', 'yellow', 'red']}, "1. LST (°C)")
            
            p90 = lst_band.reduceRegion(ee.Reducer.percentile([90]), roi, 30).get("LST_p50")
            p90_val_info = 0
            if p90:
                val_p90 = ee.Number(p90)
                p90_val_info = p90.getInfo()
                uhi = lst_band.gte(val_p90)
                uhi_clean = uhi.updateMask(uhi.connectedPixelCount(100, True).gte(3)).selfMask()
                m.add_ee_layer(uhi_clean, {"palette": ['#d7301f']}, f"2. Hotspots (> {p90_val_info:.1f}°C)")
            
            m.add_ee_layer(ndvi_band, {"min": 0, "max": 0.6, "palette": ['brown', 'white', 'green']}, "3. NDVI")
            
            p95_ndvi = ndvi_band.reduceRegion(ee.Reducer.percentile([95]), roi, 30).get("NDVI_p50")
            p95_ndvi_info = 0
            if p95_ndvi:
                val_p95 = ee.Number(p95_ndvi)
                p95_ndvi_info = p95_ndvi.getInfo()
                veg_mask = ndvi_band.gte(val_p95).selfMask()
                m.add_ee_layer(veg_mask, {"palette": ['#00FF00']}, f"4. Refugios Verdes (> {p95_ndvi_info:.2f})")

            st.success(f"Análisis basado en {count} imágenes procesadas.")
            c1, c2 = st.columns(2)
            c1.metric("🔥 Umbral Calor Crítico (p90)", f"{p90_val_info:.2f} °C")
            c2.metric("🌳 Umbral Alta Vegetación (p95)", f"{p95_ndvi_info:.2f} NDVI")
        else:
            st.warning("Sin imágenes limpias en este periodo.")
        
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

    with st.spinner("Calculando estadísticas..."):
        mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
        sample = mosaic.select(["LST_p50", "NDVI_p50"]).sample(region=roi, scale=30, numPixels=1000, geometries=False)
        data = sample.getInfo()['features']
        
        if data:
            df = pd.DataFrame([x['properties'] for x in data])
            
            st.markdown("#### 1. Correlación Calor vs. Vegetación")
            chart = alt.Chart(df).mark_circle(size=60, opacity=0.6).encode(
                x=alt.X('NDVI_p50', title='Índice de Vegetación (NDVI)'),
                y=alt.Y('LST_p50', title='Temperatura (°C)', scale=alt.Scale(zero=False)),
                color=alt.Color('LST_p50', scale=alt.Scale(scheme='turbo')),
                tooltip=['NDVI_p50', 'LST_p50']
            ).properties(height=350).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            st.markdown("#### 2. Distribución de Temperaturas")
            hist = alt.Chart(df).mark_bar().encode(
                x=alt.X('LST_p50', bin=alt.Bin(maxbins=20), title='Rango de Temperatura'),
                y=alt.Y('count()', title='Frecuencia'),
                color=alt.value('#ffaa00')
            ).properties(height=300)
            st.altair_chart(hist, use_container_width=True)
        
        st.markdown("---")
        st.markdown("#### 3. Tendencia Histórica (Serie de Tiempo)")
        
        def get_mean_lst(img):
            mean = img.reduceRegion(ee.Reducer.mean(), roi, 100).get("LST") 
            return ee.Feature(None, {
                'date': img.date().format("YYYY-MM-dd"), 
                'LST_mean': mean
            })
        
        ts_features = col.map(get_mean_lst).filter(ee.Filter.notNull(['LST_mean'])).getInfo()['features']
        
        if ts_features:
            df_ts = pd.DataFrame([x['properties'] for x in ts_features])
            df_ts['date'] = pd.to_datetime(df_ts['date'])
            
            line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                x=alt.X('date', title='Fecha', axis=alt.Axis(format='%Y-%m-%d')),
                y=alt.Y('LST_mean', title='Temperatura Promedio (°C)', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('date', title='Fecha', format='%Y-%m-%d'), alt.Tooltip('LST_mean', title='Temp (°C)', format='.1f')]
            ).properties(height=350).interactive()
            
            st.altair_chart(line_chart, use_container_width=True)
        else:
            st.info("No hay suficientes puntos temporales.")


def show_comparison_panel():
    st.markdown("### ⚖️ Comparativa de Ciudades")
    if not connect_with_gee(): return

    ciudades_disp = [
        "Villahermosa", "Teapa", "Cárdenas", "Comalcalco", "Paraíso", 
        "Frontera", "Macuspana", "Tenosique", "Huimanguillo", "Cunduacán", 
        "Jalpa de Méndez", "Nacajuca", "Jalapa", "Tacotalpa", "Emiliano Zapata"
    ]
    
    selected = st.multiselect(
        "Selecciona 2 ciudades:", 
        ciudades_disp, 
        default=st.session_state.compare_cities[:2],
        max_selections=2
    )

    if len(selected) != 2:
        st.info("Selecciona exactamente 2 ciudades.")
        return

    start = st.session_state.date_range[0].strftime("%Y-%m-%d")
    end = st.session_state.date_range[1].strftime("%Y-%m-%d")
    
    stats_data = []
    timeseries_data = []

    c1, c2 = st.columns(2)
    cols = [c1, c2]

    for idx, city in enumerate(selected):
        with cols[idx]:
            st.subheader(f"📍 {city}")
            roi = get_roi(city)
            
            if roi:
                col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                       .filterBounds(roi).filterDate(start, end)
                       .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
                       .map(cloudMaskFunction).map(maskThermalNoData).map(addLST))
                
                if col.size().getInfo() > 0:
                    mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
                    lst = mosaic.select("LST_p50")
                    
                    stats = lst.reduceRegion(
                        reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.max(), sharedInputs=True),
                        geometry=roi, scale=100, bestEffort=True
                    ).getInfo()
                    
                    stats_data.append({
                        "Ciudad": city,
                        "LST Promedio (°C)": stats.get("LST_p50_mean"),
                        "LST Máxima (°C)": stats.get("LST_p50_max")
                    })
                    
                    centroid = roi.centroid().coordinates().getInfo()
                    m = create_map(center=[centroid[1], centroid[0]], height=350)
                    m.add_ee_layer(lst, {"min": 28, "max": 42, "palette": ['blue', 'cyan', 'yellow', 'red']}, "Temperatura")
                    empty = ee.Image().byte()
                    outline = empty.paint(featureCollection=ee.FeatureCollection([ee.Feature(roi)]), color=1, width=2)
                    m.add_ee_layer(outline, {'palette': 'black'}, "Límite")
                    
                    st_folium(m, width="100%", height=350, key=f"map_{city}")
                    
                    def get_ts(img):
                        mean_val = img.reduceRegion(ee.Reducer.mean(), roi, 200).get("LST")
                        return ee.Feature(None, {'date': img.date().format("YYYY-MM-dd"), 'val': mean_val, 'city': city})
                    
                    ts_feats = col.map(get_ts).filter(ee.Filter.notNull(['val'])).getInfo()['features']
                    for f in ts_feats:
                        timeseries_data.append(f['properties'])
                else:
                    st.warning("Sin datos.")

    st.markdown("---")
    st.subheader("📊 Resultados")

    if stats_data:
        df_stats = pd.DataFrame(stats_data)
        df_ts = pd.DataFrame(timeseries_data)
        
        gc1, gc2 = st.columns(2)
        with gc1:
            df_melt = df_stats.melt("Ciudad", var_name="Métrica", value_name="Temperatura")
            bar_chart = alt.Chart(df_melt).mark_bar().encode(
                x=alt.X('Métrica', axis=None), y='Temperatura', color='Métrica', column='Ciudad'
            ).properties(height=300)
            st.altair_chart(bar_chart, use_container_width=True)
            
        with gc2:
            if not df_ts.empty:
                df_ts['date'] = pd.to_datetime(df_ts['date'])
                line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                    x='date', y=alt.Y('val', scale=alt.Scale(zero=False)), color='city'
                ).properties(height=300).interactive()
                st.altair_chart(line_chart, use_container_width=True)

# --- 7. NUEVO PANEL: REPORTES Y DESCARGAS ---
def show_report_panel():
    st.markdown(f"### 📥 Reportes y Descargas: {st.session_state.locality}")
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
        st.warning("No hay datos para generar el reporte.")
        return
    
    st.info("Generando datos para exportación, por favor espera un momento...")

    # Calcular Estadísticas Generales
    mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
    lst = mosaic.select("LST_p50")
    
    # Estadísticas escalares
    stats = lst.reduceRegion(
        reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.max(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.percentile([90]), sharedInputs=True),
        geometry=roi, scale=100, bestEffort=True
    ).getInfo()
    
    # Datos para CSV (Serie de Tiempo)
    def get_ts_export(img):
        mean = img.reduceRegion(ee.Reducer.mean(), roi, 100).get("LST")
        max_val = img.reduceRegion(ee.Reducer.max(), roi, 100).get("LST")
        return ee.Feature(None, {
            'Fecha': img.date().format("YYYY-MM-dd"), 
            'LST_Promedio': mean,
            'LST_Maxima': max_val
        })
    
    ts_export = col.map(get_ts_export).filter(ee.Filter.notNull(['LST_Promedio'])).getInfo()['features']
    df_ts = pd.DataFrame([x['properties'] for x in ts_export])

    # --- SECCIÓN 1: DESCARGA DE DATOS ---
    st.markdown("#### 1. Descarga de Datos Crudos (CSV)")
    c1, c2 = st.columns(2)
    
    # CSV Serie de Tiempo
    if not df_ts.empty:
        csv_ts = df_ts.to_csv(index=False).encode('utf-8')
        c1.download_button(
            "📅 Descargar Serie Temporal (.csv)",
            csv_ts,
            f"serie_tiempo_{st.session_state.locality}.csv",
            "text/csv",
            key='download-csv'
        )
    
    # CSV Puntos de Muestreo (Para QGIS)
    # Tomamos una muestra de 500 puntos
    sample = mosaic.select(["LST_p50", "NDVI_p50"]).sample(region=roi, scale=100, numPixels=500, geometries=True)
    data_sample = sample.getInfo()['features']
    if data_sample:
        rows = []
        for feat in data_sample:
            props = feat['properties']
            coords = feat['geometry']['coordinates']
            rows.append({
                "Lon": coords[0], "Lat": coords[1], 
                "LST_C": props.get("LST_p50"), "NDVI": props.get("NDVI_p50")
            })
        df_sample = pd.DataFrame(rows)
        csv_sample = df_sample.to_csv(index=False).encode('utf-8')
        c2.download_button(
            "📍 Descargar Puntos Muestreo (.csv)",
            csv_sample,
            f"puntos_muestreo_{st.session_state.locality}.csv",
            "text/csv",
            key='download-points'
        )

    # --- SECCIÓN 2: REPORTE PDF ---
    st.markdown("---")
    st.markdown("#### 2. Generar Reporte Ejecutivo (PDF)")
    
    if st.button("📄 Generar Reporte PDF"):
        with st.spinner("Maquetando PDF..."):
            pdf = PDFReport()
            pdf.add_page()
            
            # Títulos
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, f"Reporte: {st.session_state.locality}", 0, 1, 'L')
            
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"Periodo de Analisis: {start} al {end}", 0, 1, 'L')
            pdf.ln(10)
            
            # Tabla de Estadísticas
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Resumen Termico", 0, 1, 'L')
            
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 10, f"- Temperatura Promedio: {stats.get('LST_p50_mean', 0):.2f} C", 0, 1)
            pdf.cell(0, 10, f"- Temperatura Maxima Detectada: {stats.get('LST_p50_max', 0):.2f} C", 0, 1)
            pdf.cell(0, 10, f"- Umbral de Isla de Calor (p90): {stats.get('LST_p50_p90', 0):.2f} C", 0, 1)
            pdf.ln(10)
            
            # Intentar agregar mapa (Miniatura estática)
            try:
                vis_params = {"min": 28, "max": 45, "palette": ['blue', 'cyan', 'yellow', 'red'], "dimensions": 500}
                thumb_url = lst.getThumbURL(vis_params)
                pdf.set_font("Arial", "B", 14)
                pdf.cell(0, 10, "Mapa de Calor (Miniatura)", 0, 1, 'L')
                pdf.image(thumb_url, x=10, y=None, w=180)
                pdf.ln(5)
                pdf.set_font("Arial", "I", 10)
                pdf.cell(0, 10, "Nota: Visualizacion generada dinamicamente via Google Earth Engine.", 0, 1)
            except Exception as e:
                pdf.cell(0, 10, f"(No se pudo generar la vista previa del mapa: {e})", 0, 1)

            # Generar descarga
            html = create_download_link(pdf.output(dest="S").encode("latin-1"), f"Reporte_{st.session_state.locality}.pdf")
            st.markdown(html, unsafe_allow_html=True)

def create_download_link(val, filename):
    b64 = base64.b64encode(val)  # val looks like b'...'
    return f'<a href="data:application/octet-stream;base64,{b64.decode()}" download="{filename}">✅ Click aqui para descargar tu PDF</a>'


# --- 8. SIDEBAR ---
with st.sidebar:
    st.title("🔥 Tabasco Heat Watch")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Comparativa", "Reportes", "Info"])
    
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
elif st.session_state.window == "Reportes":
    show_report_panel()
else:
    st.markdown("### Acerca de\nPlataforma integral de monitoreo térmico urbano.")
