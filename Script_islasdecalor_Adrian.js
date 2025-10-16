// =================================================================================
// PASO 1: Cargar y Seleccionar el Área de Interés (AOI)
// =================================================================================

// --- PARÁMETRO SELECCIONABLE ---
// Cambia este nombre para analizar otra localidad de tu capa.
// Debe coincidir exactamente con uno de los siguientes valores de la columna 'NOMGEO':
//
// 'Villahermosa', 'Cárdenas', 'Comalcalco', 'Huimanguillo', 'Macuspana',
// 'Cunduacán', 'Paraíso', 'Tenosique', 'Teapa', 'Centla', 'Balancán',
// 'Jalpa de Méndez', 'Nacajuca', 'Emiliano Zapata', 'Jalapa',
// 'Tacotalpa', 'Jonuta'
//
var nombreLocalidad = "Comalcalco";

// Carga tu capa de localidades urbanas desde tus assets de GEE.
var localidadesUrbanas = ee.FeatureCollection(
  "projects/ee-cando/assets/areas_urbanas_Tab"
);

// Filtra la colección para seleccionar solo la localidad con el nombre que definiste.
var aoiFeature = localidadesUrbanas
  .filter(ee.Filter.eq("NOMGEO", nombreLocalidad))
  .first();

// Extrae la geometría de esa localidad para usarla como tu Área de Interés (AOI).
var aoi = ee.Feature(aoiFeature).geometry();

// Centra el mapa en tu AOI seleccionada con un nivel de zoom adecuado.
Map.centerObject(aoi, 12);

// (Opcional) Añade la capa al mapa para visualizar el contorno.
Map.addLayer(aoi, { color: "FF0000" }, "AOI: " + nombreLocalidad);

// =================================================================================
// PASO 2: Definir Parámetros de Búsqueda de Imágenes
// =================================================================================

// --- PARÁMETROS SELECCIONABLES ---
// Define el rango de fechas. Recomendación UHI Tabasco: usar época cálida-seca (p. ej., abril–junio).
var fechaInicio = "2024-04-01";
var fechaFin = "2024-06-30";

// Define el satélite a utilizar.
// 'LC09': Landsat 9 (Disponible desde Febrero 2022 - Presente).
// 'LC08': Landsat 8 (Disponible desde Abril 2013 - Presente).
var satelite = "LC08";

// Define el porcentaje máximo de nubes permitido en la imagen (ej. 30 = 30%).
var maxNubes = 30;

// // =================================================================================
// PASO 3 (CORREGIDO Y MEJORADO): Enmascarar Nubes/Sombras y NO-DATA térmico; Crear Mosaico
// =================================================================================

// --- Función para enmascarar nubes y sombras en Landsat 8/9 (QA_PIXEL) ---
function cloudMask(image) {
  var qa = image.select("QA_PIXEL");
  var cloudShadowBitMask = 1 << 3; // sombras
  var cloudBitMask = 1 << 5; // nubes
  var mask = qa
    .bitwiseAnd(cloudShadowBitMask)
    .eq(0)
    .and(qa.bitwiseAnd(cloudBitMask).eq(0));
  return image.updateMask(mask);
}

// --- NUEVO: Enmascara NO-DATA/Saturados en la banda térmica ST_B10 (0 y 65535 en C2 L2) ---
function maskThermalNoData(image) {
  var st = image.select("ST_B10");
  var valid = st.gt(0).and(st.lt(65535));
  return image.updateMask(valid);
}

// Carga la colección de imágenes usando los parámetros definidos.
var coleccion = ee
  .ImageCollection("LANDSAT/" + satelite + "/C02/T1_L2")
  .filterBounds(aoi)
  .filterDate(fechaInicio, fechaFin)
  .filter(ee.Filter.lt("CLOUD_COVER", maxNubes))
  .map(cloudMask) // nubes/sombras
  .map(maskThermalNoData); // NO-DATA térmico

// *** MEJORA: en lugar de mediana de todo el año, usa percentil p50 (robusto) en el periodo elegido ***
var mosaico = coleccion.reduce(ee.Reducer.percentile([50]));

// --- (opcional) percentil 75 para enfatizar máximos térmicos ---
// var mosaico_p75 = coleccion.reduce(ee.Reducer.percentile([75]));

