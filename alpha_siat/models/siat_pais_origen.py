import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatPaisOrigen(models.Model):
    _name = "alpha.siat.pais.origen"
    _description = "SIAT - Países de Origen"
    _order = "descripcion"
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
        help="Código del país SIAT"
    )

    descripcion = fields.Char(
        string="País",
        required=True,
        index=True,
        help="Nombre del país"
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
        """Display format: Country Name [CODE]"""
        result = []
        for record in self:
            name = f"{record.descripcion} [{record.codigo_clasificador}]"
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by code or country name"""
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
    def get_pais_by_codigo(self, codigo):
        """
        Get country name by code

        :param codigo: Country code (int or str)
        :return: Country name string or None
        """
        try:
            codigo = int(codigo)
        except (ValueError, TypeError):
            return None

        pais = self.search([
            ('codigo_clasificador', '=', codigo),
            ('active', '=', True)
        ], limit=1)

        return pais.descripcion if pais else None

    @api.model
    def get_codigo_bolivia(self):
        """
        Get Bolivia's country code (convenience method)

        :return: Bolivia's code (22) or None
        """
        bolivia = self.search([
            ('descripcion', 'ilike', 'bolivia'),
            ('active', '=', True)
        ], limit=1)

        return bolivia.codigo_clasificador if bolivia else 22  # Default to 22

    @api.model
    def sync_from_siat_response(self, company, paises_list):
        """
        Synchronize countries from SIAT response

        :param company: res.company record
        :param paises_list: list of dicts with codigoClasificador, descripcion
        :return: dict with statistics
        """
        if not paises_list:
            _logger.warning("No countries to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing codes for this company
        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_clasificador: rec for rec in existing_records}
        synced_codes = set()

        for pais_data in paises_list:
            codigo = pais_data.get('codigoClasificador', '')

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
                'descripcion': pais_data.get('descripcion', '').strip(),
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
            "SIAT Countries sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_codes)
        }