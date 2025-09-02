# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Proyecto: Teapa, Tabasco (2014–2024)
# Autor: Adrian Lara (estructura base generada con ayuda de IA)
# --------------------------------------------------------------

import os
import datetime as dt
from pathlib import Path

import streamlit as st

# Dependencias de mapas
try:
    import folium
    from streamlit_folium import st_folium
    FOLIUM_AVAILABLE = True
except Exception:
    FOLIUM_AVAILABLE = False

# Importar módulos utilitarios
try:
    import ee
    from app.utils.gee_utils import init_gee, get_area_teapa
    from app.utils.ndvi import calcular_ndvi
    from app.utils.lst import calcular_lst
    GEE_AVAILABLE = True
    init_gee()
except Exception as e:
    GEE_AVAILABLE = False
    print("⚠️ No se pudo inicializar GEE:", e)

# ------------------------- CONFIG BÁSICA ------------------------- #
st.set_page_config(
    page_title="ICU Teapa 2014–2024",
    page_icon="🌡️",
    layout="wide",
)

# Carpetas de trabajo
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
TEMP_DIR = DATA_DIR / "temp"
for d in (DATA_DIR, REPORTS_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Estado inicial
if "aoi" not in st.session_state:
    st.session_state.aoi = None  # Área de estudio (GeoJSON/Fiona/coords)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2014, 1, 1), dt.date(2024, 12, 31))
if "last_map" not in st.session_state:
    st.session_state.last_map = None

# Coordenadas de referencia (aprox) para Teapa, Tabasco
TEAPA_CENTER = (17.553, -92.865)  # (lat, lon)

# ------------------------- SIDEBAR ------------------------- #
with st.sidebar:
    st.markdown("## 🌡️ ICU – Teapa")
    st.caption("Dashboard base para análisis de islas de calor urbano (LST/NDVI)")

    # Selector de sección
    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )

    st.divider()

    # Filtros globales
    st.markdown("### Filtros globales")
    min_date, max_date = dt.date(2014, 1, 1), dt.date(2024, 12, 31)
    date_range = st.date_input(
        "Rango de fechas",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
        help="Periodo de análisis (2014–2024)",
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    metricas = st.multiselect(
        "Indicadores",
        ["NDVI", "LST"],
        default=["LST"],
        help="Selecciona qué indicadores calcular/visualizar",
    )

    st.markdown("### Área de estudio (AOI)")
    aoi_option = st.selectbox(
        "Definir AOI",
        ["Teapa (predeterminado)", "Subir GeoJSON"]
    )

    uploaded_geojson = None
    if aoi_option == "Subir GeoJSON":
        uploaded_geojson = st.file_uploader(
            "Carga un archivo GeoJSON",
            type=["geojson", "json"],
            help="El sistema intentará usar esta geometría como AOI",
        )

    if st.button("Aplicar AOI/Filtros"):
        st.session_state.aoi = uploaded_geojson if uploaded_geojson else "TEAPA_DEFAULT"
        st.toast("Filtros aplicados", icon="✅")

    st.divider()

    # Conexión GEE
    if GEE_AVAILABLE:
        st.success("Google Earth Engine inicializado ✅")
    else:
        st.info("No se detectó GEE. Instala y autentica con 'earthengine-api'.")

# ------------------------- UTILIDADES ------------------------- #

def build_base_map(center=TEAPA_CENTER, zoom_start=12):
    """Crea un mapa base Folium centrado en Teapa."""
    if not FOLIUM_AVAILABLE:
        st.error("Para ver mapas instala 'folium' y 'streamlit-folium'.")
        return None

    m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)
    return m


def show_map_panel():
    st.markdown("# 🗺️ Mapas")
    st.caption("Visualización de NDVI y LST desde Google Earth Engine.")

    m = build_base_map()
    if m is None:
        return

    if GEE_AVAILABLE:
        # Geometría del área de estudio
        if st.session_state.aoi == "TEAPA_DEFAULT" or st.session_state.aoi is None:
            geometry = get_area_teapa()
        else:
            # En el futuro: parsear GeoJSON cargado
            geometry = get_area_teapa()

        start_date, end_date = st.session_state.date_range
        start_date = str(start_date)
        end_date = str(end_date)

        # Colección Landsat 8 SR
        collection = "LANDSAT/LC08/C02/T1_L2"

        if "NDVI" in metricas:
            ndvi_layer = calcular_ndvi(collection, geometry, start_date, end_date)
            mapid = ndvi_layer.getMapId({"min": 0, "max": 1, "palette": ["red", "yellow", "green"]})
            folium.raster_layers.TileLayer(
                tiles=mapid["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name="NDVI",
                overlay=True,
                control=True
            ).add_to(m)

        if "LST" in metricas:
            lst_layer = calcular_lst(collection, geometry, start_date, end_date)
            mapid = lst_layer.getMapId({"min": 20, "max": 40, "palette": ["blue", "yellow", "red"]})
            folium.raster_layers.TileLayer(
                tiles=mapid["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name="LST (°C)",
                overlay=True,
                control=True
            ).add_to(m)

        folium.LayerControl().add_to(m)

    else:
        st.warning("No hay conexión con GEE. Mostrando solo mapa base.")

    out = st_folium(m, width=None, height=600)
    st.session_state.last_map = out

# ------------------------- ROUTER ------------------------- #
if section == "Mapas":
    show_map_panel()
elif section == "Gráficas":
    st.write("Gráficas (placeholder, ya definidas arriba)")
elif section == "Reportes":
    st.write("Reportes (placeholder, ya definidos arriba)")
else:
    st.write("Acerca de (placeholder, ya definido arriba)")