// --- Color verdadero (referencia) ---
// Función para escalar las bandas ópticas para visualización (reflectancia de superficie)
function aplicarEscala(imagen) {
  var bandasOpticas = imagen
    .select(["SR_B2", "SR_B3", "SR_B4"])
    .multiply(0.0000275)
    .add(-0.2);
  return imagen.addBands(bandasOpticas, null, true);
}
var mosaicoRGB = ee
  .ImageCollection("LANDSAT/" + satelite + "/C02/T1_L2")
  .filterBounds(aoi)
  .filterDate(fechaInicio, fechaFin)
  .filter(ee.Filter.lt("CLOUD_COVER", maxNubes))
  .map(cloudMask)
  .map(aplicarEscala)
  .median();

// Parámetros de visualización para color verdadero
var visColorVerdadero = {
  bands: ["SR_B4", "SR_B3", "SR_B2"],
  min: 0.0,
  max: 0.3,
};

// Añade el mosaico RGB al mapa.
Map.addLayer(
  mosaicoRGB.clip(aoi),
  visColorVerdadero,
  "Mosaico Color Verdadero (RGB)"
);

// Imprime en la consola la información del mosaico (percentil).
print("Información del mosaico (p50, con máscaras):", mosaico);

// ====================

// PASO 4: Calcular la Temperatura Superficial (LST) en Celsius
// =================================================================================

// Seleccionamos la banda de Temperatura Superficial del mosaico de percentil.
// OJO: tras el reduce(percentile) la banda se llama 'ST_B10_p50' (o _p75 si usas p75).
var bandaTermica = mosaico.select("ST_B10_p50");

// Aplicamos la fórmula de escalado para convertir a Kelvin y luego a Celsius.
// Estos valores son específicos de la Colección 2 de Landsat (L2).
var lstCelsius = bandaTermica
  .multiply(0.00341802) // Factor de escala
  .add(149.0) // Offset
  .subtract(273.15) // Kelvin a Celsius
  .rename("LST_Celsius"); // Nuevo nombre de la banda

// (Opcional) LST p75
// var lstCelsius_p75 = mosaico_p75.select('ST_B10_p75')
//   .multiply(0.00341802).add(149.0).subtract(273.15)
//   .rename('LST_Celsius_p75');

// Imprime en la consola la información de la capa de LST.
print("Información de la capa LST (°C):", lstCelsius);

// =================================================================================

//=================================================================================
// PASO 5: Visualizar el Mapa de Temperatura (LST)
// =================================================================================

// Define los parámetros de visualización para la capa LST.
// AJUSTA min/max según tu región; en Tabasco típicamente 30–45 °C diurno, suelos más altos.
var visParamsLST = {
  palette: ["blue", "cyan", "green", "yellow", "red"],
  min: 28,
  max: 48,
};

// Añade la capa de LST al mapa, usando la paleta de colores y recortándola al AOI.
Map.addLayer(
  lstCelsius.clip(aoi),
  visParamsLST,
  "Temperatura Superficial (°C) p50"
);

// (Opcional) Visualiza p75 para resaltar hotspots
// Map.addLayer(lstCelsius_p75.clip(aoi),
//   {min:30, max:50, palette:['cyan','green','yellow','red','maroon']},
//   'Temperatura Superficial (°C) p75');

// (Recomendado) Estadísticos dentro del AOI para control de calidad
var stats = lstCelsius.reduceRegion({
  reducer: ee.Reducer.minMax()
    .combine({ reducer2: ee.Reducer.mean(), sharedInputs: true })
    .combine({
      reducer2: ee.Reducer.percentile([5, 50, 95]),
      sharedInputs: true,
    }),
  geometry: aoi,
  scale: 30,
  maxPixels: 1e9,
  bestEffort: true,
});
print("Estadísticos LST (°C) en AOI:", stats);

// (Diagnóstico extra) Revisa la ST_B10 mediana (DN) para confirmar que no hay 0 dentro del AOI
var stDN = coleccion.select("ST_B10").median().reduceRegion({
  reducer: ee.Reducer.minMax(),
  geometry: aoi,
  scale: 30,
  maxPixels: 1e9,
  bestEffort: true,
});
print("Chequeo ST_B10 DN (mediana) en AOI (min/max):", stDN);

//
// =================================================================================
// PASO 6: Islas de calor por UMBRAL ESTADÍSTICO dentro del AOI (robusto)
// =================================================================================

