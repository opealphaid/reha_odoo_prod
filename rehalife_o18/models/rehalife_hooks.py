# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Migrates existing patient records after alpha_siat dependency is added:
    1. Copies document_number → vat where vat is empty.
    2. Assigns CI tipo documento (codigo_clasificador=1) where missing.
    Uses direct SQL to bypass ORM triggers and required-field constraints.
    """
    env.cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'document_number'
    """)
    if env.cr.fetchone():
        env.cr.execute("""
            UPDATE res_partner
            SET vat = document_number
            WHERE es_paciente = TRUE
              AND document_number IS NOT NULL
              AND document_number != ''
              AND (vat IS NULL OR vat = '')
        """)
        migrated = env.cr.rowcount
        _logger.info('post_init_hook: %d pacientes migrados document_number → vat', migrated)
    else:
        _logger.info('post_init_hook: columna document_number no existe, migración omitida')

    env.cr.execute("""
        SELECT id FROM alpha_siat_tipo_documento_identidad
        WHERE active = TRUE
          AND (codigo_clasificador = 1 OR descripcion ILIKE '%%CI%%')
        ORDER BY codigo_clasificador
        LIMIT 1
    """)
    row = env.cr.fetchone()
    if row:
        tipo_id = row[0]
        env.cr.execute("""
            UPDATE res_partner
            SET siat_tipo_documento_identidad_id = %s
            WHERE es_paciente = TRUE
              AND siat_tipo_documento_identidad_id IS NULL
        """, (tipo_id,))
        assigned = env.cr.rowcount
        _logger.info(
            'post_init_hook: %d pacientes asignados tipo documento CI (id=%s)',
            assigned, tipo_id,
        )
    else:
        _logger.warning('post_init_hook: No se encontró tipo documento CI en SIAT')
