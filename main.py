# --------------------------------------------------------------

# --------------------------------------------------------------

import streamlit as st
import ee
import datetime as dt
import folium
import pandas as pd
import altair as alt
from streamlit_folium import st_folium
from pathlib import Path
from branca.element import Template, MacroElement

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Islas de calor Tabasco",
    page_icon="",
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

def add_legend(m, title, colors, vmin, vmax):
    css_gradient = f"linear-gradient(to right, {', '.join(colors)})"
    template = f"""
    {{% macro html(this, kwargs) %}}
    <div style="
        position: fixed; 
        bottom: 50px; left: 50px; width: 250px; height: 85px; 
        z-index:9999; font-size:14px;
        background-color: rgba(255, 255, 255, 0.85);
        padding: 10px;
        border-radius: 6px;
        border: 1px solid #ccc;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
        ">
        <div style="font-weight: bold; margin-bottom: 5px;">{title}</div>
        <div style="width: 100%; height: 15px; background: {css_gradient}; border: 1px solid #aaa;"></div>
        <div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 12px;">
            <span>{vmin}</span>
            <span>{vmax}</span>
        </div>
    </div>
    {{% endmacro %}}
    """
    macro = MacroElement()
    macro._template = Template(template)
    m.get_root().add_child(macro)

def create_map(center=None, height=500):
    location = center if center else [st.session_state.coordinates[0], st.session_state.coordinates[1]]
    m = folium.Map(location=location, zoom_start=12, height=height, tiles=None)
    for name, layer in BASEMAPS.items():
        layer.add_to(m)
    return m

def get_roi(locality_name):
    urban_areas = ee.FeatureCollection(ASSET_ID)
    target = urban_areas.filter(ee.Filter.eq("NOMGEO", locality_name))
    if target.size().getInfo() > 0:
        return target.geometry()
    return None

# --- 6. PANELES PRINCIPALES ---

def show_map_panel():
    st.markdown(f"### Proyecto de Residencia: Islas de Calor {st.session_state.locality}")
    if not connect_with_gee(): return
    
    roi = get_roi(st.session_state.locality)

<<<<<<< HEAD
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

        # mosaico = collection.reduce(ee.Reducer.percentile([50]))

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

        # bandaTermica = mosaico.select("ST_B10_p50")

        # # Aplicamos la fórmula de escalado para convertir a Kelvin y luego a Celsius.
        # # Estos valores son específicos de la Colección 2 de Landsat (L2).
        # lstCelsius = (
        #     bandaTermica.multiply(0.00341802)
        #     .add(149.0)
        #     .subtract(273.15)
        #     .rename("LST_Celsius")
        # )

        # visParamsLST = {
        #     "palette": ["blue", "cyan", "green", "yellow", "red"],
        #     "min": 28,
        #     "max": 48,
        # }

        # map.add_ee_layer(lstCelsius, visParamsLST, "Temperatura Superficial (°C) p50")

        # percentilUHI = 90
        # minPixParche = 3

        # lstForThreshold = lstCelsius.rename("LST")

        # pctDict = lstForThreshold.reduceRegion(
        #     reducer=ee.Reducer.percentile([percentilUHI]),
        #     geometry=roi,
        #     scale=30,
        #     maxPixels=1e9,
        #     bestEffort=True,
        # )

        # key = ee.String("LST_p").cat(ee.Number(percentilUHI).format())

        # umbral = ee.Algorithms.If(
        #     pctDict.contains(key),
        #     ee.Number(pctDict.get(key)),
        #     ee.Number(ee.Dictionary(pctDict).values().get(0)),
        # )

        # n_umbral = ee.Number(umbral)

        # uhiMask = lstForThreshold.gte(n_umbral)

        # compCount = uhiMask.connectedPixelCount(maxSize=1024, eightConnected=True)

        # uhiClean = uhiMask.updateMask(compCount.gte(minPixParche)).selfMask()

        # map.add_ee_layer(
        #     uhiClean,
        #     {"palette": ["#d7301f"]},
        #     "Islas de calor (>= p" + str(percentilUHI) + ", clean)",
        # )

        # map.add_ee_layer(
        #     lstCelsius.updateMask(uhiClean),
        #     {
        #         "min": visParamsLST["min"],
        #         "max": visParamsLST["max"],
        #         "palette": visParamsLST["palette"],
        #     },
        #     "LST en islas de calor",
        # )

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
        ["Información","Mapas", "Gráficas"],
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
            "Tenosique",
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