// --- Parámetros ---
var percentilUHI = 90; // 90 o 95
var minPixParche = 3; // 3 píxeles fijo

// 6.0 Asegura un nombre de banda estable para el umbral
var lstForThreshold = lstCelsius.rename("LST"); // <--- clave: renombrar a 'LST'

// (Opcional) excluir agua al calcular el percentil (QA bit 7); descomenta si lo necesitas
// var aguaBit = 1 << 7;
// var qaMedian = coleccion.median().select('QA_PIXEL');
// var maskNoAgua = qaMedian.bitwiseAnd(aguaBit).eq(0);
// lstForThreshold = lstForThreshold.updateMask(maskNoAgua);

// 6.1 Diccionario con el percentil
var pctDict = lstForThreshold.reduceRegion({
  reducer: ee.Reducer.percentile([percentilUHI]),
  geometry: aoi,
  scale: 30,
  maxPixels: 1e9,
  bestEffort: true,
});
print("Diccionario de percentiles (debug):", pctDict);

// 6.2 Obtén el umbral de forma robusta
// Intentamos con la clave esperada 'LST_pXX'; si no existe, tomamos el primer valor del diccionario.
var key = ee.String("LST_p").cat(ee.Number(percentilUHI).format());
var umbral = ee.Algorithms.If(
  pctDict.contains(key),
  ee.Number(pctDict.get(key)),
  ee.Number(ee.Dictionary(pctDict).values().get(0)) // fallback
);
umbral = ee.Number(umbral);
print("Umbral LST (°C) p" + percentilUHI + " en AOI:", umbral);

// 6.3 Máscara UHI (≥ umbral) + limpieza por tamaño mínimo
var uhiMask = lstForThreshold.gte(umbral);
var compCount = uhiMask.connectedPixelCount({
  maxSize: 1024,
  eightConnected: true,
});
var uhiClean = uhiMask.updateMask(compCount.gte(minPixParche)).selfMask();

// 6.4 Visualización
Map.addLayer(
  uhiClean.clip(aoi),
  { palette: ["#d7301f"] },
  "Islas de calor (≥ p" + percentilUHI + ", clean)"
);
Map.addLayer(
  lstCelsius.updateMask(uhiClean).clip(aoi),
  {
    min: visParamsLST.min,
    max: visParamsLST.max,
    palette: visParamsLST.palette,
  },
  "LST en islas de calor"
);

// 6.5 Métricas
var areaUHIha = ee.Image.pixelArea()
  .updateMask(uhiClean)
  .reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: aoi,
    scale: 30,
    maxPixels: 1e9,
    bestEffort: true,
  })
  .get("area");
print(
  "Área UHI (≥ p" + percentilUHI + ") [ha]:",
  ee.Number(areaUHIha).divide(10000)
);

var sevStats = lstCelsius.updateMask(uhiClean).reduceRegion({
  reducer: ee.Reducer.mean().combine({
    reducer2: ee.Reducer.max(),
    sharedInputs: true,
  }),
  geometry: aoi,
  scale: 30,
  maxPixels: 1e9,
  bestEffort: true,
});
print("Severidad UHI — LST media/máxima (°C):", sevStats);

// =================================================================================
// PASO 7: Comparar temporadas (SECA vs. LLUVIAS) y evaluar PERSISTENCIA
// =================================================================================

// --- Fechas de las temporadas (ajústalas a tu criterio local) ---
var secaInicio = "2024-03-01";
var secaFin = "2024-05-31";
var lluviasInicio = "2024-07-01";
var lluviasFin = "2024-09-30";

// --- Función auxiliar: LST (°C) p50 para un rango de fechas ---
function LST_por_rango(fechaIni, fechaFin) {
  var col = ee
    .ImageCollection("LANDSAT/" + satelite + "/C02/T1_L2")
    .filterBounds(aoi)
    .filterDate(fechaIni, fechaFin)
    .filter(ee.Filter.lt("CLOUD_COVER", maxNubes))
    .map(cloudMask)
    .map(maskThermalNoData);

  var mos = col.reduce(ee.Reducer.percentile([50]));
  var lst = mos
    .select("ST_B10_p50")
    .multiply(0.00341802)
    .add(149.0)
    .subtract(273.15)
    .rename("LST");
  return lst.set("n_imgs", col.size());
}

