# alpha_siat/models/res_company.py
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class ResCompany(models.Model):
    _inherit = "res.company"
    siat_config_id = fields.Many2one(
        'alpha.siat.config', string="SIAT Configuration",
        help="Select the SIAT configuration (production or testing) to use for this company"
    )
    siat_codigo_sucursal = fields.Integer(
        string="SIAT - Código Sucursal",
        default=0,
        help="Código de sucursal usado for SIAT (by default first company = 0)"
    )
    siat_codigo_punto_venta = fields.Integer(
        string="SIAT - Código Punto de Venta",
        default=0,
        help="Código de punto de venta for this company/branch"
    )
    cuis_count = fields.Integer(string="CUIS count", compute="_compute_cuis_count")
    cufd_count = fields.Integer(string="CUFD count", compute="_compute_cufd_count")
    actividad_count = fields.Integer(string="Actividades count", compute="_compute_actividad_count")
    actividad_documento_count = fields.Integer(
        string="Actividades-Documentos count",
        compute="_compute_actividad_documento_count"
    )
    mensaje_servicio_count = fields.Integer(
        string="Mensajes Servicios count",
        compute="_compute_mensaje_servicio_count"
    )
    producto_servicio_count = fields.Integer(
        string="Productos/Servicios count",
        compute="_compute_producto_servicio_count"
    )
    leyenda_count = fields.Integer(
        string="Leyendas count",
        compute="_compute_leyenda_count"
    )
    evento_significativo_count = fields.Integer(
        string="Eventos Significativos count",
        compute="_compute_evento_significativo_count"
    )
    motivo_anulacion_count = fields.Integer(
        string="Motivos Anulación count",
        compute="_compute_motivo_anulacion_count"
    )
    pais_origen_count = fields.Integer(
        string="Países count",
        compute="_compute_pais_origen_count"
    )
    tipo_documento_identidad_count = fields.Integer(
        string="Tipos Documento count",
        compute="_compute_tipo_documento_identidad_count"
    )
    tipo_habitacion_count = fields.Integer(
        string="Tipos Habitación count",
        compute="_compute_tipo_habitacion_count"
    )
    tipo_metodo_pago_count = fields.Integer(
        string="Tipos Método Pago count",
        compute="_compute_tipo_metodo_pago_count"
    )
    tipo_moneda_count = fields.Integer(
        string="Tipos Moneda count",
        compute="_compute_tipo_moneda_count"
    )
    tipo_punto_venta_count = fields.Integer(
        string="Tipos Punto Venta count",
        compute="_compute_tipo_punto_venta_count"
    )
    tipos_factura_count = fields.Integer(
        string="Tipos Factura count",
        compute="_compute_tipos_factura_count"
    )
    unidad_medida_count = fields.Integer(
        string="Unidades Medida count",
        compute="_compute_unidad_medida_count"
    )
    tipo_documento_sector_count = fields.Integer(
        string="Tipos Documento Sector count",
        compute="_compute_tipo_documento_sector_count"
    )
    tipo_emision_count = fields.Integer(
        string="Tipos Emisión count",
        compute="_compute_tipo_emision_count"
    )

    @api.depends()
    def _compute_cuis_count(self):
        for company in self:
            company.cuis_count = self.env['alpha.siat.cuis'].search_count([('company_id', '=', company.id)])

    def action_get_cuis(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found. Create one and assign it to this company.")
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis_code = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Error obtaining CUIS: {e}")
        return self.action_open_cuis_history()

    def action_open_cuis_history(self):
        self.ensure_one()
        try:
            action = self.env.ref('alpha_siat.action_alpha_siat_cuis').read()[0]
        except Exception:
            action = {
                'name': 'CUIS',
                'type': 'ir.actions.act_window',
                'res_model': 'alpha.siat.cuis',
                'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('company_id', '=', self.id)],
                'context': {'default_company_id': self.id},
            }
            return action
        domain = action.get('domain') or []
        if isinstance(domain, str):
            try:
                domain = safe_eval(domain)
            except Exception:
                domain = []
        action['domain'] = [('company_id', '=', self.id)]
        ctx = action.get('context') or {}
        if isinstance(ctx, str):
            try:
                ctx = safe_eval(ctx)
            except Exception:
                ctx = {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx.update({'default_company_id': self.id})
        action['context'] = ctx
        return action


    @api.depends()
    def _compute_cufd_count(self):
        for company in self:
            company.cufd_count = self.env['alpha.siat.cufd'].search_count([
                ('company_id', '=', company.id)
            ])


    # Add these action methods
    def action_get_cufd(self):
        """Manual CUFD generation - always generates a new one"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError(
                "No SIAT configuration found. Create one and assign it to this company."
            )

        cufd_model = self.env['alpha.siat.cufd']
        try:
            cufd_code = cufd_model.get_or_fetch_cufd(
                self,
                codigo_modalidad=int(config.modalidad),
                force_new=True  # Always generate new CUFD when clicking button
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'CUFD Generated',
                    'message': f'New CUFD successfully generated: {cufd_code}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(f"Error obtaining CUFD: {e}")

    def action_open_cufd_history(self):
        """Open CUFD history for this company"""
        self.ensure_one()
        try:
            action = self.env.ref('alpha_siat.action_alpha_siat_cufd').read()[0]
        except Exception:
            action = {
                'name': 'CUFD',
                'type': 'ir.actions.act_window',
                'res_model': 'alpha.siat.cufd',
                'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('company_id', '=', self.id)],
                'context': {'default_company_id': self.id},
            }
            return action

        domain = action.get('domain') or []
        if isinstance(domain, str):
            try:
                domain = safe_eval(domain)
            except Exception:
                domain = []

        action['domain'] = [('company_id', '=', self.id)]

        ctx = action.get('context') or {}
        if isinstance(ctx, str):
            try:
                ctx = safe_eval(ctx)
            except Exception:
                ctx = {}
        if not isinstance(ctx, dict):
            ctx = {}

        ctx.update({'default_company_id': self.id})
        action['context'] = ctx

        return action

    # Add this compute method
    @api.depends()
    def _compute_actividad_count(self):
        for company in self:
            company.actividad_count = self.env['alpha.siat.actividad'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add these action methods
    def action_sync_actividades(self):
        """Synchronize activities from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_actividades(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing activities: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        actividad_model = self.env['alpha.siat.actividad']
        stats = actividad_model.sync_from_siat_response(self, resp.get('actividades', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Actividades Sincronizadas',
                'message': f"Creadas: {stats['created']}, Actualizadas: {stats['updated']}, Desactivadas: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_actividades(self):
        """Open activities list for this company"""
        self.ensure_one()
        return {
            'name': 'Actividades Económicas',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.actividad',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_actividad_documento_count(self):
        for company in self:
            company.actividad_documento_count = self.env['alpha.siat.actividad.documento.sector'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_actividades_documento_sector(self):
        """Synchronize activity-document sector relationships from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_actividades_documento_sector(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing activities-documents: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.actividad.documento.sector']
        stats = model.sync_from_siat_response(self, resp.get('actividadesDocumentos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Actividades-Documentos Sincronizados',
                'message': f"Creadas: {stats['created']}, Actualizadas: {stats['updated']}, Desactivadas: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_actividades_documento(self):
        """Open activity-document list for this company"""
        self.ensure_one()
        return {
            'name': 'Actividades - Documentos Sector',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.actividad.documento.sector',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_mensaje_servicio_count(self):
        for company in self:
            company.mensaje_servicio_count = self.env['alpha.siat.mensaje.servicio'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_mensajes_servicios(self):
        """Synchronize service messages from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_mensajes_servicios(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing service messages: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.mensaje.servicio']
        stats = model.sync_from_siat_response(self, resp.get('mensajesServicios', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Mensajes de Servicios Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_mensajes_servicios(self):
        """Open service messages list for this company"""
        self.ensure_one()
        return {
            'name': 'Mensajes de Servicios SIAT',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.mensaje.servicio',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_producto_servicio_count(self):
        for company in self:
            company.producto_servicio_count = self.env['alpha.siat.producto.servicio'].search_count([
                ('company_id', '=', company.id)
            ])

    def action_sync_productos_servicios(self):
        """Synchronize products/services from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT (with longer timeout for large response)
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_productos_servicios(self, config, cuis, timeout=60)

        if resp.get('error'):
            raise UserError(f"Error synchronizing products/services: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.producto.servicio']
        stats = model.sync_from_siat_response(self, resp.get('productos', []))

        # Build message
        message = f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}"
        if stats.get('duplicates_in_response', 0) > 0:
            message += f"\n⚠️ Duplicados en respuesta SIAT (omitidos): {stats['duplicates_in_response']}"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Productos/Servicios Sincronizados',
                'message': message,
                'type': 'success',
                'sticky': True if stats.get('duplicates_in_response', 0) > 0 else False,
            }
        }

    def action_open_productos_servicios(self):
        """Open products/services list for this company"""
        self.ensure_one()
        return {
            'name': 'Productos y Servicios',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.producto.servicio',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_leyenda_count(self):
        for company in self:
            company.leyenda_count = self.env['alpha.siat.leyenda'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_leyendas(self):
        """Synchronize legends from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_leyendas_factura(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing legends: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.leyenda']
        stats = model.sync_from_siat_response(self, resp.get('leyendas', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leyendas Sincronizadas',
                'message': f"Creadas: {stats['created']}, Actualizadas: {stats['updated']}, Desactivadas: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_leyendas(self):
        """Open legends list for this company"""
        self.ensure_one()
        return {
            'name': 'Leyendas para Facturas',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.leyenda',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }
    @api.depends()
    def _compute_evento_significativo_count(self):
        for company in self:
            company.evento_significativo_count = self.env['alpha.siat.evento.significativo'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_eventos_significativos(self):
        """Synchronize significant events from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_eventos_significativos(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing significant events: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.evento.significativo']
        stats = model.sync_from_siat_response(self, resp.get('eventos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Eventos Significativos Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_eventos_significativos(self):
        """Open significant events list for this company"""
        self.ensure_one()
        return {
            'name': 'Eventos Significativos',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.evento.significativo',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_motivo_anulacion_count(self):
        for company in self:
            company.motivo_anulacion_count = self.env['alpha.siat.motivo.anulacion'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_motivos_anulacion(self):
        """Synchronize cancellation reasons from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_motivos_anulacion(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing cancellation reasons: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.motivo.anulacion']
        stats = model.sync_from_siat_response(self, resp.get('motivos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Motivos de Anulación Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_motivos_anulacion(self):
        """Open cancellation reasons list for this company"""
        self.ensure_one()
        return {
            'name': 'Motivos de Anulación',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.motivo.anulacion',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_pais_origen_count(self):
        for company in self:
            company.pais_origen_count = self.env['alpha.siat.pais.origen'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_paises_origen(self):
        """Synchronize countries from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_paises_origen(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing countries: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.pais.origen']
        stats = model.sync_from_siat_response(self, resp.get('paises', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Países Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_paises_origen(self):
        """Open countries list for this company"""
        self.ensure_one()
        return {
            'name': 'Países de Origen',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.pais.origen',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    # Add this compute method
    @api.depends()
    def _compute_tipo_documento_identidad_count(self):
        for company in self:
            company.tipo_documento_identidad_count = self.env['alpha.siat.tipo.documento.identidad'].search_count([
                ('company_id', '=', company.id)
            ])

    # Add this action method
    def action_sync_tipos_documento_identidad(self):
        """Synchronize document types from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        # Get CUIS first
        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        # Call SIAT
        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_documento_identidad(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing document types: {resp.get('mensajes', 'Unknown error')}")

        # Process response
        model = self.env['alpha.siat.tipo.documento.identidad']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos de Documento Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_documento_identidad(self):
        """Open document types list for this company"""
        self.ensure_one()
        return {
            'name': 'Tipos de Documento de Identidad',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.documento.identidad',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_habitacion_count(self):
        for company in self:
            company.tipo_habitacion_count = self.env['alpha.siat.tipo.habitacion'].search_count([
                ('company_id', '=', company.id)
            ])

    def action_sync_tipos_habitacion(self):
        """Synchronize room types from SIAT"""
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_habitacion(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing room types: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.habitacion']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos de Habitación Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_habitacion(self):
        self.ensure_one()
        return {
            'name': 'Tipos de Habitación',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.habitacion',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_metodo_pago_count(self):
        for company in self:
            company.tipo_metodo_pago_count = self.env['alpha.siat.tipo.metodo.pago'].search_count([
                ('company_id', '=', company.id)
            ])

    def action_sync_tipos_metodo_pago(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_metodo_pago(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing payment methods: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.metodo.pago']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos Método de Pago Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_metodo_pago(self):
        self.ensure_one()
        return {
            'name': 'Tipos de Método de Pago',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.metodo.pago',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_moneda_count(self):
        for company in self:
            company.tipo_moneda_count = self.env['alpha.siat.tipo.moneda'].search_count([('company_id', '=', company.id)])

    def action_sync_tipos_moneda(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_moneda(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing currencies: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.moneda']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos de Moneda Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_moneda(self):
        self.ensure_one()
        return {
            'name': 'Tipos de Moneda',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.moneda',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_punto_venta_count(self):
        for company in self:
            company.tipo_punto_venta_count = self.env['alpha.siat.tipo.punto.venta'].search_count([('company_id', '=', company.id)])

    def action_sync_tipos_punto_venta(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_punto_venta(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing punto venta types: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.punto.venta']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos Punto Venta Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_punto_venta(self):
        self.ensure_one()
        return {
            'name': 'Tipos Punto de Venta',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.punto.venta',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipos_factura_count(self):
        for company in self:
            company.tipos_factura_count = self.env['alpha.siat.tipos.factura'].search_count([('company_id', '=', company.id)])

    def action_sync_tipos_factura(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_factura(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing invoice types: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipos.factura']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos Factura Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_factura(self):
        self.ensure_one()
        return {
            'name': 'Tipos de Factura',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipos.factura',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }


    @api.depends()
    def _compute_unidad_medida_count(self):
        for company in self:
            company.unidad_medida_count = self.env['alpha.siat.unidad.medida'].search_count([('company_id', '=', company.id)])

    def action_sync_unidades_medida(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_unidades_medida(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing unidades medida: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.unidad.medida']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Unidades de Medida Sincronizadas',
                'message': f"Creadas: {stats['created']}, Actualizadas: {stats['updated']}, Desactivadas: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_unidades_medida(self):
        self.ensure_one()
        return {
            'name': 'Unidades de Medida SIAT',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.unidad.medida',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_documento_sector_count(self):
        for company in self:
            company.tipo_documento_sector_count = self.env['alpha.siat.tipo.documento.sector'].search_count([('company_id', '=', company.id)])

    def action_sync_tipos_documento_sector(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_documento_sector(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing document types (sector): {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.documento.sector']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos Documento Sector Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_documento_sector(self):
        self.ensure_one()
        return {
            'name': 'Tipos Documento Sector',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.documento.sector',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    @api.depends()
    def _compute_tipo_emision_count(self):
        for company in self:
            company.tipo_emision_count = self.env['alpha.siat.tipo.emision'].search_count([('company_id', '=', company.id)])

    def action_sync_tipos_emision(self):
        self.ensure_one()
        config = self.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No SIAT configuration found.")

        cuis_model = self.env['alpha.siat.cuis']
        try:
            cuis = cuis_model.get_or_fetch_cuis(self, codigo_modalidad=int(config.modalidad))
        except Exception as e:
            raise UserError(f"Cannot sync without valid CUIS: {e}")

        client = self.env['alpha.siat.client'].sudo()
        resp = client.call_sincronizar_tipos_emision(self, config, cuis)

        if resp.get('error'):
            raise UserError(f"Error synchronizing tipos de emisión: {resp.get('mensajes', 'Unknown error')}")

        model = self.env['alpha.siat.tipo.emision']
        stats = model.sync_from_siat_response(self, resp.get('tipos', []))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tipos de Emisión Sincronizados',
                'message': f"Creados: {stats['created']}, Actualizados: {stats['updated']}, Desactivados: {stats['deactivated']}",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_tipos_emision(self):
        self.ensure_one()
        return {
            'name': 'Tipos de Emisión SIAT',
            'type': 'ir.actions.act_window',
            'res_model': 'alpha.siat.tipo.emision',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    def action_generar_cuf_prueba(self):
        self.ensure_one()

        # Llamar al generador de CUF
        cuf_generator = self.env['alpha.siat.cuf.generator']
        resultado = cuf_generator.generar_cuf(company_id=self.id, numero_factura=1)

        # Mostrar notificación con el CUF generado
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '✅ CUF Generado Exitosamente',
                'message': f"CUF: {resultado['cuf']}\n\nRevisa los logs de Odoo para ver el proceso completo de generación.",
                'type': 'success',
                'sticky': True,
            }
        }