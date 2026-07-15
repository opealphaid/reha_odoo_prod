import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatActividadDocumentoSector(models.Model):
    _name = "alpha.siat.actividad.documento.sector"
    _description = "SIAT - Actividades por Documento Sector"
    _order = "codigo_actividad, codigo_documento_sector"
    _rec_name = "tipo_documento_sector"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        string="Company"
    )

    codigo_actividad = fields.Char(
        string="Código Actividad (CAEB)",
        required=True,
        index=True,
        help="Código de Actividad Económica de Bolivia"
    )

    actividad_id = fields.Many2one(
        "alpha.siat.actividad",
        string="Actividad Económica",
        compute="_compute_actividad_id",
        store=True,
        help="Relación con la actividad económica"
    )

    codigo_documento_sector = fields.Integer(
        string="Código Documento Sector",
        required=True,
        index=True,
        help="Código del tipo de documento/factura sectorial"
    )

    tipo_documento_sector = fields.Char(
        string="Tipo Documento Sector",
        required=True,
        help="Tipo de documento/factura (FCV, NCD, NCDDE, etc.)"
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
        ('uniq_actividad_documento',
         'UNIQUE(company_id, codigo_actividad, codigo_documento_sector)',
         'La combinación de actividad y documento sector debe ser única por compañía')
    ]

    @api.depends('codigo_actividad', 'company_id')
    def _compute_actividad_id(self):
        """Link to alpha.siat.actividad if exists"""
        for record in self:
            if record.codigo_actividad and record.company_id:
                actividad = self.env['alpha.siat.actividad'].search([
                    ('codigo_caeb', '=', record.codigo_actividad),
                    ('company_id', '=', record.company_id.id)
                ], limit=1)
                record.actividad_id = actividad.id if actividad else False
            else:
                record.actividad_id = False

    def name_get(self):
        """Display format: [CAEB] Tipo Documento"""
        result = []
        for record in self:
            name = f"[{record.codigo_actividad}] {record.tipo_documento_sector}"
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by activity code or document type"""
        args = args or []
        if name:
            args = ['|',
                    ('codigo_actividad', operator, name),
                    ('tipo_documento_sector', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def sync_from_siat_response(self, company, actividades_documento_list):
        """
        Synchronize activity-document relationships from SIAT response

        :param company: res.company record
        :param actividades_documento_list: list of dicts with codigoActividad, codigoDocumentoSector, tipoDocumentoSector
        :return: dict with statistics
        """
        if not actividades_documento_list:
            _logger.warning("No activity-document relationships to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing records for this company
        existing_records = self.search([('company_id', '=', company.id)])
        existing_keys = {
            (rec.codigo_actividad, rec.codigo_documento_sector): rec
            for rec in existing_records
        }
        synced_keys = set()

        for act_doc_data in actividades_documento_list:
            codigo_act = act_doc_data.get('codigoActividad', '').strip()
            codigo_doc = act_doc_data.get('codigoDocumentoSector', '')

            if not codigo_act or not codigo_doc:
                continue

            # Convert to int if it's a string
            try:
                codigo_doc = int(codigo_doc)
            except (ValueError, TypeError):
                _logger.warning(f"Invalid codigoDocumentoSector: {codigo_doc}")
                continue

            key = (codigo_act, codigo_doc)
            synced_keys.add(key)

            vals = {
                'company_id': company.id,
                'codigo_actividad': codigo_act,
                'codigo_documento_sector': codigo_doc,
                'tipo_documento_sector': act_doc_data.get('tipoDocumentoSector', '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if key in existing_keys:
                # Update existing record
                existing_rec = existing_keys[key]
                # Only update if something changed
                if (existing_rec.tipo_documento_sector != vals['tipo_documento_sector'] or
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
        keys_to_deactivate = set(existing_keys.keys()) - synced_keys
        deactivated = 0
        if keys_to_deactivate:
            records_to_deactivate = self.browse([
                existing_keys[key].id for key in keys_to_deactivate
                if existing_keys[key].active
            ])
            if records_to_deactivate:
                records_to_deactivate.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })
                deactivated = len(records_to_deactivate)

        _logger.info(
            "SIAT Activity-Document sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_keys)
        }