// --- Función auxiliar: máscara UHI (≥ percentilUHI) con limpieza por minPixParche ---
// (usa las mismas constantes percentilUHI y minPixParche que definiste en PASO 6)
function UHI_mask(lstImg, geom) {
  // Asegura clave de percentil estable
  lstImg = lstImg.rename("LST");
  var pct = lstImg.reduceRegion({
    reducer: ee.Reducer.percentile([percentilUHI]),
    geometry: geom,
    scale: 30,
    maxPixels: 1e9,
    bestEffort: true,
  });
  var key = ee.String("LST_p").cat(ee.Number(percentilUHI).format());
  var thr = ee.Algorithms.If(
    pct.contains(key),
    ee.Number(pct.get(key)),
    ee.Number(ee.Dictionary(pct).values().get(0))
  );
  thr = ee.Number(thr);

  var mask = lstImg.gte(thr);
  var count = mask.connectedPixelCount({
    maxSize: 1024, // límite permitido por GEE
    eightConnected: true,
  });
  var clean = mask.updateMask(count.gte(minPixParche)).selfMask();
  return clean.set("umbral", thr);
}

// --- 7.1 LST por temporada (p50 robusto de cada periodo) ---
var lstSeca = LST_por_rango(secaInicio, secaFin);
var lstLluvia = LST_por_rango(lluviasInicio, lluviasFin);
print("Imágenes usadas — SECA:", lstSeca.get("n_imgs"));
print("Imágenes usadas — LLUVIAS:", lstLluvia.get("n_imgs"));

// --- 7.2 UHI por temporada (≥ percentilUHI interno de cada una) ---
var uhiSeca = UHI_mask(lstSeca, aoi);
var uhiLluvia = UHI_mask(lstLluvia, aoi);
print("Umbral SECA (°C) p" + percentilUHI + ":", uhiSeca.get("umbral"));
print("Umbral LLUVIAS (°C) p" + percentilUHI + ":", uhiLluvia.get("umbral"));

// --- 7.3 Persistencia: intersección de UHI en ambas temporadas ---
var uhiPersist = uhiSeca.and(uhiLluvia).selfMask();

// --- 7.4 Capas de visualización (LST ocultas por defecto) ---
Map.addLayer(
  lstSeca.clip(aoi),
  { min: 28, max: 48, palette: ["blue", "cyan", "green", "yellow", "red"] },
  "LST SECA (°C) p50 " + secaInicio + "–" + secaFin,
  false
);

Map.addLayer(
  lstLluvia.clip(aoi),
  { min: 28, max: 48, palette: ["blue", "cyan", "green", "yellow", "red"] },
  "LST LLUVIAS (°C) p50 " + lluviasInicio + "–" + lluviasFin,
  false
);

Map.addLayer(
  uhiSeca.clip(aoi),
  { palette: ["#d7301f"] },
  "UHI SECA (≥ p" + percentilUHI + ")",
  true
);
Map.addLayer(
  uhiLluvia.clip(aoi),
  { palette: ["#d7301f"] },
  "UHI LLUVIAS (≥ p" + percentilUHI + ")",
  true
);
Map.addLayer(
  uhiPersist.clip(aoi),
  { palette: ["#800026"] },
  "UHI PERSISTENTE (∩)",
  true
);

// --- 7.5 Métricas de área (ha) e índice Jaccard ---
var areaImg = ee.Image.pixelArea();
function areaHa(maskImg) {
  return ee
    .Number(
      areaImg
        .updateMask(maskImg)
        .reduceRegion({
          reducer: ee.Reducer.sum(),
          geometry: aoi,
          scale: 30,
          maxPixels: 1e9,
          bestEffort: true,
        })
        .get("area")
    )
    .divide(10000);
}
var areaSecaHa = areaHa(uhiSeca);
var areaLluviaHa = areaHa(uhiLluvia);
var areaInterHa = areaHa(uhiPersist);
var areaUnionHa = areaHa(uhiSeca.or(uhiLluvia).selfMask());
var jaccard = areaInterHa.divide(areaUnionHa);

print("Área UHI SECA (ha):", areaSecaHa);
print("Área UHI LLUVIAS (ha):", areaLluviaHa);
print("Área UHI PERSISTENTE (ha):", areaInterHa);
print("Índice de similitud Jaccard:", jaccard);
