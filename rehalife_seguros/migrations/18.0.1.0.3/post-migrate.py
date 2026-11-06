# -*- coding: utf-8 -*-
"""Fase 6, punto 3 (2026-11-06): recalcula price_unit de las líneas de PVM.

Después de cargar el modelo nuevo (el pre-migrate ya copió el % a
porcentaje_cobertura):
1. Líneas que no son de PVM: porcentaje_cobertura / precio_servicio_pvm NULL
   → 0 (SQL, sin recálculo).
2. Líneas de PVM sin precio_servicio_pvm: se fija con el precio ACTUAL del
   servicio (product.lst_price). Las que ya lo tienen lo conservan (no
   siguen cambios de precio posteriores).
3. price_unit = technical_price_unit = precio_servicio_pvm × % / 100,
   redondeado con la moneda del pedido, SOLO donde no coincide. Por SQL:
   un pedido bloqueado prohíbe escribir price_unit por el ORM.
4. Se recalculan con el ORM los importes que dependen de price_unit
   (subtotales, totales del pedido, monto a facturar) de esas líneas.

Idempotente: una segunda corrida no encuentra diferencias y no cambia nada.
No toca facturas, Notas de Conformidad ni valores congelados de reservas.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("""
        UPDATE sale_order_line l
           SET porcentaje_cobertura = COALESCE(l.porcentaje_cobertura, 0),
               precio_servicio_pvm = COALESCE(l.precio_servicio_pvm, 0)
          FROM sale_order o
         WHERE o.id = l.order_id
           AND (o.es_pedido_marco IS NOT TRUE OR l.display_type IS NOT NULL)
           AND (l.porcentaje_cobertura IS NULL OR l.precio_servicio_pvm IS NULL)
    """)

    cr.execute("""
        SELECT l.id
          FROM sale_order_line l
          JOIN sale_order o ON o.id = l.order_id
         WHERE o.es_pedido_marco IS TRUE
           AND l.display_type IS NULL
    """)
    line_ids = [row[0] for row in cr.fetchall()]
    if not line_ids:
        return

    cr.execute("""
        SELECT id, porcentaje_cobertura, precio_servicio_pvm, price_unit, technical_price_unit
          FROM sale_order_line WHERE id IN %s
    """, (tuple(line_ids),))
    rows = {r[0]: r[1:] for r in cr.fetchall()}

    lines = env['sale.order.line'].browse(line_ids)
    cambiadas = []
    for line in lines:
        porcentaje, precio, price_unit, technical = rows[line.id]
        porcentaje = float(porcentaje or 0.0)
        if precio is None:
            precio = line.product_id.lst_price if line.product_id else 0.0
        precio = float(precio)
        currency = line.order_id.currency_id or env.company.currency_id
        monto = currency.round(precio * porcentaje / 100.0)
        if (rows[line.id][1] is None
                or currency.compare_amounts(float(price_unit or 0.0), monto)
                or currency.compare_amounts(float(technical or 0.0), monto)):
            cr.execute("""
                UPDATE sale_order_line
                   SET porcentaje_cobertura = %s, precio_servicio_pvm = %s,
                       price_unit = %s, technical_price_unit = %s
                 WHERE id = %s
            """, (porcentaje, precio, monto, monto, line.id))
            cambiadas.append(line.id)

    if cambiadas:
        changed = env['sale.order.line'].browse(cambiadas)
        changed.invalidate_recordset(
            ['porcentaje_cobertura', 'precio_servicio_pvm', 'price_unit', 'technical_price_unit'])
        # Solo los dependientes de price_unit (importes); no vuelve a calcular
        # price_unit ni precio_servicio_pvm.
        changed.modified(['price_unit'])
        env.flush_all()
    _logger.info(
        '[rehalife_seguros 18.0.1.0.3] price_unit recalculado como monto de la aseguradora '
        'en %s de %s línea(s) de Pedido de Venta Marco.', len(cambiadas), len(line_ids),
    )
