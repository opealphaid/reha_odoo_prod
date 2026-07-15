import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatMensajeServicio(models.Model):
    _name = "alpha.siat.mensaje.servicio"
    _description = "SIAT - Mensajes de Servicios"
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
        help="Código del mensaje/error de servicio SIAT"
    )

    descripcion = fields.Text(
        string="Descripción",
        required=True,
        help="Descripción del mensaje/error"
    )

    tipo_mensaje = fields.Selection([
        ('success', 'Éxito'),
        ('error', 'Error'),
        ('warning', 'Advertencia'),
        ('info', 'Información')
    ], string="Tipo de Mensaje", compute="_compute_tipo_mensaje", store=True,
        help="Tipo de mensaje según código")

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

    @api.depends('codigo_clasificador')
    def _compute_tipo_mensaje(self):
        """Determine message type based on code range"""
        for record in self:
            codigo = record.codigo_clasificador
            if codigo == 926:  # COMUNICACION EXITOSA
                record.tipo_mensaje = 'success'
            elif codigo in [901, 903, 905, 907, 908, 978]:  # Success statuses
                record.tipo_mensaje = 'success'
            elif codigo >= 2000 and codigo < 3000:  # Warnings (2000-2999)
                record.tipo_mensaje = 'warning'
            elif codigo >= 3000:  # Info/Marks (3000+)
                record.tipo_mensaje = 'info'
            else:  # Errors (900-1999)
                record.tipo_mensaje = 'error'

    def name_get(self):
        """Display format: [CODE] Description (truncated)"""
        result = []
        for record in self:
            desc = record.descripcion[:60] + '...' if len(record.descripcion) > 60 else record.descripcion
            name = f"[{record.codigo_clasificador}] {desc}"
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
    def get_mensaje_by_codigo(self, codigo):
        """
        Get message description by code

        :param codigo: Message code (int or str)
        :return: Message description string or None
        """
        try:
            codigo = int(codigo)
        except (ValueError, TypeError):
            return None

        mensaje = self.search([
            ('codigo_clasificador', '=', codigo),
            ('active', '=', True)
        ], limit=1)

        return mensaje.descripcion if mensaje else None

    @api.model
    def sync_from_siat_response(self, company, mensajes_list):
        """
        Synchronize service messages from SIAT response

        :param company: res.company record
        :param mensajes_list: list of dicts with codigoClasificador, descripcion
        :return: dict with statistics
        """
        if not mensajes_list:
            _logger.warning("No service messages to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing codes for this company
        existing_records = self.search([('company_id', '=', company.id)])
        existing_codes = {rec.codigo_clasificador: rec for rec in existing_records}
        synced_codes = set()

        for msg_data in mensajes_list:
            codigo = msg_data.get('codigoClasificador', '')

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
                'descripcion': msg_data.get('descripcion', '').strip(),
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
            "SIAT Service Messages sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_codes)
        }