import json
from datetime import timedelta
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SiatCufd(models.Model):
    _name = "alpha.siat.cufd"
    _description = "CUFD - Código Único de Facturación Diaria"
    _order = "fecha_vigencia desc"

    company_id = fields.Many2one("res.company", required=True, index=True)
    codigo_sucursal = fields.Integer(required=True, index=True)
    codigo_punto_venta = fields.Integer(required=True, index=True)
    modalidad = fields.Selection(
        [('1', 'Electrónica'), ('2', 'Computarizada')],
        required=True,
        index=True
    )

    cufd = fields.Char("CUFD", required=True, index=True)
    codigo_control = fields.Char("Código Control", help="Control code returned by SIAT")
    direccion = fields.Char("Dirección", help="Address returned by SIAT")

    fecha_vigencia = fields.Datetime("Fecha Vigencia", required=True)
    fecha_expiracion = fields.Datetime("Fecha Expiración", compute="_compute_fecha_expiracion", store=True)

    mensajes = fields.Text()
    raw_response = fields.Text(string="Raw Response")

    state = fields.Selection(
        [('valid', 'Válido'), ('expired', 'Expirado'), ('error', 'Error')],
        default='valid',
        index=True
    )
    archived = fields.Boolean(
        string="Archived",
        default=False,
        help="When true this record was superseded by a newer CUFD"
    )

    _sql_constraints = [
        ('uniq_cufd',
         'UNIQUE(company_id,codigo_sucursal,codigo_punto_venta,modalidad,cufd)',
         'The same CUFD should not be stored twice for the same combination')
    ]

    @api.depends('fecha_vigencia')
    def _compute_fecha_expiracion(self):
        """CUFD expires 24 hours after generation"""
        for record in self:
            if record.fecha_vigencia:
                record.fecha_expiracion = record.fecha_vigencia + timedelta(hours=24)
            else:
                record.fecha_expiracion = False

    @api.model
    def _mark_existing_as_archived(self, company_id, sucursal, punto, modalidad):
        """Mark all previous valid CUFDs as archived"""
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
    def _validate_before_request(self, company, config, modalidad, cuis):
        """Validate all required fields before making CUFD request"""
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

        if not cuis:
            missing.append("CUIS (must obtain CUIS before requesting CUFD)")

        if missing:
            raise UserError(
                "Cannot request CUFD. Missing required configuration/fields: %s" %
                (", ".join(missing))
            )

    @api.model
    def get_or_fetch_cufd(self, company, codigo_modalidad=None, safety_minutes=30, force_new=False):
        """
        Get valid CUFD or fetch a new one if expired/missing.

        :param company: res.company record
        :param codigo_modalidad: modalidad code (1 or 2)
        :param safety_minutes: minutes before expiration to fetch new CUFD
        :param force_new: if True, always generate a new CUFD even if valid one exists
        :return: CUFD code string
        """
        if isinstance(company, (int,)):
            company = self.env['res.company'].browse(company)
        if not company or not company.exists():
            raise UserError("Invalid company for CUFD request")

        config = company.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError(
                "SIAT configuration not found. Please create a SIAT configuration "
                "and assign it to the company or create one globally."
            )

        modalidad = codigo_modalidad or (config.modalidad and str(config.modalidad)) or None
        if modalidad and isinstance(modalidad, int):
            modalidad = str(modalidad)

        sucursal = int(company.siat_codigo_sucursal or 0)
        punto = int(company.siat_codigo_punto_venta or 0)

        # First get CUIS (required for CUFD request)
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(company, codigo_modalidad=int(modalidad))
        except Exception as e:
            raise UserError(f"Cannot obtain CUFD without valid CUIS: {e}")

        # Validate all requirements
        self._validate_before_request(company, config, modalidad, cuis)

        # Check for valid existing CUFD (only if not forcing new generation)
        if not force_new:
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
                expiration = fv + timedelta(hours=24) if fv else None
                if expiration and expiration > (now_dt + safety_delta):
                    _logger.info("Using existing valid CUFD for company %s", company.name)
                    return rec.cufd
                else:
                    _logger.info("CUFD expired or about to expire, fetching new one")
                    rec.write({'state': 'expired', 'archived': True})

        # Fetch new CUFD
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_cufd(company, config, cuis)

        if not resp or resp.get('error'):
            # Create error record
            try:
                self.create({
                    'company_id': company.id,
                    'codigo_sucursal': sucursal,
                    'codigo_punto_venta': punto,
                    'modalidad': modalidad,
                    'cufd': resp.get('codigo') if resp and resp.get('codigo') else '',
                    'codigo_control': '',
                    'direccion': '',
                    'fecha_vigencia': fields.Datetime.now(),
                    'mensajes': (resp.get('mensajes') if resp else 'No response from service') or '',
                    'raw_response': (resp.get('raw') if resp else '') or '',
                    'state': 'error',
                    'archived': False,
                })
            except Exception as e:
                _logger.exception("Failed to create CUFD error record: %s", e)

            raise UserError(
                "Error obtaining CUFD: %s" %
                ((resp.get('mensajes') if resp else 'No response') or 'Unknown error')
            )

        # Archive previous valid CUFDs
        self._mark_existing_as_archived(company.id, sucursal, punto, modalidad)

        # Create new CUFD record
        new_vals = {
            'company_id': company.id,
            'codigo_sucursal': sucursal,
            'codigo_punto_venta': punto,
            'modalidad': modalidad,
            'cufd': resp['codigo'],
            'codigo_control': resp.get('codigoControl', ''),
            'direccion': resp.get('direccion', ''),
            'fecha_vigencia': resp.get('vigencia') or fields.Datetime.now(),
            'mensajes': resp.get('mensajes') or '',
            'raw_response': json.dumps(resp.get('raw') or resp),
            'state': 'valid',
            'archived': False,
        }
        new = self.create(new_vals)
        _logger.info("Created new CUFD for company %s: %s", company.name, new.cufd)
        return new.cufd

    @api.model
    def cron_generate_daily_cufd(self):
        """
        Cron job to generate CUFD daily for all companies with SIAT configuration.
        Should be scheduled to run once per day.
        """
        _logger.info("Starting daily CUFD generation cron job")

        companies = self.env['res.company'].search([
            ('siat_config_id', '!=', False)
        ])

        for company in companies:
            try:
                _logger.info("Generating CUFD for company: %s", company.name)
                self.get_or_fetch_cufd(company)
            except Exception as e:
                _logger.error(
                    "Failed to generate CUFD for company %s: %s",
                    company.name, str(e)
                )

        _logger.info("Completed daily CUFD generation cron job")