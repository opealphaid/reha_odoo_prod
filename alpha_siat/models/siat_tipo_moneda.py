# alpha_siat/models/siat_tipo_moneda.py
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class SiatTipoMoneda(models.Model):
    _name = "alpha.siat.tipo.moneda"
    _description = "SIAT - Tipos de Moneda"
    _order = "codigo_clasificador"
    _rec_name = "descripcion"

    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company, string="Company"
    )

    codigo_clasificador = fields.Integer(
        string="Código Clasificador", required=True, index=True,
        help="Código del tipo de moneda SIAT"
    )

    descripcion = fields.Char(
        string="Descripción", required=True,
        help="Descripción de la moneda"
    )

    active = fields.Boolean(
        default=True,
        help="Si está inactivo, significa que ya no existe en SIAT"
    )

    ultima_sincronizacion = fields.Datetime(
        string="Última Sincronización", readonly=True,
        help="Fecha y hora de la última sincronización con SIAT"
    )

    _sql_constraints = [
        ('uniq_codigo_clasificador_company',
         'UNIQUE(company_id, codigo_clasificador)',
         'El código clasificador debe ser único por compañía')
    ]

    def name_get(self):
        return [(r.id, r.descripcion) for r in self]

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if name:
            try:
                code = int(name)
                args = ['|', ('codigo_clasificador', '=', code), ('descripcion', operator, name)] + args
            except ValueError:
                args = [('descripcion', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def sync_from_siat_response(self, company, tipos_list):
        """
        Synchronize currencies from SIAT response.
        tipos_list: [{'codigoClasificador': '1', 'descripcion': 'BOLIVIANO'}, ...]
        """
        if not tipos_list:
            _logger.warning("No currencies to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = updated = 0
        sync_time = fields.Datetime.now()

        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_clasificador: rec for rec in existing_records}
        synced_codes = set()

        for tipo in tipos_list:
            codigo = tipo.get('codigoClasificador', '')
            try:
                codigo = int(codigo)
            except (ValueError, TypeError):
                _logger.warning("Invalid codigoClasificador for tipo moneda: %s", codigo)
                continue

            synced_codes.add(codigo)
            vals = {
                'company_id': company.id,
                'codigo_clasificador': codigo,
                'descripcion': (tipo.get('descripcion') or '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if codigo in existing_codes:
                rec = existing_codes[codigo]
                if (rec.descripcion != vals['descripcion'] or not rec.active):
                    rec.write(vals)
                    updated += 1
                else:
                    rec.write({'ultima_sincronizacion': sync_time})
            else:
                self.create(vals)
                created += 1

        codes_to_deactivate = set(existing_codes.keys()) - synced_codes
        deactivated = 0
        if codes_to_deactivate:
            to_deactivate = self.search([
                ('company_id', '=', company.id),
                ('codigo_clasificador', 'in', list(codes_to_deactivate)),
                ('active', '=', True)
            ])
            if to_deactivate:
                to_deactivate.write({'active': False, 'ultima_sincronizacion': sync_time})
                deactivated = len(to_deactivate)

        _logger.info("SIAT TipoMoneda sync for %s: %d created, %d updated, %d deactivated",
                     company.name, created, updated, deactivated)

        return {'created': created, 'updated': updated, 'deactivated': deactivated, 'total_synced': len(synced_codes)}

    # Convenience helpers
    @api.model
    def get_codigo_boliviano(self, company=None):
        """Return SIAT code for BOLIVIANO; default to 1 if not found."""
        domain = [('descripcion', 'ilike', 'BOLIVIANO'), ('active', '=', True)]
        if company:
            domain = [('company_id', '=', company.id)] + domain
        rec = self.search(domain, limit=1)
        return rec.codigo_clasificador if rec else 1

    @api.model
    def get_codigo_dolar(self, company=None):
        """Return SIAT code for DÓLAR/US Dollar; default to 2 if not found."""
        domain = [('descripcion', 'ilike', 'DÓLAR'), ('active', '=', True)]
        if company:
            domain = [('company_id', '=', company.id)] + domain
        rec = self.search(domain, limit=1)
        return rec.codigo_clasificador if rec else 2
