from . import models

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Migra company.siat_codigo_sucursal/punto_venta a una Sucursal SIAT
    ('Sucursal Principal') por compañía, y le asigna esa sucursal a las
    facturas/órdenes ya emitidas (siat_numero_factura ya seteado) para que
    la numeración por sucursal (alpha.siat.sucursal.get_next_numero_factura)
    continúe desde donde iba, en vez de reiniciar en 1.

    Idempotente: no crea ni reasigna nada si ya existe.
    """
    Sucursal = env['alpha.siat.sucursal']

    for company in env['res.company'].search([]):
        codigo_sucursal = company.siat_codigo_sucursal or 0
        codigo_punto_venta = company.siat_codigo_punto_venta or 0

        sucursal = Sucursal.search([
            ('company_id', '=', company.id),
            ('codigo_sucursal', '=', codigo_sucursal),
            ('codigo_punto_venta', '=', codigo_punto_venta),
        ], limit=1)

        if not sucursal:
            sucursal = Sucursal.create({
                'name': 'Sucursal Principal',
                'company_id': company.id,
                'codigo_sucursal': codigo_sucursal,
                'codigo_punto_venta': codigo_punto_venta,
            })
            _logger.info(
                "alpha_siat post_init_hook: creada Sucursal Principal (Suc. %s / PDV %s) para %s",
                codigo_sucursal, codigo_punto_venta, company.name
            )

        moves_sin_sucursal = env['account.move'].search([
            ('company_id', '=', company.id),
            ('siat_numero_factura', '!=', False),
            ('siat_sucursal_id', '=', False),
        ])
        if moves_sin_sucursal:
            moves_sin_sucursal.write({'siat_sucursal_id': sucursal.id})
            _logger.info(
                "alpha_siat post_init_hook: %d account.move existentes asignados a '%s' (%s)",
                len(moves_sin_sucursal), sucursal.name, company.name
            )

        orders_sin_sucursal = env['pos.order'].search([
            ('company_id', '=', company.id),
            ('siat_numero_factura', '>', 0),
            ('siat_sucursal_id', '=', False),
        ])
        if orders_sin_sucursal:
            orders_sin_sucursal.write({'siat_sucursal_id': sucursal.id})
            _logger.info(
                "alpha_siat post_init_hook: %d pos.order existentes asignadas a '%s' (%s)",
                len(orders_sin_sucursal), sucursal.name, company.name
            )