import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _default_siat_tipo_documento_identidad_id(self):
        tipo_doc_model = self.env['alpha.siat.tipo.documento.identidad']

        # Preferir CI (codigo_clasificador=1) de la compañía activa
        tipo = tipo_doc_model.search([
            ('codigo_clasificador', '=', 1),
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
        ], limit=1)

        # Si no hay tipos sincronizados aún, caer a cualquier tipo activo disponible
        if not tipo:
            tipo = tipo_doc_model.search([('active', '=', True)], limit=1)

        return tipo.id if tipo else False

    # SIAT Homologation Fields for Customers
    siat_tipo_documento_identidad_id = fields.Many2one(
        'alpha.siat.tipo.documento.identidad',
        string='Tipo de Documento',
        help='Tipo de documento de identidad según catálogo SIAT',
        domain="[('active', '=', True)]",
        index=True,
        required=True,  # Obligatorio
        default=lambda self: self._default_siat_tipo_documento_identidad_id()
    )

    # Make VAT (CI) required for customers with SIAT
    vat = fields.Char(
        string='CI',
        help='Cédula de Identidad',
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

    siat_razon_social_facturacion = fields.Char(
        string='Razón Social para Facturación',
        help='Nombre a utilizar en la factura SIAT, independiente de la identidad real del contacto',
        tracking=True
    )

    siat_nit_facturacion = fields.Char(
        string='NIT/CI para Facturación',
        help='Número de documento a utilizar en la factura SIAT, independiente del NIT/CI real (vat)',
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

    @api.depends('siat_nit_facturacion', 'siat_complemento')
    def _compute_siat_documento_completo(self):

        for partner in self:
            if partner.siat_nit_facturacion:
                if partner.siat_complemento:
                    partner.siat_documento_completo = f"{partner.siat_nit_facturacion}-{partner.siat_complemento}"
                else:
                    partner.siat_documento_completo = partner.siat_nit_facturacion
            else:
                partner.siat_documento_completo = False

    @api.depends('siat_nit_facturacion')
    def _compute_codigo_cliente(self):

        for partner in self:
            if partner.siat_nit_facturacion:
                # Limpiar el NIT/CI de facturación de guiones y espacios
                nit_clean = partner.siat_nit_facturacion.replace('-', '').replace(' ', '')
                partner.codigo_cliente = f"CLI{nit_clean}"
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

        # Solo advertir si alguien cambia manualmente el tipo de documento en un
        # contacto YA GUARDADO, no cuando se autocompleta por default al crear uno nuevo
        es_registro_existente = bool(self._origin.id)
        cambio_manual = self._origin.siat_tipo_documento_identidad_id != self.siat_tipo_documento_identidad_id

        if not (es_registro_existente and cambio_manual):
            return

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

    @api.constrains('siat_nit_facturacion')
    def _check_siat_nit_facturacion(self):

        for partner in self:
            if partner.siat_nit_facturacion == '0':
                raise ValidationError(_(
                    "NIT/CI para Facturación inválido: '0' no es un valor válido para SIAT.\n\n"
                    "Usa '0000000' si no tienes datos de facturación configurados, o el NIT/CI "
                    "real para facturación de este cliente."
                ))

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('siat_razon_social_facturacion'):
                vals['siat_razon_social_facturacion'] = 'S/N'
            if not vals.get('siat_nit_facturacion'):
                vals['siat_nit_facturacion'] = '0000000'
        return super().create(vals_list)