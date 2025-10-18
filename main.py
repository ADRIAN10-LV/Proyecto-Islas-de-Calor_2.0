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
    st.session_state.aoi = None  # Área de estudio (GeoJSON/Fiona/coords)
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2014, 1, 1), dt.datetime.now())
if "last_map" not in st.session_state:
    st.session_state.last_map = None

# Coordenadas de referencia (aprox) para Teapa, Tabasco
COORDENADAS_INICIALES = (17.558567, -92.948714)  # (lat, lon)

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

GEE_AVAILABLE = False


def connect_with_gee():
    global GEE_AVAILABLE
    # Importar módulos utilitarios
    try:
        ee.Authenticate()
        ee.Initialize(project="islas-calor-teapa-475319")
        st.toast("Google Earth Engine inicializado ✅")
        GEE_AVAILABLE = True
    except Exception as e:
        GEE_AVAILABLE = False
        st.toast("No se pudo inicializar GEE:", e)


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
def build_base_map(center=COORDENADAS_INICIALES, zoom_start=14):
    # Add EE drawing method to folium.
    """Crea un mapa base Folium centrado en Teapa."""

    if "folium" and "streamlit_folium" not in sys.modules:
        st.toast("Folium no se encuentra instalado")
        return None

    map = folium.Map(COORDENADAS_INICIALES, zoom_start=zoom_start, height=500)
    return map
    # dem = ee.Image('USGS/SRTMGL1_003')

    # vis_params = {
    # 'min': 0,
    # 'max': 4000,
    # 'palette': ['006633', 'E5FFCC', '662A00', 'D8D8D8', 'F5F5F5']}

    # Create a map object.
    # m = geemap.Map(center=[40,-100], zoom=4)
    # m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)

    # Add the elevation model to the map object.
    # m.add_ee_layer(dem.updateMask(dem.gt(0)), vis_params, 'DEM')

    # Display the map.
    # display(m)

    # Create a folium map object.

# Método para mostrar el panel del mapa
def show_map_panel():
    st.markdown("Islas de calor por localidades de Tabasco")
    st.caption("Visualización de NDVI y LST desde Google Earth Engine.")

    map = build_base_map()
    if map == None:
        return

    connect_with_gee()

    if GEE_AVAILABLE:
        # Set visualization parameters.
        dem = ee.Image("USGS/SRTMGL1_003")

        # Set visualization parameters.
        vis_params = {
            "min": 0,
            "max": 4000,
            "palette": ["006633", "E5FFCC", "662A00", "D8D8D8", "F5F5F5"],
        }

        # Add custom BASEMAPS
        BASEMAPS["Google Maps"].add_to(map)
        BASEMAPS["Google Satellite Hybrid"].add_to(map)

        # Add the elevation model to the map object.
        map.add_ee_layer(dem.updateMask(dem.gt(0)), vis_params, "DEM")

        # jan_2023_climate = (
        #     ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_AGGR")
        #     .filterDate("2023-01", "2023-02")
        #     .first()
        # )
        # # jan_2023_climate

        # m = geemap.Map(center=[30, 0], zoom=2)

        # vis_params = {
        #     "bands": ["temperature_2m"],
        #     "min": 229,
        #     "max": 304,
        #     "palette": "inferno",
        # }
        # m.add_layer(jan_2023_climate, vis_params, "Temperature (K)")

        # Geometría del área de estudio
        # if st.session_state.aoi == "TEAPA_DEFAULT" or st.session_state.aoi is None:
        #     geometry = get_area_teapa()
        # else:
        #     # En el futuro: parsear GeoJSON cargado
        #     geometry = get_area_teapa()

        # start_date, end_date = st.session_state.date_range
        # start_date = str(start_date)
        # end_date = str(end_date)

        # # Colección Landsat 8 SR
        # collection = "LANDSAT/LC08/C02/T1_L2"

        # if "NDVI" in metricas:
        #     ndvi_layer = calcular_ndvi(collection, geometry, start_date, end_date)
        #     mapid = ndvi_layer.getMapId(
        #         {"min": 0, "max": 1, "palette": ["red", "yellow", "green"]}
        #     )
        #     folium.raster_layers.TileLayer(
        #         tiles=mapid["tile_fetcher"].url_format,
        #         attr="Google Earth Engine",
        #         name="NDVI",
        #         overlay=True,
        #         control=True,
        #     ).add_to(m)

        # if "LST" in metricas:
        #     lst_layer = calcular_lst(collection, geometry, start_date, end_date)
        #     mapid = lst_layer.getMapId(
        #         {"min": 20, "max": 40, "palette": ["blue", "yellow", "red"]}
        #     )
        #     folium.raster_layers.TileLayer(
        #         tiles=mapid["tile_fetcher"].url_format,
        #         attr="Google Earth Engine",
        #         name="LST (°C)",
        #         overlay=True,
        #         control=True,
        #     ).add_to(m)

        folium.LayerControl().add_to(map)

    else:
        st.warning("No hay conexión con GEE. Mostrando solo mapa base.")

    out = st_folium(map, width=None, height=600)
    st.session_state.last_map = out


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
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state.date_range = date_range

    st.markdown("Área de estudio (AOI)")
    aoi_option = st.selectbox("Definir AOI", ["Teapa", "Tacotalpa", "Subir GeoJSON"])

    uploaded_geojson = None
    if aoi_option == "Subir GeoJSON":
        uploaded_geojson = st.file_uploader(
            "Carga un archivo GeoJSON",
            type=["geojson", "json"],
            help="El sistema intentará usar esta geometría como AOI",
        )

    if st.button("Aplicar AOI/Filtros"):
        st.session_state.aoi = uploaded_geojson if uploaded_geojson else "Teapa"
        st.toast("Filtros aplicados", icon="✅")

    metricas = st.multiselect(
        "Indicadores",
        ["NDVI", "LST"],
        default=["LST"],
        help="Selecciona qué indicadores calcular/visualizar",
    )


# Router de las ventanas
match section:
    case "Mapas":
        show_map_panel()
    case "Gráficas":
        st.write("Gráficas (placeholder, ya definidas arriba)")
    case "Reportes":
        st.write("Reportes (placeholder, ya definidos arriba)")
    case _:
        st.write("Acerca de (placeholder, ya definido arriba)")
