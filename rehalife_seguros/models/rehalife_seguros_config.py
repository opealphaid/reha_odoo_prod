# -*- coding: utf-8 -*-
from odoo import models


class RehalifeSegurosSyncWizard(models.TransientModel):
    _name = 'rehalife.seguros.sync.wizard'
    _description = 'Sincronizacion Rehalife Seguros'

    def action_sync_insurance_providers(self):
        result = self.env['res.partner'].sync_insurance_providers_from_backend()
        message = '%d creada(s), %d actualizada(s).' % (
            result['created'], result['updated'],
        )
        if result['created']:
            message += (
                '\n⚠️ Las aseguradoras nuevas se crearon con NIT placeholder '
                '"0000000" (el backend no maneja NIT) — corrígelo en cada una '
                'desde Seguros > Aseguradoras antes de facturarles de verdad.'
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Aseguradoras sincronizadas',
                'message': message,
                'type': 'warning' if result['created'] else 'success',
                'sticky': bool(result['created']),
            },
        }

    def action_sync_patient_insurances(self):
        result = self.env['res.partner'].sync_patient_insurances_from_backend()
        message = '%d paciente(s) actualizados (%d aseguradora(s) revisadas).' % (
            result['updated'], result['providers_checked'],
        )
        if result['skipped']:
            message += (
                '\n⚠️ %d afiliación(es) omitidas (paciente sin espejo en Odoo).'
                % result['skipped']
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pacientes asegurados sincronizados',
                'message': message,
                'type': 'warning' if result['skipped'] else 'success',
                'sticky': bool(result['skipped']),
            },
        }
