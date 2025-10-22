


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