# -*- coding: utf-8 -*-
import logging
from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RehalifeImportReservationsWizard(models.TransientModel):
    _name = 'rehalife.import.reservations.wizard'
    _description = 'Importar Reservas Completadas desde Next.js'

    date_from = fields.Date(string='Fecha Desde', required=True)
    date_to = fields.Date(string='Fecha Hasta', required=True)
    result_message = fields.Text(string='Resultado', readonly=True)
    state = fields.Selection(
        [('draft', 'Configurar'), ('done', 'Completado')],
        default='draft',
    )

    def action_import(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError('La fecha de inicio no puede ser posterior a la fecha de fin.')

        reservations_data = self.env['rehalife.api'].get_completed_reservations(
            self.date_from.isoformat(), self.date_to.isoformat()
        )

        Reservation = self.env['rehalife.reservation']
        created_ids = []
        updated_to_paid_ids = []
        skipped_ids = []
        error_lines = []

        for raw in reservations_data:
            ext_id = raw.get('id', '?')
            try:
                with self.env.cr.savepoint():
                    result = Reservation.import_from_nextjs(raw)
                action = result.get('action')
                if action == 'created':
                    created_ids.append(ext_id)
                elif action == 'updated_to_paid':
                    updated_to_paid_ids.append(ext_id)
                else:
                    skipped_ids.append(ext_id)
            except Exception as e:
                error_lines.append('  - %s: %s' % (ext_id, str(e)))
                _logger.error('[ImportReservations] Error en reserva %s: %s', ext_id, str(e))

        lines = [
            'Reservas recibidas del backend: %d' % len(reservations_data),
            'Creadas en Odoo: %d' % len(created_ids),
            'Actualizadas a pagada: %d' % len(updated_to_paid_ids),
            'Ya existentes / omitidas: %d' % len(skipped_ids),
            'Errores: %d' % len(error_lines),
        ]
        if error_lines:
            lines.append('')
            lines.append('Detalle de errores:')
            lines.extend(error_lines)

        self.write({'result_message': '\n'.join(lines), 'state': 'done'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
