from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Resena:
    orden_id:     str
    app:          str
    marca:        str
    local_id:     str
    local_nombre: str
    fecha_orden:  Optional[datetime]   # None para fuentes sin fecha (ej: Mercado Libre)
    estrellas:    int
    plato:        str
    tags:         list = field(default_factory=list)
    comentario:   str = ""
    es_error_grave: bool = False

@dataclass
class Reclamo:
    orden_id:          str
    app:               str
    marca:             str
    local_id:          str
    local_nombre:      str
    fecha_orden:       datetime
    platos_pedidos:    str   # todos los platos de la orden (de api_ordenes)
    platos_reclamados: str   # productos específicos del reclamo (de compensations.products_names)
    razon:             str   # motivo traducido al español
    comentario:        str = ""  # texto libre escrito por el cliente (user_details)

@dataclass
class ResumenLocal:
    local_id:     str
    local_nombre: str
    fecha_desde:  datetime
    fecha_hasta:  datetime
    total_ordenes:      int = 0
    resenas_negativas:  int = 0
    errores_graves:     int = 0
    resenas: list = field(default_factory=list)
