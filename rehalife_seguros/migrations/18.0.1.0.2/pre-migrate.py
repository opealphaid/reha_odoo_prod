# -*- coding: utf-8 -*-
"""Pagos anticipados, Fase 4.

rehalife.nota.conformidad.porcentaje_cobertura deja de ser
related='pedido_marco_line_id.price_unit' (store=True) y pasa a ser un campo
almacenado normal, fijado al crear la NC.

Como era related store, la columna ya tiene el valor; al cambiar la
definición, Odoo conserva la columna y sus datos (no la borra ni recalcula
nada: un campo que deja de ser computado no se recalcula, y los computados
que dependen de él, como monto_cubierto/importe_total, solo se recalculan
cuando cambian sus dependencias por el ORM, no por SQL).

Este script solo RELLENA las NC con porcentaje_cobertura NULL usando el
price_unit actual de su línea (lo que el related habría mostrado), ANTES de
que deje de ser related. No toca:
- NC con un valor ya guardado (idempotente: correrlo dos veces no cambia nada);
- monto_cubierto / importe_total de ninguna NC (UPDATE por SQL, sin recálculo),
  así que las NC facturadas conservan sus montos.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'rehalife_nota_conformidad'
           AND column_name = 'porcentaje_cobertura'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE rehalife_nota_conformidad nc
           SET porcentaje_cobertura = l.price_unit
          FROM sale_order_line l
         WHERE l.id = nc.pedido_marco_line_id
           AND nc.porcentaje_cobertura IS NULL
    """)
    _logger.info(
        '[rehalife_seguros 18.0.1.0.2] porcentaje_cobertura rellenado en %s Nota(s) de '
        'Conformidad sin valor (sin recalcular montos).', cr.rowcount,
    )
