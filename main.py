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
from dotenv import load_dotenv
import json

# Cargamos el archivo de variables de entorno
load_dotenv()

# Carpetas de trabajo
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
TEMP_DIR = DATA_DIR / "temp"
for d in (DATA_DIR, REPORTS_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Estado inicial
if "locality" not in st.session_state:
    st.session_state.locality = "Teapa"  # Área de estudio
if "coordinates" not in st.session_state:
    st.session_state.coordinates = (17.558567, -92.948714)
# if "latitude" not in st.session_state:
#     st.session_state.latitude = -92.948714
# if "longitude" not in st.session_state:
#     st.session_state.longitude = 17.558567
if "date_range" not in st.session_state:
    st.session_state.date_range = (dt.date(2024, 1, 1), dt.datetime.now())
if "gee_available" not in st.session_state:
    st.session_state.gee_available = False
if "window" not in st.session_state:
    st.session_state.window = "Mapas"

# Coordenadas de referencia (aprox) para Teapa, Tabasco
# COORDENADAS_INICIALES = st.session_state.coordinates  # (lat, lon)

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

# st.write(json.dumps(dict(st.secrets["google"]["gee_api_key"])))


def connect_with_gee():
    # Importar módulos utilitarios
    if (
        "gee_available" not in st.session_state
        or st.session_state.gee_available == False
    ):
        try:

            ee.Authenticate()

            credentials = ee.ServiceAccountCredentials(
                st.secrets["google"]["google-service-account"],
                key_data=json.dumps(dict(st.secrets["google"]["gee_api_key"])),
            )

            # ee.Initialize(project=os.getenv("GEE_PROJECT"))

            ee.Initialize(credentials)
            st.toast("Google Earth Engine inicializado")
            st.session_state.gee_available = True
        except Exception as e:
            st.toast(e)
            st.toast("No se pudo inicializar Google Earth Engine")
            st.session_state.gee_available = False
            return False
    return True


def cloudMaskFunction(image):
    qa = image.select("QA_PIXEL")
    cloud_mask = qa.bitwiseAnd(1 << 5)
    shadow_mask = qa.bitwiseAnd(1 << 3)
    combined_mask = cloud_mask.Or(shadow_mask).eq(0)
    return image.updateMask(combined_mask)


def noThermalDataFunction(image):
    st = image.select("ST_B10")
    valid = st.gt(0) and (st.lt(65535))
    return image.updateMask(valid)


def applyScale(image):
    opticalBands = (
        image.select(["SR_B2", "SR_B3", "SR_B4"]).multiply(0.0000275).add(-0.2)
    )
    return image.addBands(opticalBands, None, True)


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
def create_map(center=st.session_state.coordinates, zoom_start=13):
    # Add EE drawing method to folium.
    # """Crea un mapa base Folium centrado en Teapa."""

    if "folium" and "streamlit_folium" not in sys.modules:
        st.toast("Folium no se encuentra instalado")
        return None

    map = folium.Map(st.session_state.coordinates, zoom_start=zoom_start, height=500)

    return map


def set_coordinates():
    if st.session_state.gee_available == True:
        roi = (
            ee.FeatureCollection(os.getenv("GEE_LOCALITIES_ASSET"))
            .filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
            .geometry()
        )

        st.session_state.coordinates = (
            roi.centroid().coordinates().getInfo()[-1],
            roi.centroid().coordinates().getInfo()[0],
        )


# Método para mostrar el panel del mapa
def show_map_panel():
    st.markdown("Islas de calor por localidades de Tabasco")
    st.caption("Visualización de LST desde Google Earth Engine.")

    map = create_map()
    if map == None:
        return

    connect_with_gee()

    if st.session_state.gee_available:
        # # Add custom BASEMAPS
        # BASEMAPS["Google Maps"].add_to(map)
        BASEMAPS["Google Satellite Hybrid"].add_to(map)

        # CGAZ_ADM0 = ee.FeatureCollection("projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM0");
        # CGAZ_ADM1 = ee.FeatureCollection("projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM1");
        # CGAZ_ADM2 = ee.FeatureCollection(
        #     "projects/earthengine-legacy/assets/projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2"
        # )

        roi = (
            ee.FeatureCollection(os.getenv("GEE_LOCALITIES_ASSET"))
            .filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
            .geometry()
        )

        collection = (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterDate(
                (dt.datetime.fromisoformat(str(st.session_state.date_range[0]))),
                dt.datetime.fromisoformat(str(st.session_state.date_range[1])),
            )
            .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
            .map(lambda image: image.clip(roi))
            .map(cloudMaskFunction)
            .map(noThermalDataFunction)
        )

        mosaico = collection.reduce(ee.Reducer.percentile([50]))

        # mosaicoRGB = (
        #     ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        #     .filterBounds(roi)
        #     .filterDate(
        #         (dt.datetime.fromisoformat(str(st.session_state.date_range[0]))),
        #         dt.datetime.fromisoformat(str(st.session_state.date_range[1])),
        #     )
        #     .filter(ee.Filter.lt("CLOUD_COVER", MAX_NUBES))
        #     .map(cloudMaskFunction)
        #     .map(applyScale)
        #     .median()
        # )

        # visColorVerdadero = {
        #     "bands": ("SR_B4", "SR_B3", "SR_B2"),
        #     "min": 0.0,
        #     "max": 0.3,
        # }

        # map.add_ee_layer(mosaicoRGB, visColorVerdadero, "RGB")

        bandaTermica = mosaico.select("ST_B10_p50")

        # Aplicamos la fórmula de escalado para convertir a Kelvin y luego a Celsius.
        # Estos valores son específicos de la Colección 2 de Landsat (L2).
        lstCelsius = (
            bandaTermica.multiply(0.00341802)
            .add(149.0)
            .subtract(273.15)
            .rename("LST_Celsius")
        )

        visParamsLST = {
            "palette": ["blue", "cyan", "green", "yellow", "red"],
            "min": 28,
            "max": 48,
        }

        map.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C) p50")

        percentilUHI = 90
        minPixParche = 3

        lstForThreshold = lstCelsius.rename("LST")

        pctDict = lstForThreshold.reduceRegion(
            reducer=ee.Reducer.percentile([percentilUHI]),
            geometry=roi,
            scale=30,
            maxPixels=1e9,
            bestEffort=True,
        )

        key = ee.String("LST_p").cat(ee.Number(percentilUHI).format())

        umbral = ee.Algorithms.If(
            pctDict.contains(key),
            ee.Number(pctDict.get(key)),
            ee.Number(ee.Dictionary(pctDict).values().get(0)),
        )

        n_umbral = ee.Number(umbral)

        uhiMask = lstForThreshold.gte(n_umbral)

        compCount = uhiMask.connectedPixelCount(maxSize=1024, eightConnected=True)

        uhiClean = uhiMask.updateMask(compCount.gte(minPixParche)).selfMask()

        map.add_ee_layer(
            uhiClean,
            {"palette": ["#d7301f"]},
            "Islas de calor (>= p" + str(percentilUHI) + ", clean)",
        )

        map.add_ee_layer(
            lstCelsius.updateMask(uhiClean),
            {
                "min": visParamsLST["min"],
                "max": visParamsLST["max"],
                "palette": visParamsLST["palette"],
            },
            "LST en islas de calor",
        )

        # style = {
        #     "color": "0000ffff",
        #     "width": 1,
        #     "lineType": "solid",
        #     "fillColor": "00000000",
        # }

        # map.add_ee_layer(roi.style(**style), {}, st.session_state.locality)

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
    st.markdown("Opciones")

    st.markdown("Área de estudio (localidad)")
    st.session_state.locality = st.selectbox(
        "Definir localidad",
        [
            "Balancán",
            "Cárdenas",
            "Frontera",
            "Villahermosa",
            "Comalcalco",
            "Cunduacán",
            "Emiliano Zapata",
            "Huimanguillo",
            "Jalapa",
            "Jalpa de Méndez",
            "Jonuta",
            "Macuspana",
            "Nacajuca",
            "Paraíso",
            "Tacotalpa",
            "Teapa",
            "Tenosique de Pino Suárez",
        ],
    )

    set_coordinates()

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

    # if st.button("do something"):
    #     # do something
    #     st.session_state["locality"] = not st.session_state["locality"]
    #     st.rerun()

    # uploaded_geojson = None
    # if locality_option == "Subir GeoJSON":
    #     uploaded_geojson = st.file_uploader(
    #         "Carga un archivo GeoJSON",
    #         type=["geojson", "json"],
    #         help="El sistema intentará usar esta geometría como locality",
    #     )

    # if st.button("Aplicar locality/Filtros"):
    #     st.session_state.locality = uploaded_geojson if uploaded_geojson else "Teapa"
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
