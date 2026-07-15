# -*- coding: utf-8 -*-
from odoo import models, fields


class RehalifeSyncWizard(models.TransientModel):
    _name = 'rehalife.sync.wizard'
    _description = 'Asistente de Sincronizacion Rehalife'

    sync_cities = fields.Boolean(string='Sincronizar Ciudades', default=True)
    sync_patients = fields.Boolean(string='Sincronizar Pacientes', default=True)
    result_message = fields.Text(string='Resultado', readonly=True)
    state = fields.Selection(
        [('draft', 'Configurar'), ('done', 'Completado')],
        default='draft',
    )

    def action_sync(self):
        self.ensure_one()
        messages = []

        if self.sync_cities:
            result = self.env['rehalife.city'].sync_from_backend()
            messages.append(
                'Ciudades: %d creadas, %d actualizadas.' % (result['created'], result['updated'])
            )
        if self.sync_patients:
            result = self.env['rehalife.patient'].sync_from_backend()
            messages.append(
                'Pacientes: %d creados, %d actualizados, %d omitidos.' % (
                    result['created'], result['updated'], result['skipped']
                )
            )

        self.write({
            'result_message': '\n'.join(messages) or 'Nada seleccionado.',
            'state': 'done',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
