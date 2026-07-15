# alpha_siat/models/siat_cuis.py
import json
from datetime import timedelta
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SiatCuis(models.Model):
    _name = "alpha.siat.cuis"
    _description = "CUIS por Sucursal y Punto de Venta"
    _order = "fecha_vigencia desc"

    company_id = fields.Many2one("res.company", required=True, index=True)
    codigo_sucursal = fields.Integer(required=True, index=True)
    codigo_punto_venta = fields.Integer(required=True, index=True)
    modalidad = fields.Selection([('1','Electrónica'),('2','Computarizada')], required=True, index=True)
    cuis = fields.Char("CUIS", required=True, index=True)
    fecha_vigencia = fields.Datetime("Fecha Vigencia", required=True)
    mensajes = fields.Text()
    raw_response = fields.Text(string="Raw Response")
    state = fields.Selection([('valid','Válido'),('expired','Expirado'),('error','Error')], default='valid', index=True)
    archived = fields.Boolean(string="Archived", default=False, help="When true this record was superseded by a newer CUIS")

    _sql_constraints = [
        ('uniq_cuis','UNIQUE(company_id,codigo_sucursal,codigo_punto_venta,modalidad,cuis)',
         'The same CUIS should not be stored twice for the same combination')
    ]

    @api.model
    def _mark_existing_as_archived(self, company_id, sucursal, punto, modalidad):
        domain = [
            ('company_id', '=', company_id),
            ('codigo_sucursal', '=', sucursal),
            ('codigo_punto_venta', '=', punto),
            ('modalidad', '=', modalidad),
            ('state', '=', 'valid'),
            ('archived', '=', False),
        ]
        recs = self.search(domain)
        if recs:
            recs.write({'state': 'expired', 'archived': True})

    @api.model
    def _validate_before_request(self, company, config, modalidad):
        missing = []
        if not (config.wsdl_codigos or '').strip():
            missing.append("wsdl_codigos (service URL)")
        if not (config.codigo_sistema or '').strip():
            missing.append("codigo_sistema (SIAT system code)")
        company_nit = (company.vat or '').strip()
        if not company_nit:
            partner_vat = (company.partner_id.vat or '').strip() if company.partner_id else ''
            if partner_vat:
                company_nit = partner_vat
        if not company_nit:
            missing.append("company NIT (company.vat or partner.vat)")
        if not modalidad:
            missing.append("modalidad (config.modalidad)")
        if missing:
            raise UserError("Cannot request CUIS. Missing required configuration/fields: %s" % (", ".join(missing)))

    @api.model
    def get_or_fetch_cuis(self, company, codigo_modalidad=None, safety_minutes=5):
        if isinstance(company, (int,)):
            company = self.env['res.company'].browse(company)
        if not company or not company.exists():
            raise UserError("Invalid company for CUIS request")
        config = company.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("SIAT configuration not found. Please create a SIAT configuration and assign it to the company or create one globally.")

        modalidad = codigo_modalidad or (config.modalidad and str(config.modalidad)) or None
        if modalidad and isinstance(modalidad, int):
            modalidad = str(modalidad)

        sucursal = int(company.siat_codigo_sucursal or 0)
        punto = int(company.siat_codigo_punto_venta or 0)
        self._validate_before_request(company, config, modalidad)
        safety_delta = timedelta(minutes=int(safety_minutes))
        now_dt = fields.Datetime.now()
        rec = self.search([
            ('company_id', '=', company.id),
            ('codigo_sucursal', '=', sucursal),
            ('codigo_punto_venta', '=', punto),
            ('modalidad', '=', modalidad),
            ('state', '=', 'valid'),
            ('archived', '=', False),
        ], order='fecha_vigencia desc', limit=1)

        if rec:
            fv = rec.fecha_vigencia
            if fv and fv > (now_dt + safety_delta):
                return rec.cuis
            else:
                rec.write({'state': 'expired', 'archived': True})
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_cuis(company, config)
        if not resp or resp.get('error'):
            try:
                self.create({
                    'company_id': company.id,
                    'codigo_sucursal': sucursal,
                    'codigo_punto_venta': punto,
                    'modalidad': modalidad,
                    'cuis': resp.get('codigo') if resp and resp.get('codigo') else '',
                    'fecha_vigencia': fields.Datetime.now(),
                    'mensajes': (resp.get('mensajes') if resp else 'No response from service') or '',
                    'raw_response': (resp.get('raw') if resp else '') or '',
                    'state': 'error',
                    'archived': False,
                })
            except Exception as e:
                _logger.exception("Failed to create CUIS error record: %s", e)
            raise UserError("Error obtaining CUIS: %s" % ((resp.get('mensajes') if resp else 'No response') or 'Unknown error'))
        self._mark_existing_as_archived(company.id, sucursal, punto, modalidad)
        new_vals = {
            'company_id': company.id,
            'codigo_sucursal': sucursal,
            'codigo_punto_venta': punto,
            'modalidad': modalidad,
            'cuis': resp['codigo'],
            'fecha_vigencia': resp.get('vigencia') or fields.Datetime.now(),
            'mensajes': resp.get('mensajes') or '',
            'raw_response': json.dumps(resp.get('raw') or resp),
            'state': 'valid',
            'archived': False,
        }
        new = self.create(new_vals)
        return new.cuis
