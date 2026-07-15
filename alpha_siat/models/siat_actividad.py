import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatActividad(models.Model):
    _name = "alpha.siat.actividad"
    _description = "SIAT - Actividades Económicas (CAEB)"
    _order = "codigo_caeb"
    _rec_name = "descripcion"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        string="Company"
    )

    codigo_caeb = fields.Char(
        string="Código CAEB",
        required=True,
        index=True,
        help="Código de Actividad Económica de Bolivia"
    )
    descripcion = fields.Char(
        string="Descripción",
        required=True,
        help="Descripción de la actividad económica"
    )
    tipo_actividad = fields.Selection(
        [('P', 'Principal'), ('S', 'Secundaria')],
        string="Tipo de Actividad",
        required=True,
        index=True,
        help="P = Actividad Principal, S = Actividad Secundaria"
    )

    active = fields.Boolean(
        default=True,
        help="Si está inactivo, significa que ya no existe en SIAT"
    )

    ultima_sincronizacion = fields.Datetime(
        string="Última Sincronización",
        readonly=True,
        help="Fecha y hora de la última sincronización con SIAT"
    )

    _sql_constraints = [
        ('uniq_codigo_caeb_company',
         'UNIQUE(company_id, codigo_caeb)',
         'El código CAEB debe ser único por compañía')
    ]

    def name_get(self):
        """Display format: [CODE] Description"""
        result = []
        for record in self:
            name = f"[{record.codigo_caeb}] {record.descripcion}"
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by code or description"""
        args = args or []
        if name:
            args = ['|', ('codigo_caeb', operator, name), ('descripcion', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def sync_from_siat_response(self, company, actividades_list):
        """
        Synchronize activities from SIAT response

        :param company: res.company record
        :param actividades_list: list of dicts with codigoCaeb, descripcion, tipoActividad
        :return: dict with statistics
        """
        if not actividades_list:
            _logger.warning("No activities to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing codes for this company
        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_caeb: rec for rec in existing_records}
        synced_codes = set()

        for act_data in actividades_list:
            codigo = act_data.get('codigoCaeb', '').strip()
            if not codigo:
                continue

            synced_codes.add(codigo)

            vals = {
                'company_id': company.id,
                'codigo_caeb': codigo,
                'descripcion': act_data.get('descripcion', '').strip(),
                'tipo_actividad': act_data.get('tipoActividad', 'S').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if codigo in existing_codes:
                # Update existing record
                existing_rec = existing_codes[codigo]
                # Only update if something changed
                if (existing_rec.descripcion != vals['descripcion'] or
                        existing_rec.tipo_actividad != vals['tipo_actividad'] or
                        not existing_rec.active):
                    existing_rec.write(vals)
                    updated += 1
                else:
                    # Just update sync time
                    existing_rec.write({'ultima_sincronizacion': sync_time})
            else:
                # Create new record
                self.create(vals)
                created += 1

        # Deactivate records that are no longer in SIAT
        codes_to_deactivate = set(existing_codes.keys()) - synced_codes
        deactivated = 0
        if codes_to_deactivate:
            records_to_deactivate = self.search([
                ('company_id', '=', company.id),
                ('codigo_caeb', 'in', list(codes_to_deactivate)),
                ('active', '=', True)
            ])
            if records_to_deactivate:
                records_to_deactivate.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })
                deactivated = len(records_to_deactivate)

        _logger.info(
            "SIAT Activities sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_codes)
        }