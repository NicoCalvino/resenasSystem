# Sistema de Reseñas Negativas

Extrae reseñas de 1-2 estrellas de Rappi, PedidosYa y Mercado Pago,
detecta errores graves y genera un PDF por local.

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuración

Crear un archivo `.env` (o exportar variables de entorno):

```bash
export RAPPI_EMAIL="nicolascalvino@gmail.com"
export RAPPI_PASSWORD="RVc0Iq5t1X*y"
export PEYA_EMAIL="nicolascalvino@gmail.com"
export PEYA_PASSWORD="uRW.zB*,xQQ2Ftc"
```

## Uso

```bash
# Reseñas de ayer (modo normal diario)
python main.py

# Rango específico
python main.py --desde 2026-03-31 --hasta 2026-04-01

# Incluir CSV de Mercado Pago
python main.py --mp-csv /ruta/al/archivo.csv

# Ver el browser durante el login (útil para debug o CAPTCHA)
python main.py --headless false

# Carpeta de salida personalizada
python main.py --output /ruta/informes
```

## Estructura del proyecto

```
resenas_system/
├── main.py                    # Orquestador principal
├── requirements.txt
├── config/
│   ├── models.py              # Modelos de datos (Resena, ResumenLocal)
│   └── locales.py             # 65 tiendas con IDs reales de Rappi/PedidosYa
├── extractors/
│   ├── rappi.py               # Login → token localStorage → API REST
│   ├── pedidosya.py           # Login → interceptar token → API REST
│   └── mercadopago.py         # Procesador de CSV descargado manualmente
├── processor/
│   └── procesador.py          # Detección errores graves + agrupación por local
└── report/
    └── generador_pdf.py       # PDF con gauges, estrellas, badges error grave
```

## Credenciales

- **Rappi**: cuenta maestra de partners.rappi.com
- **PedidosYa**: cuenta maestra de portal-app.pedidosya.com
- **Mercado Pago**: descarga manual del CSV desde el portal Looker

## Notas sobre el login

El sistema usa Playwright para hacer login en el portal web y extraer
el token de autenticación, replicando exactamente el flujo del Excel/VBA actual.
Si el portal muestra un CAPTCHA, ejecutar con `--headless false` para
completarlo manualmente.

## Errores graves

Se detectan usando las palabras clave de la hoja "Referencias" del Excel:
agria, agrio, alambre, asco, bicho, cabello, crud, cucaracha, descomp,
diarrea, enferm, gusano, hongo, hormiga, intoxica, larva, madera, metal,
moho, mosca, pelo, plástico, podrid, sangr, uña, vidrio, vomit, y más.