# --------------------------------------------------------------
# Panel de gráficas
# --------------------------------------------------------------
def show_graphics_panel():
    st.markdown("### 🌡️ Análisis de Temperatura Superficial (LST)")
    st.caption(
        f"Localidad seleccionada: **{st.session_state.locality}** | "
        f"Periodo: {st.session_state.date_range[0]} — {st.session_state.date_range[1]}"
    )

    tipo_grafica = st.radio(
        "Tipo de gráfica:",
        ["Evolución temporal", "Comparación entre municipios"],
        horizontal=True,
    )

    if not connect_with_gee():
        st.error("No se pudo conectar con Google Earth Engine.")
        return

    # ======================================
    # Definición de la colección Landsat 8
    # ======================================
    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterDate(
            dt.datetime.fromisoformat(str(st.session_state.date_range[0])),
            dt.datetime.fromisoformat(str(st.session_state.date_range[1])),
        )
        .filter(ee.Filter.lt("CLOUD_COVER", 30))
        .map(cloudMaskFunction)
        .map(noThermalDataFunction)
    )

    # Conversión de ST_B10 a °C
    def calc_lst(img):
        lst = img.select("ST_B10").multiply(0.00341802).add(149).subtract(273.15)
        return lst.set("year", img.date().get("year"))

    lst_collection = collection.map(calc_lst)

    # ======================================
    # MODO 1 — EVOLUCIÓN TEMPORAL
    # ======================================
    if tipo_grafica == "Evolución temporal":
        roi = (
            ee.FeatureCollection(os.getenv("GEE_LOCALITIES_ASSET"))
            .filter(ee.Filter.eq("NOMGEO", st.session_state.locality))
            .geometry()
        )

        # Reducir promedio por año
        def yearly_mean(year):
            start = ee.Date.fromYMD(year, 1, 1)
            end = start.advance(1, "year")
            year_coll = lst_collection.filterDate(start, end)
            lst_mean = (
                year_coll.mean()
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e9,
                )
                .get("ST_B10")
            )
            return ee.Feature(None, {"year": year, "LST_media": lst_mean})

        years = ee.List.sequence(2014, 2024)
        lst_by_year = ee.FeatureCollection(years.map(yearly_mean)).getInfo()

        # Convertir a DataFrame
        data = []
        for f in lst_by_year["features"]:
            props = f["properties"]
            if props["LST_media"] is not None:
                data.append([int(props["year"]), float(props["LST_media"])])

        df = pd.DataFrame(data, columns=["Año", "LST_media"]).sort_values("Año")
        st.success(f"✅ Datos reales obtenidos de {st.session_state.locality}.")
        st.line_chart(df, x="Año", y="LST_media")
        st.caption("Evolución anual de la temperatura superficial promedio (°C).")

    # ======================================
    # MODO 2 — COMPARACIÓN ENTRE MUNICIPIOS
    # ======================================
    elif tipo_grafica == "Comparación entre municipios":
        localidades = [
            "Balancán", "Cárdenas", "Frontera", "Villahermosa", "Comalcalco",
            "Cunduacán", "Emiliano Zapata", "Huimanguillo", "Jalapa",
            "Jalpa de Méndez", "Jonuta", "Macuspana", "Nacajuca", "Paraíso",
            "Tacotalpa", "Teapa", "Tenosique"
        ]

        modo = st.radio(
            "Modo de comparación:",
            ["Seleccionar dos cabeceras", "Comparar todas"],
            horizontal=True,
        )

        # Calcular promedio por localidad
        features = ee.FeatureCollection(os.getenv("GEE_LOCALITIES_ASSET"))
        results = []

        for muni in localidades:
            roi = features.filter(ee.Filter.eq("NOMGEO", muni)).geometry()
            lst_mean = (
                lst_collection.mean()
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e9,
                )
                .getInfo()
            )
            if "ST_B10" in lst_mean and lst_mean["ST_B10"] is not None:
                results.append({"Municipio": muni, "LST_promedio": float(lst_mean["ST_B10"])})

        df_municipios = pd.DataFrame(results)

        if modo == "Seleccionar dos cabeceras":
            muni_1 = st.selectbox("Municipio 1", localidades, index=0)
            muni_2 = st.selectbox("Municipio 2", localidades, index=1)
            df_sel = df_municipios[df_municipios["Municipio"].isin([muni_1, muni_2])]
            st.bar_chart(df_sel, x="Municipio", y="LST_promedio")
        else:
            st.bar_chart(df_municipios, x="Municipio", y="LST_promedio")

        st.caption("Temperatura superficial promedio (°C) por cabecera municipal en el rango seleccionado.")

