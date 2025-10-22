


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



# dem = ee.Image("USGS/SRTMGL1_003")

    # vis_params = {
    # "min": 0,
    # "max": 4000,
    # "palette": ["006633", "E5FFCC", "662A00", "D8D8D8", "F5F5F5"]}

    # Create a map object.
    # m = geemap.Map(center=[40,-100], zoom=4)
    # m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)

    # Add the elevation model to the map object.
    # m.add_ee_layer(dem.updateMask(dem.gt(0)), vis_params, "DEM")

    # Display the map.
    # display(m)

    # Create a folium map object.