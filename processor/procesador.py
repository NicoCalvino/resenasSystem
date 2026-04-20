"""
Procesador usando keywords reales del Excel (hoja Referencias).
"""
import logging, re
from datetime import datetime
from collections import defaultdict
from config.models import Resena, ResumenLocal
from config.locales import KEYWORDS_GRAVES

logger = logging.getLogger(__name__)

def _norm(t):
    for a,b in [('a','a'),('e','e'),('i','i'),('o','o'),('u','u'),
                ('a','a'),('e','e'),('i','i'),('o','o'),('u','u'),
                ('n','n')]:
        pass
    import unicodedata
    return unicodedata.normalize('NFKD', t.lower()).encode('ascii','ignore').decode()

_KW = [re.compile(r'\b' + re.escape(_norm(k))) for k in KEYWORDS_GRAVES]

def es_error_grave(comentario, tags):
    texto = _norm(" ".join([comentario] + tags))
    for pattern in _KW:
        if pattern.search(texto):
            return True
    return False

class Procesador:
    def procesar(self, resenas, totales_por_grupo, fecha_desde, fecha_hasta):
        for r in resenas:
            r.es_error_grave = es_error_grave(r.comentario, r.tags)

        por_grupo = defaultdict(list)
        for r in resenas:
            por_grupo[r.local_id].append(r)

        resumenes = []
        for grupo, rs in por_grupo.items():
            rs.sort(key=lambda r: r.fecha_orden or datetime.min)
            resumenes.append(ResumenLocal(
                local_id=grupo, local_nombre=grupo,
                fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                total_ordenes=totales_por_grupo.get(grupo, 0),
                resenas_negativas=len(set(r.orden_id for r in rs)),
                errores_graves=len(set(r.orden_id for r in rs if r.es_error_grave)),
                resenas=rs,
            ))
        return sorted(resumenes, key=lambda r: r.local_nombre)

def _test():
    casos = [
        ("encontre un pelo en la sopa",   [], True),
        ("cucaracha adentro",             [], True),
        ("el pollo estaba crudo",         [], True),
        ("plastico adentro",              [], True),
        ("me intoxique",                  [], True),
        ("sabor agrio",                   [], True),
        ("estaba podrido",                [], True),
        ("llego frio pero rico",          [], False),
        ("no me gusto el sabor",          [], False),
        ("tardo mucho",                   [], False),
        ("vidrio en la comida",           [], True),
        ("tenia hongos",                  [], True),
        ("vomite toda la noche",          [], True),
        ("olor a podrido",                [], True),
        ("todo bien normal",              [], False),
    ]
    ok = sum(1 for c,t,e in casos if es_error_grave(c,t)==e)
    print(f"\nKeywords reales del Excel — {ok}/{len(casos)} tests OK\n")
    for c,t,e in casos:
        r = es_error_grave(c,t)
        print(f"  {'OK' if r==e else 'FAIL'}  '{c[:45]}'  esperado={e} obtenido={r}")

if __name__ == "__main__":
    import sys; sys.path.insert(0,'/home/claude/resenas_system')
    _test()