def Información():
    st.title("Acerca del Proyecto")

    st.markdown("""
    ### Descripción

    Este proyecto tiene como objetivo permitir identificar, analizar y visualizar las 
    **Islas de Calor Urbano (ICU)** en el municipio de **Teapa, Tabasco** como área de estudio principal, mediante el 
    procesamiento de imágenes satelitales (Landsat 8) y el cálculo de la 
    **Temperatura Superficial Terrestre (LST)**.  
    El sistema integra **Google Earth Engine**, **Python** y **Streamlit** para automatizar el 
    análisis geoespacial y mostrar los resultados de forma interactiva.

    ---

    ### Autores del desarrollo 
    - **Adrian Lara Vázquez** — **Residente** — Estudiante de la carrera Ingeniería Informatíca del Instituto Tecnológico Superior de la Región Sierra.
    - **Ing. Daniel Perez Flores** — **Colaborador y ayudante del proyecto** — Maestro e Ingeniero Informatíco del Instituto Tecnológico Superior de la Región Sierra.
    - **M.I José de Jesús Lenin Valencia Cruz** — **Asesor Interno del proyecto** — Maestro e Ingeniero Informatíco del Instituto Tecnológico Superior de la Región Sierra.
    - **Mtro. Candelario Peralta Carreta** — **Asesor Externo del proyecto** — Centro del Cambio Global y la Sustentabilidad en el Sureste A.C. (CCGSS).

    ---

    ### Instituciones participantes
    - **Instituto Tecnológico Superior de la Región Sierra (ITSS)**  
    - **Centro del Cambio Global y la Sustentabilidad en el Sureste A.C. (CCGSS)**
    """)

        
# Router de las ventanas
match st.session_state.window:
    case "Mapas":
        show_map_panel()
    case "Gráficas":
        show_graphics_panel()
    case "Información":
        Información()
=======
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
            
            viz_lst = {"min": 28, "max": 45, "palette": ['blue', 'cyan', 'yellow', 'red']}
            m.add_ee_layer(lst_band, viz_lst, "1. LST (°C)")
            add_legend(m, "Temperatura LST (°C)", viz_lst['palette'], viz_lst['min'], viz_lst['max'])
            
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
        
        map_data = st_folium(m, width="100%", height=600)
        
        if map_data and map_data.get('last_clicked'):
            clicked_lat = map_data['last_clicked']['lat']
            clicked_lng = map_data['last_clicked']['lng']
            if count > 0:
                point = ee.Geometry.Point([clicked_lng, clicked_lat])
                values = mosaic.select(["LST_p50", "NDVI_p50"]).reduceRegion(
                    reducer=ee.Reducer.first(), geometry=point, scale=30
                ).getInfo()
                
                val_lst = values.get('LST_p50')
                val_ndvi = values.get('NDVI_p50')
                
                st.info(f"📍 **Inspector:** Lat: {clicked_lat:.4f}, Lon: {clicked_lng:.4f}")
                k1, k2 = st.columns(2)
                k1.metric("🌡️ Temperatura", f"{val_lst:.2f} °C" if val_lst else "N/A")
                k2.metric("🌿 NDVI", f"{val_ndvi:.2f}" if val_ndvi else "N/A")
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
            return ee.Feature(None, {'date': img.date().format("YYYY-MM-dd"), 'LST_mean': mean})
        
        ts_features = col.map(get_mean_lst).filter(ee.Filter.notNull(['LST_mean'])).getInfo()['features']
        
        if ts_features:
            df_ts = pd.DataFrame([x['properties'] for x in ts_features])
            df_ts['date'] = pd.to_datetime(df_ts['date'])
            
            line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                x=alt.X('date', title='Fecha', axis=alt.Axis(format='%Y-%m-%d')),
                y=alt.Y('LST_mean', title='Temperatura Promedio (°C)', scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip('date', format='%Y-%m-%d'), alt.Tooltip('LST_mean', format='.1f')]
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
                    viz = {"min": 28, "max": 42, "palette": ['blue', 'cyan', 'yellow', 'red']}
                    m.add_ee_layer(lst, viz, "Temperatura")
                    add_legend(m, f"LST {city}", viz['palette'], viz['min'], viz['max'])
                    
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
            else:
                st.error("Error cargando geometría.")

    st.markdown("---")
    st.subheader("📊 Resultados Comparativos")
    st.markdown(" ")

    if stats_data:
        df_stats = pd.DataFrame(stats_data)
        df_ts = pd.DataFrame(timeseries_data)
        
        st.markdown("##### 1. Promedios y Máximos")
        df_melt = df_stats.melt("Ciudad", var_name="Métrica", value_name="Temperatura")
        bar_chart = alt.Chart(df_melt).mark_bar().encode(
            x=alt.X('Métrica', axis=None),
            y=alt.Y('Temperatura', title='Grados Celsius'),
            color='Métrica',
            column=alt.Column('Ciudad', header=alt.Header(titleOrient="bottom"))
        ).properties(width=300, height=300).configure_view(stroke='transparent')
        st.altair_chart(bar_chart)
        
        st.markdown("---")
        
        if not df_ts.empty:
            st.markdown("##### 2. Evolución Temporal Simultánea")
            df_ts['date'] = pd.to_datetime(df_ts['date'])
            line_chart = alt.Chart(df_ts).mark_line(point=True).encode(
                x=alt.X('date', title='Fecha'),
                y=alt.Y('val', title='LST Promedio (°C)', scale=alt.Scale(zero=False)),
                color='city',
                tooltip=['date', 'city', 'val']
            ).properties(height=400).interactive()
            st.altair_chart(line_chart, use_container_width=True)


