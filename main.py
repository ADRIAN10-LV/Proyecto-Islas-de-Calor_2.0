# --------------------------------------------------------------
# main.py — Dashboard Streamlit para Islas de Calor Urbano (ICU)
# Autor: Adrian Lara (estructura base generada con ayuda de IA)
# --------------------------------------------------------------

import sys
import os
import ee
import datetime as dt
import streamlit as st
import folium
from folium import plugins
from streamlit_folium import st_folium
from pathlib import Path

# Carpetas de trabajo
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
TEMP_DIR = DATA_DIR / "temp"
for d in (DATA_DIR, REPORTS_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Estado inicial
if "aoi" not in st.session_state:
    st.session_state.aoi = "Teapa"  # Área de estudio (GeoJSON/Fiona/coords)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.datetime.now())
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# Coordenadas de referencia (aprox) para Teapa, Tabasco
COORDENADAS_INICIALES = (17.558567, -92.948714)  # (lat, lon)

# Variable para el máximo de nubes
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
    # Importar módulos utilitarios
    if (
        "gee_available" not in st.session_state
        or st.session_state.gee_available is False
    ):
        try:
            ee.Authenticate()
            ee.Initialize(project="islas-calor-teapa-475319")
            st.toast("Google Earth Engine inicializado")
            st.session_state.gee_available = True
        except Exception as e:
            st.toast("No se pudo inicializar Google Earth Engine")
            st.session_state.gee_available = False
            return False
    return True


# Método para agregar las imágenes de GEE a los mapas de folium
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        # display ee.Image()
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
            ).add_to(self)
        # display ee.ImageCollection()
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
        # display ee.Geometry()
        elif isinstance(ee_object, ee.geometry.Geometry):
            folium.GeoJson(
                data=ee_object.getInfo(), name=name, overlay=True, control=True
            ).add_to(self)
        # display ee.FeatureCollection()
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

    except:
        print("Could not display {}".format(name))


folium.Map.add_ee_layer = add_ee_layer


# Método para generar el mapa base
def create_map(center=COORDENADAS_INICIALES, zoom_start=8):
    # Add EE drawing method to folium.
    # """Crea un mapa base Folium centrado en Teapa."""

    if "folium" and "streamlit_folium" not in sys.modules:
        st.toast("Folium no se encuentra instalado")
        return None

    map = folium.Map(COORDENADAS_INICIALES, zoom_start=zoom_start, height=500)

    return map
    

# Método para mostrar el panel del mapa
def show_map_panel():
    st.markdown("Islas de calor por localidades de Tabasco")
    st.caption("Visualización de NDVI y LST desde Google Earth Engine.")

    map = create_map()
    if map == None:
        return

    connect_with_gee()

    if st.session_state.gee_available:
        # # Add custom BASEMAPS
        # BASEMAPS["Google Maps"].add_to(map)
        # BASEMAPS["Google Satellite Hybrid"].add_to(map)

        # CGAZ_ADM0 = ee.FeatureCollection("projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM0");
        # CGAZ_ADM1 = ee.FeatureCollection("projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM1");
        CGAZ_ADM2 = ee.FeatureCollection(
            "projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2"
        )

        boundaries = ee.FeatureCollection("WM/geoLab/geoBoundaries/600/ADM2")

        filtered = boundaries.filter(ee.Filter.eq("shapeName", st.session_state.aoi))

        style = {
            "color": "0000ffff",
            "width": 2,
            "lineType": "solid",
            "fillColor": "00000080",
        }

        # map.add_ee_layer(filtered.style(**style), {}, "ADM2 Boundaries")

        map.add_ee_layer(filtered.style(**style), {}, st.session_state.aoi)

        # roi = ee.Geometry.Point(-122.4488, 37.7589)

        # st.write(dt.datetime.fromisoformat(str(st.session_state.date_range[0])))
        # st.write(dt.datetime.fromisoformat(str(st.session_state.date_range[1])))

        # collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterDate((dt.datetime.fromisoformat(str(st.session_state.date_range[0]))), dt.datetime.fromisoformat(str(st.session_state.date_range[1]))).filterBounds(roi)

        #   .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", MAX_NUBES)).size().getInfo())

        folium.LayerControl().add_to(map)

    else:
        st.toast("No hay conexión con Google Earth Engine, mostrando solo mapa base")

    st_folium(map, width=None, height=600)


# Configuración de streamlit
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="🌡️",
    layout="wide",
)


# Configuración del sidebar
with st.sidebar:
    st.markdown("Islas de calor Tabasco")
    st.caption("Dashboard base para análisis de islas de calor urbano (LST/NDVI)")

    # Selector de sección
    section = st.radio(
        "Secciones",
        ["Mapas", "Gráficas", "Reportes", "Acerca de"],
        index=0,
    )
    st.session_state.window = section

    # Filtros globales
    st.markdown("Filtros")
    min_date, max_date = dt.date(2014, 1, 1), dt.datetime.now()
    date_range = st.date_input(
        "Rango de fechas",
        value=st.session_state.date_range,
        min_value=min_date,
        max_value=max_date,
        help="Periodo de análisis",
    )
    # st.write(dt.datetime.fromisoformat(str(date_range[0])))
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    st.markdown("Área de estudio (AOI)")
    st.session_state.aoi = st.selectbox("Definir AOI", ["Teapa", "Tacotalpa", "Centro"])

    # if st.button("do something"):
    #     # do something
    #     st.session_state["aoi"] = not st.session_state["aoi"]
    #     st.rerun()

    # uploaded_geojson = None
    # if aoi_option == "Subir GeoJSON":
    #     uploaded_geojson = st.file_uploader(
    #         "Carga un archivo GeoJSON",
    #         type=["geojson", "json"],
    #         help="El sistema intentará usar esta geometría como AOI",
    #     )

    # if st.button("Aplicar AOI/Filtros"):
    #     st.session_state.aoi = uploaded_geojson if uploaded_geojson else "Teapa"
    #     st.toast("Filtros aplicados", icon="✅")

    # if st.button("Generar"):
    #     show_map_panel()

    # metricas = st.multiselect(
    #     "Indicadores",
    #     ["NDVI", "LST"],
    #     default=["LST"],
    #     help="Selecciona qué indicadores calcular/visualizar",
    # )


# Router de las ventanas
match st.session_state.window:
    case "Mapas":
        show_map_panel()
    case "Gráficas":
        st.write("Gráficas (placeholder, ya definidas arriba)")
    case "Reportes":
        st.write("Reportes (placeholder, ya definidos arriba)")
    case _:
        st.write("Acerca de (placeholder, ya definido arriba)")
