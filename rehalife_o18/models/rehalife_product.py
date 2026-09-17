# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    rehalife_external_id = fields.Char(
        string='ID Externo (Service Type)',
        index=True,
        copy=False,
    )
    rehalife_sync_state = fields.Selection(
        selection=[
            ('draft', 'No sincronizado'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado Sync Rehalife',
        default='draft',
        readonly=True,
    )
    rehalife_sync_error = fields.Text(string='Error de Sync', readonly=True)
    rehalife_last_sync = fields.Datetime(string='Ultima Sincronizacion', readonly=True)

    _sql_constraints = [
        ('rehalife_external_id_uniq', 'UNIQUE(rehalife_external_id)',
         'Ya existe un producto sincronizado con ese Service Type.'),
    ]

    # ──────────────────────────────────────────────
    #  SYNC: Backend (Next.js) → Odoo
    # ──────────────────────────────────────────────

    @api.model
    def sync_service_types_from_backend(self):
        """Importa y actualiza los Service Types del backend como productos."""
        api_service = self.env['rehalife.api']
        service_types = api_service.get_service_types()
        created = updated = skipped = 0
        for service_type in service_types:
            ext_id = service_type.get('id')
            if not ext_id:
                skipped += 1
                continue

            price = service_type.get('price')
            has_price = price is not None
            vals = {
                'name': service_type.get('name', ''),
                'default_code': service_type.get('reference') or False,
                'list_price': float(price) if has_price else 0.0,
                'rehalife_external_id': str(ext_id),
                'rehalife_last_sync': fields.Datetime.now(),
            }
            if has_price:
                vals['rehalife_sync_state'] = 'synced'
                vals['rehalife_sync_error'] = False
            else:
                # No bloquea la sincronizacion, pero deja evidencia de que el
                # producto quedo a precio 0 porque el backend aun no tiene un
                # precio definido para este servicio.
                vals['rehalife_sync_state'] = 'draft'
                vals['rehalife_sync_error'] = 'Sin precio definido en el backend.'

            existing = self.search([('rehalife_external_id', '=', str(ext_id))], limit=1)
            if existing:
                # No se pisa sale_ok/available_in_pos: si contabilidad ya
                # homologó y activó el producto a mano, el sync no debe
                # desactivarlo ni reactivarlo.
                existing.write(vals)
                updated += 1
            else:
                # Nace como borrador (no vendible): la homologación SIAT
                # (Código de Producto, Actividad Económica, Unidad de Medida)
                # es distinta por servicio y no se puede autoasignar, así que
                # queda como paso manual de contabilidad por producto.
                vals.update({
                    'type': 'service',
                    'sale_ok': False,
                    'purchase_ok': False,
                    'available_in_pos': False,
                    'taxes_id': [(5, 0, 0)],
                })
                self.create(vals)
                created += 1

        pending_homologation = self.search_count([
            ('rehalife_external_id', '!=', False),
            ('siat_homologado', '=', False),
        ])

        _logger.info(
            'Rehalife service types: %d creados, %d actualizados, %d omitidos, '
            '%d pendientes de homologacion SIAT.',
            created, updated, skipped, pending_homologation,
        )
        return {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'pending_homologation': pending_homologation,
        }
