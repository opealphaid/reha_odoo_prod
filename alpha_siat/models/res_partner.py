import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # SIAT Homologation Fields for Customers
    siat_tipo_documento_identidad_id = fields.Many2one(
        'alpha.siat.tipo.documento.identidad',
        string='Tipo de Documento',
        help='Tipo de documento de identidad según catálogo SIAT',
        domain="[('active', '=', True)]",
        index=True,
        required=True  # Obligatorio
    )

    # Make VAT (NIT/CI) required for customers with SIAT
    vat = fields.Char(
        string='NIT/CI',
        help='Número de Identificación Tributaria o Cédula de Identidad',
        index=True,
        tracking=True,
        required=True  # Obligatorio
    )

    siat_complemento = fields.Char(
        string='Complemento',
        size=10,
        help='Complemento del documento de identidad (ej: 1A, 2B)',
        tracking=True
    )

    # Computed field for easy identification
    siat_documento_completo = fields.Char(
        string='Documento Completo',
        compute='_compute_siat_documento_completo',
        store=True,
        help='Documento completo con complemento (ej: 12345678-1A)'
    )

    # Código de Cliente para SIAT
    codigo_cliente = fields.Char(
        string='Código Cliente',
        compute='_compute_codigo_cliente',
        store=True,
        help='Código de cliente formato: CLI + NIT/CI (ej: CLI12345678)'
    )

    # Homologation status
    siat_homologado_cliente = fields.Boolean(
        string='Cliente Homologado SIAT',
        compute='_compute_siat_homologado_cliente',
        store=True,
        help='Indica si el cliente está completamente homologado para facturación SIAT'
    )

    # Computed/Related fields for easy access
    siat_codigo_tipo_documento = fields.Integer(
        related='siat_tipo_documento_identidad_id.codigo_clasificador',
        string='Código Tipo Documento',
        store=True,
        readonly=True
    )

    siat_descripcion_tipo_documento = fields.Char(
        related='siat_tipo_documento_identidad_id.descripcion',
        string='Tipo de Documento',
        readonly=True
    )

    @api.depends('vat', 'siat_complemento')
    def _compute_siat_documento_completo(self):

        for partner in self:
            if partner.vat:
                if partner.siat_complemento:
                    partner.siat_documento_completo = f"{partner.vat}-{partner.siat_complemento}"
                else:
                    partner.siat_documento_completo = partner.vat
            else:
                partner.siat_documento_completo = False

    @api.depends('vat')
    def _compute_codigo_cliente(self):

        for partner in self:
            if partner.vat:
                # Limpiar el VAT de guiones y espacios
                vat_clean = partner.vat.replace('-', '').replace(' ', '')
                partner.codigo_cliente = f"CLI{vat_clean}"
            else:
                partner.codigo_cliente = False

    @api.depends('siat_tipo_documento_identidad_id', 'vat')
    def _compute_siat_homologado_cliente(self):
        for partner in self:
            # Solo marcar como homologado si el registro está guardado
            # Verificamos si tiene ID real (no NewId temporal)
            if partner.id and isinstance(partner.id, int):
                partner.siat_homologado_cliente = bool(
                    partner.siat_tipo_documento_identidad_id and
                    partner.vat
                )
            else:
                # Registro nuevo (no guardado aún) o ID temporal
                partner.siat_homologado_cliente = False

    @api.onchange('siat_tipo_documento_identidad_id')
    def _onchange_siat_tipo_documento_identidad(self):

        if self.siat_tipo_documento_identidad_id:
            tipo = self.siat_tipo_documento_identidad_id.descripcion.upper()

            # If CI selected, suggest complement might be needed
            if 'CI' in tipo or 'CEDULA' in tipo:
                return {
                    'warning': {
                        'title': _('Información'),
                        'message': _(
                            'Para Cédulas de Identidad, recuerde agregar el complemento si corresponde (ej: 1A, 2B).')
                    }
                }

            # If NIT selected, remind about format
            elif 'NIT' in tipo:
                return {
                    'warning': {
                        'title': _('Información'),
                        'message': _('Para NIT, ingrese el número sin guiones ni espacios.')
                    }
                }

    @api.constrains('vat', 'siat_tipo_documento_identidad_id', 'customer_rank')
    def _check_siat_customer_fields(self):

        for partner in self:
            # Only validate for customers
            if partner.customer_rank > 0 and not partner.is_company:
                # Check if trying to invoice without proper homologation
                if partner.invoice_ids:
                    if not partner.vat:
                        raise ValidationError(_(
                            "El cliente '%s' debe tener un NIT/CI para poder facturar."
                        ) % partner.name)

                    if not partner.siat_tipo_documento_identidad_id:
                        raise ValidationError(_(
                            "El cliente '%s' debe tener un Tipo de Documento SIAT para poder facturar."
                        ) % partner.name)

    @api.model
    def _validate_vat_format(self, vat_value, tipo_documento):

        if not vat_value:
            return (False, "Debe ingresar un número de documento")

        # Clean the value
        vat_clean = vat_value.strip()

        if not tipo_documento:
            return (True, "")  # Skip validation if no document type

        tipo_desc = tipo_documento.descripcion.upper()

        # CI validation (should be numeric, 5-10 digits typically)
        if 'CI' in tipo_desc or 'CEDULA' in tipo_desc:
            if not vat_clean.replace('-', '').isdigit():
                return (False, "La Cédula de Identidad debe contener solo números")
            if len(vat_clean.replace('-', '')) < 5:
                return (False, "La Cédula de Identidad parece muy corta")

        # NIT validation (should be numeric, typically 8-13 digits)
        elif 'NIT' in tipo_desc:
            if not vat_clean.replace('-', '').isdigit():
                return (False, "El NIT debe contener solo números")
            if len(vat_clean.replace('-', '')) < 5:
                return (False, "El NIT parece muy corto")

        return (True, "")

    def validate_siat_customer_homologation(self):

        self.ensure_one()

        errors = []

        if not self.vat:
            errors.append(_("El cliente debe tener un NIT/CI."))

        if not self.siat_tipo_documento_identidad_id:
            errors.append(_("El cliente debe tener un Tipo de Documento SIAT."))

        # Validate VAT format based on document type
        if self.vat and self.siat_tipo_documento_identidad_id:
            is_valid, error_msg = self._validate_vat_format(
                self.vat,
                self.siat_tipo_documento_identidad_id
            )
            if not is_valid:
                errors.append(_(error_msg))

        if errors:
            raise ValidationError("\n".join(errors))

        return True

    def get_siat_customer_data(self):

        self.ensure_one()

        # Validate first
        self.validate_siat_customer_homologation()

        # Build customer data for SIAT invoice
        data = {
            'numeroDocumento': self.vat,
            'tipoDocumentoIdentidad': self.siat_codigo_tipo_documento,
            'razonSocial': self.name[:500],  # Limit to 500 chars
            'codigoCliente': self.codigo_cliente,  # Agregar código de cliente
        }

        # Add complement if exists
        if self.siat_complemento:
            data['complemento'] = self.siat_complemento

        # Add email if exists (optional in SIAT but useful)
        if self.email:
            data['email'] = self.email

        return data

    def action_homologar_cliente_siat(self):

        self.ensure_one()
        return {
            'name': _('Homologar Cliente SIAT'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'form_view_ref': 'alpha_siat.res_partner_homologacion_siat_form',
            }
        }

    @api.model
    def cron_check_non_homologated_customers(self):

        non_homologated = self.search([
            ('siat_homologado_cliente', '=', False),
            ('customer_rank', '>', 0),  # Only customers
            ('is_company', '=', False),  # Not companies
            ('active', '=', True)
        ])

        if non_homologated:
            _logger.warning(
                "Found %d non-homologated customers: %s",
                len(non_homologated),
                ', '.join(non_homologated.mapped('name')[:10])  # Show first 10
            )

        return non_homologated

    def action_sync_tipo_documento_identidad(self):

        company = self.env.company
        return company.action_sync_tipos_documento_identidad()