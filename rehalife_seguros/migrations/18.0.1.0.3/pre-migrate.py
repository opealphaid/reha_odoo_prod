# -*- coding: utf-8 -*-
"""Fase 6, punto 3 (2026-11-06): % de cobertura del Pedido de Venta Marco.

Hasta 18.0.1.0.2 el price_unit de una línea de PVM ERA el % de cobertura.
Desde 18.0.1.0.3 el % vive en sale_order_line.porcentaje_cobertura y
price_unit pasa a ser el monto que cubre la aseguradora (lo recalcula el
post-migrate).

Este script, ANTES de cargar el modelo nuevo:
1. Crea las columnas porcentaje_cobertura (Float sin dígitos → double
   precision) y precio_servicio_pvm (digits → numeric) si no existen, con el
   tipo que espera Odoo 18 (fields.Float._column_type). Así Odoo no las trata como columnas nuevas: no calcula
   precio_servicio_pvm sobre TODAS las líneas de venta ni dispara el
   recálculo de price_unit de pedidos de venta normales (que podría
   resetearlos a la lista de precios).
2. Copia price_unit → porcentaje_cobertura en las líneas de PVM que aún no
   tienen el % (porcentaje_cobertura IS NULL). Idempotente: una segunda
   corrida no encuentra NULL y no hace nada, aunque price_unit ya sea un
   monto.

No toca Notas de Conformidad (guardan su propio %, migración 18.0.1.0.2) ni
los valores congelados de las reservas. Si se actualiza saltando versiones,
el pre-migrate de 18.0.1.0.2 corre antes que este, cuando price_unit todavía
es el %.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        ALTER TABLE sale_order_line
            ADD COLUMN IF NOT EXISTS porcentaje_cobertura double precision,
            ADD COLUMN IF NOT EXISTS precio_servicio_pvm numeric
    """)
    cr.execute("""
        UPDATE sale_order_line l
           SET porcentaje_cobertura = l.price_unit
          FROM sale_order o
         WHERE o.id = l.order_id
           AND o.es_pedido_marco IS TRUE
           AND l.display_type IS NULL
           AND l.porcentaje_cobertura IS NULL
    """)
    _logger.info(
        '[rehalife_seguros 18.0.1.0.3] porcentaje_cobertura copiado desde price_unit en %s '
        'línea(s) de Pedido de Venta Marco.', cr.rowcount,
    )
