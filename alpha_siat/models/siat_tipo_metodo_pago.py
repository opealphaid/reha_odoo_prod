# alpha_siat/models/siat_tipo_metodo_pago.py
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class SiatTipoMetodoPago(models.Model):
    _name = "alpha.siat.tipo.metodo.pago"
    _description = "SIAT - Tipos de Método de Pago"
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
        help="Código del tipo de método de pago SIAT"
    )

    descripcion = fields.Char(
        string="Descripción",
        required=True,
        help="Descripción del método de pago"
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
        Synchronize payment methods from SIAT response.
        tipos_list: list of dicts {'codigoClasificador': '1', 'descripcion': 'EFECTIVO'}
        """
        if not tipos_list:
            _logger.warning("No payment methods to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_clasificador: rec for rec in existing_records}
        synced_codes = set()

        for tipo_data in tipos_list:
            codigo = tipo_data.get('codigoClasificador', '')
            try:
                codigo = int(codigo)
            except (ValueError, TypeError):
                _logger.warning("Invalid codigoClasificador for metodo pago: %s", codigo)
                continue

            synced_codes.add(codigo)
            vals = {
                'company_id': company.id,
                'codigo_clasificador': codigo,
                'descripcion': (tipo_data.get('descripcion') or '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if codigo in existing_codes:
                existing_rec = existing_codes[codigo]
                if (existing_rec.descripcion != vals['descripcion'] or not existing_rec.active):
                    existing_rec.write(vals)
                    updated += 1
                else:
                    existing_rec.write({'ultima_sincronizacion': sync_time})
            else:
                self.create(vals)
                created += 1

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
            "SIAT TipoMetodoPago sync for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_codes)
        }

    # Convenience helpers
    @api.model
    def get_codigo_efectivo(self, company=None):
        """Return code for EFECTIVO (cash). Defaults to 1 if not found."""
        domain = [('descripcion', 'ilike', 'EFECTIVO'), ('active', '=', True)]
        if company:
            domain = [('company_id', '=', company.id)] + domain
        rec = self.search(domain, limit=1)
        return rec.codigo_clasificador if rec else 1

    @api.model
    def get_codigo_tarjeta(self, company=None):
        """Return code for TARJETA (card). Defaults to 2 if not found."""
        domain = [('descripcion', 'ilike', 'TARJETA'), ('active', '=', True)]
        if company:
            domain = [('company_id', '=', company.id)] + domain
        rec = self.search(domain, limit=1)
        return rec.codigo_clasificador if rec else 2
