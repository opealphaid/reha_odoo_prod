import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SiatProductoServicio(models.Model):
    _name = "alpha.siat.producto.servicio"
    _description = "SIAT - Productos y Servicios por Actividad"
    _order = "codigo_actividad, codigo_producto"
    _rec_name = "descripcion_producto"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        string="Company"
    )

    codigo_actividad = fields.Char(
        string="Código Actividad (CAEB)",
        required=True,
        index=True,
        help="Código de Actividad Económica de Bolivia"
    )

    actividad_id = fields.Many2one(
        "alpha.siat.actividad",
        string="Actividad Económica",
        compute="_compute_actividad_id",
        store=True,
        help="Relación con la actividad económica"
    )

    codigo_producto = fields.Char(
        string="Código Producto",
        required=True,
        index=True,
        help="Código del producto o servicio SIAT"
    )

    descripcion_producto = fields.Text(
        string="Descripción Producto/Servicio",
        required=True,
        help="Descripción del producto o servicio"
    )

    nandina_ids = fields.One2many(
        "alpha.siat.producto.nandina",
        "producto_servicio_id",
        string="Códigos NANDINA",
        help="Códigos arancelarios NANDINA asociados"
    )

    nandina_count = fields.Integer(
        string="# NANDINA",
        compute="_compute_nandina_count",
        help="Cantidad de códigos NANDINA asociados"
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
        ('uniq_actividad_producto',
         'UNIQUE(company_id, codigo_actividad, codigo_producto)',
         'La combinación de actividad y producto debe ser única por compañía')
    ]

    @api.depends('codigo_actividad', 'company_id')
    def _compute_actividad_id(self):
        """Link to alpha.siat.actividad if exists"""
        for record in self:
            if record.codigo_actividad and record.company_id:
                actividad = self.env['alpha.siat.actividad'].search([
                    ('codigo_caeb', '=', record.codigo_actividad),
                    ('company_id', '=', record.company_id.id)
                ], limit=1)
                record.actividad_id = actividad.id if actividad else False
            else:
                record.actividad_id = False

    @api.depends('nandina_ids')
    def _compute_nandina_count(self):
        """Count NANDINA codes"""
        for record in self:
            record.nandina_count = len(record.nandina_ids)

    def name_get(self):
        """Display format: [CODE] Description (truncated)"""
        result = []
        for record in self:
            desc = record.descripcion_producto[:80] + '...' if len(
                record.descripcion_producto) > 80 else record.descripcion_producto
            name = f"[{record.codigo_producto}] {desc}"
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by activity code, product code or description"""
        args = args or []
        if name:
            args = ['|', '|',
                    ('codigo_actividad', operator, name),
                    ('codigo_producto', operator, name),
                    ('descripcion_producto', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def sync_from_siat_response(self, company, productos_list):
        """
        Synchronize products/services from SIAT response

        :param company: res.company record
        :param productos_list: list of dicts with codigoActividad, codigoProducto, descripcionProducto, nandina (optional list)
        :return: dict with statistics
        """
        if not productos_list:
            _logger.warning("No products/services to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0, 'duplicates_in_response': 0}

        created = 0
        updated = 0
        duplicates_in_response = 0
        sync_time = fields.Datetime.now()

        _logger.info("=== INICIO SINCRONIZACIÓN PRODUCTOS SIAT ===")
        _logger.info(f"Company: {company.name}, Total productos a procesar: {len(productos_list)}")

        existing_records = self.search([('company_id', '=', company.id)])
        existing_keys = {
            (rec.codigo_actividad, rec.codigo_producto): rec
            for rec in existing_records
        }
        synced_keys = set()

        _logger.info(f"Productos existentes en BD: {len(existing_records)}")

        seen_in_this_sync = set()

        nandina_model = self.env['alpha.siat.producto.nandina']

        for idx, prod_data in enumerate(productos_list, 1):
            codigo_act = prod_data.get('codigoActividad', '').strip()
            codigo_prod = prod_data.get('codigoProducto', '').strip()

            if not codigo_act or not codigo_prod:
                _logger.warning(f"Producto {idx}: Datos incompletos - Act: '{codigo_act}', Prod: '{codigo_prod}'")
                continue

            key = (codigo_act, codigo_prod)

            if key in seen_in_this_sync:
                duplicates_in_response += 1
                _logger.warning(
                    f"Producto {idx}: DUPLICADO en respuesta SIAT - Activity={codigo_act}, Product={codigo_prod}"
                )
                continue

            seen_in_this_sync.add(key)
            synced_keys.add(key)

            nandinas = prod_data.get('nandinas', [])

            vals = {
                'company_id': company.id,
                'codigo_actividad': codigo_act,
                'codigo_producto': codigo_prod,
                'descripcion_producto': prod_data.get('descripcionProducto', '').strip(),
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            try:
                if key in existing_keys:
                    existing_rec = existing_keys[key]
                    _logger.debug(f"Producto {idx}: Actualizando existente - {codigo_act}/{codigo_prod}")

                    if existing_rec.descripcion_producto != vals['descripcion_producto'] or not existing_rec.active:
                        existing_rec.write(vals)
                        updated += 1
                        _logger.info(f"Producto {idx}: ACTUALIZADO - {codigo_act}/{codigo_prod}")
                    else:
                        existing_rec.write({'ultima_sincronizacion': sync_time})

                    if nandinas:
                        _logger.debug(f"Producto {idx}: Sincronizando {len(nandinas)} códigos NANDINA")
                    nandina_model.sync_nandinas_for_producto(existing_rec, nandinas, sync_time)
                else:
                    _logger.info(f"Producto {idx}: CREANDO nuevo - {codigo_act}/{codigo_prod}")
                    _logger.debug(f"Valores: {vals}")

                    new_rec = self.with_context(tracking_disable=True).create(vals)
                    created += 1
                    _logger.info(f"Producto {idx}: CREADO exitosamente - ID: {new_rec.id}")

                    # Create NANDINA records
                    if nandinas:
                        _logger.debug(f"Producto {idx}: Creando {len(nandinas)} códigos NANDINA")
                        nandina_model.sync_nandinas_for_producto(new_rec, nandinas, sync_time)

            except Exception as e:
                error_msg = str(e)
                _logger.error(f"Producto {idx}: ERROR procesando {codigo_act}/{codigo_prod}")
                _logger.error(f"Tipo de error: {type(e).__name__}")
                _logger.error(f"Mensaje: {error_msg}")

                if 'duplicate key value violates unique constraint' in error_msg:
                    _logger.warning(
                        f"Producto {idx}: Constraint duplicado (race condition) - Activity={codigo_act}, Product={codigo_prod}"
                    )
                    duplicates_in_response += 1
                    self.env.cr.rollback()
                elif 'InFailedSqlTransaction' in error_msg or 'aborted' in error_msg:
                    _logger.error(f"Producto {idx}: Transacción SQL fallida detectada. Haciendo rollback...")
                    self.env.cr.rollback()
                    existing_records = self.search([('company_id', '=', company.id)])
                    existing_keys = {
                        (rec.codigo_actividad, rec.codigo_producto): rec
                        for rec in existing_records
                    }
                    _logger.info(f"Producto {idx}: Transacción reiniciada, continuando...")
                else:
                    _logger.error(f"Producto {idx}: Error no manejado, deteniendo sincronización")
                    self.env.cr.rollback()
                    raise

            if idx % 100 == 0:
                _logger.info(f"Progreso: {idx}/{len(productos_list)} productos procesados")

        _logger.info("Procesando productos a desactivar...")
        keys_to_deactivate = set(existing_keys.keys()) - synced_keys
        deactivated = 0
        if keys_to_deactivate:
            _logger.info(f"Productos a desactivar: {len(keys_to_deactivate)}")
            records_to_deactivate = self.browse([
                existing_keys[key].id for key in keys_to_deactivate
                if existing_keys[key].active
            ])
            if records_to_deactivate:
                records_to_deactivate.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })
                deactivated = len(records_to_deactivate)
                _logger.info(f"Productos desactivados: {deactivated}")

        log_msg = (
            f"SIAT Products/Services sync completed for {company.name}: "
            f"{created} created, {updated} updated, {deactivated} deactivated"
        )
        if duplicates_in_response > 0:
            log_msg += f", {duplicates_in_response} duplicates skipped"

        _logger.info("=== FIN SINCRONIZACIÓN PRODUCTOS SIAT ===")
        _logger.info(log_msg)

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'duplicates_in_response': duplicates_in_response,
            'total_synced': len(synced_keys)
        }


class SiatProductoNandina(models.Model):
    _name = "alpha.siat.producto.nandina"
    _description = "SIAT - Códigos NANDINA por Producto"
    _order = "producto_servicio_id, codigo_nandina"
    _rec_name = "codigo_nandina"

    producto_servicio_id = fields.Many2one(
        "alpha.siat.producto.servicio",
        string="Producto/Servicio",
        required=True,
        ondelete="cascade",
        index=True
    )

    codigo_nandina = fields.Char(
        string="Código NANDINA",
        required=True,
        index=True,
        help="Código arancelario NANDINA (Nomenclatura Arancelaria Andina)"
    )

    active = fields.Boolean(default=True)

    ultima_sincronizacion = fields.Datetime(
        string="Última Sincronización",
        readonly=True
    )

    _sql_constraints = [
        ('uniq_producto_nandina',
         'UNIQUE(producto_servicio_id, codigo_nandina)',
         'El código NANDINA debe ser único por producto')
    ]

    @api.model
    def sync_nandinas_for_producto(self, producto_rec, nandinas_list, sync_time):
        """
        Sync NANDINA codes for a specific product

        :param producto_rec: alpha.siat.producto.servicio record
        :param nandinas_list: list of NANDINA code strings
        :param sync_time: datetime of sync
        """
        if not nandinas_list:
            # No nandinas in response, deactivate all existing
            existing_nandinas = self.search([
                ('producto_servicio_id', '=', producto_rec.id),
                ('active', '=', True)
            ])
            if existing_nandinas:
                existing_nandinas.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })
            return

        # Get existing NANDINA codes for this product
        existing_nandinas = self.search([('producto_servicio_id', '=', producto_rec.id)])
        existing_codes = {rec.codigo_nandina: rec for rec in existing_nandinas}
        synced_codes = set()

        for nandina_code in nandinas_list:
            nandina_code = nandina_code.strip()
            if not nandina_code:
                continue

            synced_codes.add(nandina_code)

            if nandina_code in existing_codes:
                # Update existing
                rec = existing_codes[nandina_code]
                if not rec.active:
                    rec.write({'active': True, 'ultima_sincronizacion': sync_time})
                else:
                    rec.write({'ultima_sincronizacion': sync_time})
            else:
                # Create new
                self.create({
                    'producto_servicio_id': producto_rec.id,
                    'codigo_nandina': nandina_code,
                    'ultima_sincronizacion': sync_time,
                    'active': True,
                })

        # Deactivate codes no longer in SIAT
        codes_to_deactivate = set(existing_codes.keys()) - synced_codes
        if codes_to_deactivate:
            recs_to_deactivate = self.search([
                ('producto_servicio_id', '=', producto_rec.id),
                ('codigo_nandina', 'in', list(codes_to_deactivate)),
                ('active', '=', True)
            ])
            if recs_to_deactivate:
                recs_to_deactivate.write({
                    'active': False,
                    'ultima_sincronizacion': sync_time
                })