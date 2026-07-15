import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatTipoDocumentoIdentidad(models.Model):
    _name = "alpha.siat.tipo.documento.identidad"
    _description = "SIAT - Tipos de Documento de Identidad"
    _order = "codigo_clasificador"
    _rec_name = "descripcion"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        string="Company"
    )

    codigo_clasificador = fields.Integer(
        string="Código Clasificador",
        required=True,
        index=True,
        help="Código del tipo de documento SIAT"
    )

    descripcion = fields.Char(
        string="Descripción",
        required=True,
        help="Descripción del tipo de documento de identidad"
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
        ('uniq_codigo_clasificador_company',
         'UNIQUE(company_id, codigo_clasificador)',
         'El código clasificador debe ser único por compañía')
    ]

    def name_get(self):
        """Display format: Description"""
        result = []
        for record in self:
            name = record.descripcion
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by code or description"""
        args = args or []
        if name:
            # Try to convert to int for code search
            try:
                code = int(name)
                args = ['|', ('codigo_clasificador', '=', code), ('descripcion', operator, name)] + args
            except ValueError:
                args = [('descripcion', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def get_tipo_documento_by_codigo(self, codigo):
        """
        Get document type description by code

        :param codigo: Document type code (int or str)
        :return: Document type description string or None
        """
        try:
            codigo = int(codigo)
        except (ValueError, TypeError):
            return None

        tipo_doc = self.search([
            ('codigo_clasificador', '=', codigo),
            ('active', '=', True)
        ], limit=1)

        return tipo_doc.descripcion if tipo_doc else None

    @api.model
    def get_codigo_ci(self):
        """
        Get CI (Cédula de Identidad) code - convenience method

        :return: CI code (1) or None
        """
        ci = self.search([
            ('descripcion', 'ilike', 'CI'),
            ('descripcion', 'ilike', 'CEDULA'),
            ('active', '=', True)
        ], limit=1)

        return ci.codigo_clasificador if ci else 1  # Default to 1

    @api.model
    def get_codigo_nit(self):
        """
        Get NIT code - convenience method

        :return: NIT code (5) or None
        """
        nit = self.search([
            ('descripcion', 'ilike', 'NIT'),
            ('active', '=', True)
        ], limit=1)

        return nit.codigo_clasificador if nit else 5  # Default to 5

    @api.model
    def sync_from_siat_response(self, company, tipos_list):
        """
        Synchronize document types from SIAT response

        :param company: res.company record
        :param tipos_list: list of dicts with codigoClasificador, descripcion
        :return: dict with statistics
        """
        if not tipos_list:
            _logger.warning("No document types to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing codes for this company
        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_clasificador: rec for rec in existing_records}
        synced_codes = set()

        for tipo_data in tipos_list:
            codigo = tipo_data.get('codigoClasificador', '')

            # Convert to int
            try:
                codigo = int(codigo)
            except (ValueError, TypeError):
                _logger.warning(f"Invalid codigoClasificador: {codigo}")
                continue

            synced_codes.add(codigo)

            vals = {
                'company_id': company.id,
                'codigo_clasificador': codigo,
                'descripcion': tipo_data.get('descripcion', '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if codigo in existing_codes:
                # Update existing record
                existing_rec = existing_codes[codigo]
                # Only update if something changed
                if (existing_rec.descripcion != vals['descripcion'] or
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
                ('codigo_clasificador', 'in', list(codes_to_deactivate)),
                ('active', '=', True)
            ])
            if records_to_deactivate:
                records_to_deactivate.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })
                deactivated = len(records_to_deactivate)

        _logger.info(
            "SIAT Document Types sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_codes)
        }