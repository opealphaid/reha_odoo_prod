# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_aseguradora = fields.Boolean(string='Es Aseguradora', default=False, tracking=True)

    aseguradora_id = fields.Many2one(
        'res.partner', string='Aseguradora',
        domain="[('is_aseguradora', '=', True)]",
    )
    numero_poliza = fields.Char(string='Número de Póliza')
    poliza_vigencia_desde = fields.Date(string='Póliza Vigente Desde')
    poliza_vigencia_hasta = fields.Date(string='Póliza Vigente Hasta')

    # Inverso de aseguradora_id — permite ver, desde el contacto de la
    # aseguradora, qué pacientes están afiliados a ella.
    paciente_ids = fields.One2many(
        'res.partner', 'aseguradora_id', string='Pacientes Asegurados',
    )

    @api.constrains('is_aseguradora', 'vat')
    def _check_aseguradora_required_fields(self):
        for rec in self:
            if rec.is_aseguradora and not rec.vat:
                raise ValidationError(
                    'Las aseguradoras requieren un NIT (campo "vat") para poder '
                    'facturarles.'
                )

    # NIT placeholder para aseguradoras nuevas: el backend Rehalife no expone
    # NIT y 'vat' es required=True en alpha_siat para cualquier partner. Mismo
    # sentinel que ya usa alpha_siat/models/res_partner.py para
    # siat_nit_facturacion ("sin datos de facturación configurados") — no se
    # inventa una segunda convención. Hay que corregirlo a mano antes de
    # facturarle de verdad a esa aseguradora.
    _NIT_PLACEHOLDER = '0000000'

    @api.model
    def sync_insurance_providers_from_backend(self):
        """Importa/actualiza aseguradoras (res.partner con is_aseguradora=True)
        desde el backend Rehalife. Las que no tienen espejo en Odoo se crean
        con NIT placeholder (ver _NIT_PLACEHOLDER) para no romper el
        required=True de vat; el NIT real se corrige a mano en Odoo."""
        providers_data = self.env['rehalife.api'].get_insurance_providers()
        ctx = {'skip_rehalife_sync': True}

        tipo_nit = self.env['alpha.siat.tipo.documento.identidad'].search(
            [('codigo_clasificador', '=', 5), ('active', '=', True)], limit=1
        )

        created = updated = 0
        for p in providers_data:
            ext_id = p.get('id')
            if not ext_id:
                continue

            vals = {
                'name': p.get('name', ''),
                'email': p.get('contactEmail') or False,
                'phone': p.get('contactPhone') or False,
            }

            existing = self.search(
                [('rehalife_external_id', '=', ext_id)], limit=1
            )
            if existing:
                existing.with_context(**ctx).write(vals)
                updated += 1
                continue

            vals.update({
                'is_aseguradora': True,
                'is_company': True,
                'vat': self._NIT_PLACEHOLDER,
                'siat_tipo_documento_identidad_id': tipo_nit.id if tipo_nit else False,
                'rehalife_external_id': ext_id,
            })
            self.with_context(**ctx).create(vals)
            created += 1

        _logger.info(
            'Rehalife Seguros sync aseguradoras: %d creadas (NIT placeholder '
            'pendiente de corregir), %d actualizadas.', created, updated,
        )
        return {'created': created, 'updated': updated}

    @api.model
    def sync_patient_insurances_from_backend(self):
        """Actualiza aseguradora_id de los pacientes ya reflejados en Odoo,
        recorriendo GET /patient-insurances/insurance-provider/:id por cada
        aseguradora ya sincronizada — el backend no expone un listado global
        de afiliaciones."""
        api_service = self.env['rehalife.api']
        ctx = {'skip_rehalife_sync': True}

        providers = self.search([
            ('is_aseguradora', '=', True),
            ('rehalife_external_id', '!=', False),
        ])

        updated = skipped = 0
        for provider in providers:
            affiliations = api_service.get_patient_insurances_by_provider(
                provider.rehalife_external_id
            )
            for aff in affiliations:
                patient_ext_id = (aff.get('patient') or {}).get('id')
                if not patient_ext_id:
                    skipped += 1
                    continue

                patient = self.search(
                    [('rehalife_external_id', '=', patient_ext_id)], limit=1
                )
                if not patient:
                    skipped += 1
                    continue

                if patient.aseguradora_id.id != provider.id:
                    patient.with_context(**ctx).write(
                        {'aseguradora_id': provider.id}
                    )
                    updated += 1

        _logger.info(
            'Rehalife Seguros sync afiliaciones: %d actualizadas, %d omitidas '
            '(paciente sin espejo en Odoo), %d aseguradora(s) revisadas.',
            updated, skipped, len(providers),
        )
        return {
            'updated': updated,
            'skipped': skipped,
            'providers_checked': len(providers),
        }