def show_report_panel():
    st.markdown(f"### 📥 Descarga de Datos: {st.session_state.locality}")
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
        st.warning("No hay datos para exportar.")
        return
    
    st.info("Generando archivos...")

    mosaic = col.reduce(ee.Reducer.percentile([50])).clip(roi)
    
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

    st.markdown("#### Datos Disponibles")
    c1, c2 = st.columns(2)
    
    if not df_ts.empty:
        csv_ts = df_ts.to_csv(index=False).encode('utf-8')
        c1.download_button(
            "📅 Descargar Serie Temporal (.csv)",
            csv_ts, f"serie_tiempo_{st.session_state.locality}.csv", "text/csv"
        )
    
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
            csv_sample, f"puntos_muestreo_{st.session_state.locality}.csv", "text/csv"
        )


def show_info_panel():
    st.markdown("""
    ### Descripción
    Este proyecto tiene como objetivo permitir identificar, analizar y visualizar las 
    **Islas de Calor Urbano (ICU)** en el municipio de **Teapa, Tabasco** como área de estudio principal, mediante el 
    procesamiento de imágenes satelitales (Landsat 8) y el cálculo de la 
    **Temperatura Superficial Terrestre (LST)**.
    
    ---
    ### Autores
    - **Adrian Lara Vázquez** — Residente
    - **Ing. Daniel Perez Flores** — Colaborador
    - **M.I José de Jesús Lenin Valencia Cruz** — Asesor Interno
    - **Mtro. Candelario Peralta Carreta** — Asesor Externo

    ---
    ### Instituciones
    - **Instituto Tecnológico Superior de la Región Sierra (ITSS)**
    - **Centro del Cambio Global y la Sustentabilidad en el Sureste A.C. (CCGSS)**
    """)


# --- 9. SIDEBAR ---
with st.sidebar:
    st.title("APLICACIÓN WEB PARA EL ANÁLISIS TÉRMICO URBANO EN TEAPA CON LANDSAT 8 USANDO PYTHON Y GOOGLE EARTH ENGINE")
    st.markdown("---")
    st.session_state.window = st.radio("Menú", ["Mapas", "Gráficas", "Comparativa", "Descargas", "Info"])
    
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

# --- 10. ROUTER ---
if st.session_state.window == "Mapas":
    show_map_panel()
elif st.session_state.window == "Gráficas":
    show_graphics_panel()
elif st.session_state.window == "Comparativa":
    show_comparison_panel()
elif st.session_state.window == "Descargas":
    show_report_panel()
else:
    show_info_panel()
>>>>>>> 0cd58a8ab27ed53b33f2f11119cb2eec3cec2352
