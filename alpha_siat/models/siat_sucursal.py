# alpha_siat/models/siat_sucursal.py
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SiatSucursal(models.Model):
    _name = "alpha.siat.sucursal"
    _description = "SIAT - Sucursales y Puntos de Venta"
    _order = "company_id, codigo_sucursal, codigo_punto_venta"

    name = fields.Char(
        required=True,
        help="Nombre descriptivo de la sucursal/punto de venta (ej: 'Sucursal Centro - PDV 1')"
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company
    )
    codigo_sucursal = fields.Integer(
        string="Código Sucursal (SIAT)", required=True, default=0,
        help="Código de sucursal asignado por SIAT para esta sucursal"
    )
    codigo_punto_venta = fields.Integer(
        string="Código Punto de Venta (SIAT)", required=True, default=0,
        help="Código de punto de venta asignado por SIAT para esta caja/PDV"
    )
    active = fields.Boolean(default=True)

    state_id = fields.Many2one(
        "res.country.state", string="Departamento",
        help="Departamento donde está ubicada esta sucursal (para la cabecera de la factura SIAT)"
    )
    city = fields.Char(
        string="Municipio",
        help="Municipio de esta sucursal (elemento 'municipio' de la cabecera SIAT)"
    )
    street = fields.Char(
        string="Dirección",
        help="Dirección de esta sucursal (unidad vecinal, calle, número, etc.)"
    )
    phone = fields.Char(
        string="Teléfono",
        help="Teléfono de esta sucursal"
    )

    _sql_constraints = [
        ('uniq_sucursal_pdv', 'UNIQUE(company_id, codigo_sucursal, codigo_punto_venta)',
         'Ya existe una sucursal registrada con ese código de sucursal y punto de venta para esta compañía.')
    ]

    def get_siat_municipio(self):
        """Municipio a enviar en el elemento 'municipio' de la cabecera SIAT."""
        self.ensure_one()
        return self.city or self.company_id.city or 'Nuestra Senora de La Paz'

    def get_siat_telefono(self):
        """Teléfono a enviar en el elemento 'telefono' de la cabecera SIAT."""
        self.ensure_one()
        phone = self.phone or self.company_id.phone
        return phone[:25] if phone else '0000000'

    def get_siat_direccion_completa(self):
        """Dirección para el elemento 'direccion' de la cabecera SIAT y para
        nuestra representación impresa: solo la dirección libre (unidad
        vecinal/calle/nro) — el municipio y el teléfono ya se muestran por
        separado (get_siat_municipio / get_siat_telefono), así que no se
        repiten acá para no saturar la factura con datos redundantes.

        Si la sucursal no tiene dirección cargada, se cae a la de la
        compañía (útil para la sucursal migrada desde los campos viejos de
        res.company)."""
        self.ensure_one()
        return self.street or self.company_id.street or 'Sin dirección'

    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, f"{rec.name} (Suc. {rec.codigo_sucursal} / PDV {rec.codigo_punto_venta})"))
        return result

    @api.model
    def get_default_sucursal(self, company):
        """Devuelve la única sucursal activa de la compañía. Si hay 0 o 2+, error claro.

        Usado por flujos que no dependen de un usuario en particular (botones
        admin en la compañía, sincronización de catálogos SIAT).
        """
        sucursales = self.search([('company_id', '=', company.id), ('active', '=', True)])
        if len(sucursales) == 1:
            return sucursales
        if not sucursales:
            raise UserError(
                "La compañía '%s' no tiene ninguna Sucursal SIAT registrada.\n\n"
                "Vaya a: SIAT Bolivia > Sucursales y registre al menos una "
                "(código de sucursal + código de punto de venta)." % company.name
            )
        raise UserError(
            "La compañía '%s' tiene %d Sucursales SIAT registradas.\n\n"
            "Esta acción no depende de un usuario específico y no puede elegir "
            "automáticamente entre varias. Indique la sucursal explícitamente." % (
                company.name, len(sucursales)
            )
        )

    @api.model
    def get_sucursal_for_sync(self, company):
        """Resuelve la sucursal a usar para las sincronizaciones de catálogos SIAT
        a nivel de compañía (Actividades, Unidades de Medida, etc. en res.company).

        Estas sincronizaciones no dependen de un usuario y, además, el XML que se
        envía a SIAT para ellas ya usa directamente company.siat_codigo_sucursal /
        company.siat_codigo_punto_venta (ver siat_client.py), no el registro de
        Sucursal SIAT. Por eso, cuando hay más de una Sucursal SIAT activa, se usa
        esos mismos códigos de la compañía para desambiguar y así pedir el CUIS
        con la sucursal/PDV que realmente se va a usar en la sincronización.
        """
        sucursales = self.search([('company_id', '=', company.id), ('active', '=', True)])
        if len(sucursales) <= 1:
            return self.get_default_sucursal(company)

        match = sucursales.filtered(
            lambda s: s.codigo_sucursal == company.siat_codigo_sucursal
            and s.codigo_punto_venta == company.siat_codigo_punto_venta
        )
        if len(match) == 1:
            return match

        raise UserError(
            "La compañía '%s' tiene %d Sucursales SIAT registradas y ninguna coincide "
            "con los códigos configurados en la compañía (Sucursal %s / Punto de Venta %s).\n\n"
            "Corrija 'SIAT - Código Sucursal' / 'SIAT - Código Punto de Venta' en la compañía "
            "para que coincidan con la Sucursal SIAT desde la que quiere sincronizar, o cree "
            "una Sucursal SIAT con esos códigos." % (
                company.name, len(sucursales), company.siat_codigo_sucursal,
                company.siat_codigo_punto_venta
            )
        )

    @api.model
    def get_sucursal_for_user(self, company, user=None):
        """Resuelve la sucursal SIAT desde la cual debe facturar `user`.

        1. Si el usuario tiene una Sucursal SIAT asignada, se usa esa.
        2. Si no tiene asignada, se cae a get_default_sucursal (para no romper
           compañías de una sola sucursal con usuarios sin asignar todavía).
        """
        user = user or self.env.user
        sucursal = user.siat_sucursal_id
        if sucursal:
            if sucursal.company_id != company:
                raise UserError(
                    "El usuario '%s' tiene asignada la Sucursal SIAT '%s', que "
                    "pertenece a la compañía '%s', distinta de '%s'.\n\n"
                    "Corrija la Sucursal SIAT asignada al usuario en su perfil." % (
                        user.name, sucursal.display_name, sucursal.company_id.name, company.name
                    )
                )
            return sucursal

        sucursales = self.search([('company_id', '=', company.id), ('active', '=', True)])
        if len(sucursales) == 1:
            return sucursales
        if not sucursales:
            raise UserError(
                "La compañía '%s' no tiene ninguna Sucursal SIAT registrada.\n\n"
                "Vaya a: SIAT Bolivia > Sucursales y registre al menos una." % company.name
            )
        raise UserError(
            "El usuario '%s' no tiene una Sucursal SIAT asignada y la compañía "
            "'%s' tiene %d sucursales registradas.\n\n"
            "Pida a un administrador que le asigne una Sucursal SIAT en: "
            "Ajustes > Usuarios > %s > Sucursal SIAT." % (
                user.name, company.name, len(sucursales), user.name
            )
        )

    def get_next_numero_factura(self):
        """Siguiente número de factura SIAT correlativo para ESTA sucursal/PDV.

        Fuente única de verdad para account_move.py y pos_order.py (antes cada
        uno mantenía su propio contador independiente). Bloquea la fila de la
        sucursal (SELECT ... FOR UPDATE) para serializar altas concurrentes
        desde la misma caja.
        """
        self.ensure_one()

        self.env.cr.execute(
            "SELECT id FROM alpha_siat_sucursal WHERE id = %s FOR UPDATE",
            (self.id,)
        )

        ultima_factura = self.env['account.move'].search([
            ('siat_sucursal_id', '=', self.id),
            ('siat_numero_factura', '!=', False),
            ('move_type', '=', 'out_invoice'),
        ], order='siat_numero_factura desc', limit=1)

        siguiente_numero = (ultima_factura.siat_numero_factura + 1) if ultima_factura else 1

        _logger.info(
            "Siguiente número de factura SIAT para sucursal '%s' (Suc. %s / PDV %s): %s",
            self.name, self.codigo_sucursal, self.codigo_punto_venta, siguiente_numero
        )

        return siguiente_numero

    def action_get_cuis(self):
        """Obtiene (o reutiliza si sigue vigente) el CUIS de ESTA sucursal
        específica — a diferencia del botón de la Compañía, no depende de
        que exista una única sucursal registrada."""
        self.ensure_one()
        company = self.company_id
        config = company.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No se encontró configuración SIAT. Créela y asígnela a la compañía.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis_code = cuis_model.get_or_fetch_cuis(company, sucursal=self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Error al obtener el CUIS: {e}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'CUIS obtenido',
                'message': f"Sucursal '{self.name}': CUIS {cuis_code}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_get_cufd(self):
        """Genera un CUFD nuevo para ESTA sucursal específica."""
        self.ensure_one()
        company = self.company_id
        config = company.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No se encontró configuración SIAT. Créela y asígnela a la compañía.")

        cufd_model = self.env['alpha.siat.cufd']
        try:
            cufd_code = cufd_model.get_or_fetch_cufd(
                company, sucursal=self, codigo_modalidad=int(config.modalidad), force_new=True
            )
        except Exception as e:
            raise UserError(f"Error al obtener el CUFD: {e}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'CUFD generado',
                'message': f"Sucursal '{self.name}': CUFD {cufd_code}",
                'type': 'success',
                'sticky': False,
            }
        }
