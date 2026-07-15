# alpha_siat/models/siat_tipo_emision.py
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class SiatTipoEmision(models.Model):
    _name = "alpha.siat.tipo.emision"
    _description = "SIAT - Tipos de Emisión"
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
        help="Código SIAT del tipo de emisión"
    )

    descripcion = fields.Char(
        string="Descripción",
        required=True,
        help="Descripción del tipo de emisión (EN LINEA, FUERA DE LINEA, CONTINGENCIA, ...)"
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

    # Optional: mapping to internal usage (e.g. emission mode)
    internal_code = fields.Selection(
        [('online', 'EN LINEA'), ('offline', 'FUERA DE LINEA'), ('contingency', 'CONTINGENCIA'), ('mass', 'MASIVO'), ('other', 'OTRO')],
        string="Mapa interno (sugerido)",
        help="Sugerencia para mapear a la lógica interna de emisión"
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
        Synchronize TipoEmision from SIAT response.
        tipos_list: [{'codigoClasificador': '1', 'descripcion': 'EN LINEA'}, ...]
        """
        if not tipos_list:
            _logger.warning("No tipos emision to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = updated = 0
        sync_time = fields.Datetime.now()

        existing = self.search([('company_id', '=', company.id)])
        existing_map = {rec.codigo_clasificador: rec for rec in existing}
        synced_codes = set()

        for t in tipos_list:
            codigo = t.get('codigoClasificador', '')
            try:
                codigo = int(codigo)
            except (ValueError, TypeError):
                _logger.warning("Invalid codigoClasificador for tipo emision: %s", codigo)
                continue

            synced_codes.add(codigo)
            vals = {
                'company_id': company.id,
                'codigo_clasificador': codigo,
                'descripcion': (t.get('descripcion') or '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if codigo in existing_map:
                rec = existing_map[codigo]
                if rec.descripcion != vals['descripcion'] or not rec.active:
                    rec.write(vals)
                    updated += 1
                else:
                    rec.write({'ultima_sincronizacion': sync_time})
            else:
                self.create(vals)
                created += 1

        # Deactivate removed codes
        to_deactivate = set(existing_map.keys()) - synced_codes
        deactivated = 0
        if to_deactivate:
            recs = self.search([
                ('company_id', '=', company.id),
                ('codigo_clasificador', 'in', list(to_deactivate)),
                ('active', '=', True)
            ])
            if recs:
                recs.write({'active': False, 'ultima_sincronizacion': sync_time})
                deactivated = len(recs)

        _logger.info("SIAT TipoEmision sync for %s: %d created, %d updated, %d deactivated",
                     company.name, created, updated, deactivated)

        return {'created': created, 'updated': updated, 'deactivated': deactivated, 'total_synced': len(synced_codes)}
