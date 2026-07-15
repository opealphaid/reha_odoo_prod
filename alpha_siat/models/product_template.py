import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # SIAT Homologation Fields
    siat_codigo_producto_sin = fields.Many2one(
        'alpha.siat.producto.servicio',
        string='Producto SIAT',
        help='Código de producto/servicio según catálogo SIAT',
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        index=True
    )

    siat_actividad_economica_id = fields.Many2one(
        'alpha.siat.actividad',
        string='Actividad Económica',
        help='Actividad económica SIAT asociada a este producto',
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        index=True
    )

    siat_unidad_medida_id = fields.Many2one(
        'alpha.siat.unidad.medida',
        string='Unidad de Medida SIAT',
        help='Unidad de medida según catálogo SIAT',
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        index=True
    )

    # Computed/Related fields for easy access
    siat_codigo_actividad = fields.Char(
        related='siat_actividad_economica_id.codigo_caeb',
        string='Código Actividad',
        store=True,
        readonly=True
    )

    siat_codigo_producto = fields.Char(
        related='siat_codigo_producto_sin.codigo_producto',
        string='Código Producto SIN',
        store=True,
        readonly=True
    )

    siat_codigo_unidad_medida = fields.Integer(
        related='siat_unidad_medida_id.codigo_clasificador',
        string='Código Unidad Medida',
        store=True,
        readonly=True
    )

    # Homologation status
    siat_homologado = fields.Boolean(
        string='Homologado SIAT',
        compute='_compute_siat_homologado',
        store=True,
        help='Indica si el producto está completamente homologado para facturación SIAT'
    )

    # Company field (if not already inherited)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    def _requiere_homologacion_siat(self):
        """
        Determina si el producto requiere homologación SIAT.
        Solo los productos de COMPRA ÚNICAMENTE están exentos de homologación.

        Returns:
            bool: True si requiere homologación, False si no la requiere
        """
        self.ensure_one()

        # Si el producto puede venderse (sale_ok) o está disponible en POS, requiere homologación
        if self.sale_ok or self.available_in_pos:
            return True

        # Si SOLO es de compra (purchase_ok=True, sale_ok=False, available_in_pos=False)
        # NO requiere homologación
        return False

    @api.depends('siat_codigo_producto_sin', 'siat_actividad_economica_id', 'siat_unidad_medida_id')
    def _compute_siat_homologado(self):
        """
        A product is considered homologated when it has all required SIAT fields
        """
        for product in self:
            product.siat_homologado = bool(
                product.siat_codigo_producto_sin and
                product.siat_actividad_economica_id and
                product.siat_unidad_medida_id
            )

    @api.constrains('sale_ok', 'available_in_pos', 'siat_codigo_producto_sin',
                    'siat_actividad_economica_id', 'siat_unidad_medida_id', 'default_code')
    def _check_siat_homologation(self):

        if self.env.context.get('install_mode') or self.env.context.get('module'):
            return

        if self.env.context.get('import_file'):
            return

        for product in self:
            if product._requiere_homologacion_siat():
                try:
                    product.validate_siat_homologation()
                except ValidationError:
                    raise

    @api.onchange('siat_codigo_producto_sin')
    def _onchange_siat_codigo_producto_sin(self):
        """
        When selecting a SIAT product, auto-suggest the activity if available
        """
        if self.siat_codigo_producto_sin and not self.siat_actividad_economica_id:
            # Get the activity linked to this product
            if self.siat_codigo_producto_sin.actividad_id:
                self.siat_actividad_economica_id = self.siat_codigo_producto_sin.actividad_id

    @api.onchange('type')
    def _onchange_type_suggest_uom(self):
        """
        Auto-suggest SIAT unit of measure based on product type
        """
        if self.type and not self.siat_unidad_medida_id:
            uom_model = self.env['alpha.siat.unidad.medida']

            if self.type == 'service':
                # Try to find "UNIDAD (SERVICIOS)"
                codigo = uom_model.get_codigo_unidad_servicios(self.company_id)
            else:
                # Try to find "UNIDAD (BIENES)"
                codigo = uom_model.get_codigo_unidad_bienes(self.company_id)

            if codigo:
                uom_siat = uom_model.search([
                    ('codigo_clasificador', '=', codigo),
                    ('company_id', '=', self.company_id.id),
                    ('active', '=', True)
                ], limit=1)
                if uom_siat:
                    self.siat_unidad_medida_id = uom_siat

    def action_homologar_siat(self):
        """
        Wizard/action to homologate product with SIAT
        Opens a form to select SIAT codes
        """
        self.ensure_one()
        return {
            'name': _('Homologar Producto SIAT'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'form_view_ref': 'alpha_siat.product_template_homologacion_form',
            }
        }

    def validate_siat_homologation(self):
        """
        Validate that product is properly homologated for SIAT invoicing
        Raises ValidationError if not properly configured
        Returns True si la validación es exitosa o no es necesaria
        """
        self.ensure_one()

        # Si el producto NO requiere homologación (solo compra), retornar True sin validar
        if not self._requiere_homologacion_siat():
            _logger.info(
                "Producto '%s' (ID: %d) es solo de compra, no requiere homologación SIAT",
                self.name, self.id
            )
            return True

        # Si requiere homologación, proceder con las validaciones
        errors = []

        # COMENTADO: Ya no es obligatorio el código interno
        # if not self.default_code:
        #     errors.append(_("El producto debe tener un código interno (Referencia Interna)."))

        if not self.siat_codigo_producto_sin:
            errors.append(_("Debe seleccionar un Código de Producto SIAT."))

        if not self.siat_actividad_economica_id:
            errors.append(_("Debe seleccionar una Actividad Económica SIAT."))

        if not self.siat_unidad_medida_id:
            errors.append(_("Debe seleccionar una Unidad de Medida SIAT."))

        # Verify activity matches product
        if self.siat_codigo_producto_sin and self.siat_actividad_economica_id:
            if self.siat_codigo_producto_sin.codigo_actividad != self.siat_actividad_economica_id.codigo_caeb:
                errors.append(_(
                    "La Actividad Económica seleccionada (%s) no coincide con "
                    "la actividad del producto SIAT (%s)."
                ) % (
                                  self.siat_actividad_economica_id.codigo_caeb,
                                  self.siat_codigo_producto_sin.codigo_actividad
                              ))

        if errors:
            raise ValidationError("\n".join(errors))

        return True

    def get_siat_invoice_line_data(self):
        """
        Get SIAT-ready data for invoice line
        Returns dict with all required SIAT fields
        """
        self.ensure_one()

        # Validate first
        self.validate_siat_homologation()

        return {
            'actividadEconomica': self.siat_codigo_actividad,
            'codigoProductoSin': int(self.siat_codigo_producto),
            'codigoProducto': self.default_code or 'PROD-' + str(self.id),
            'descripcion': self.name[:500],  # Max 500 chars per XSD
            'unidadMedida': self.siat_codigo_unidad_medida,
        }

    @api.model
    def cron_check_non_homologated_products(self):
        """
        Cron job to identify products that need homologation
        Solo busca productos que requieran homologación (no solo compra)
        """
        non_homologated = self.search([
            ('siat_homologado', '=', False),
            ('active', '=', True),
            '|',
            ('sale_ok', '=', True),  # Productos que pueden venderse
            ('available_in_pos', '=', True)  # O disponibles en POS
        ])

        if non_homologated:
            _logger.warning(
                "Found %d non-homologated products that require SIAT homologation: %s",
                len(non_homologated),
                ', '.join(non_homologated.mapped('name'))
            )

        return non_homologated