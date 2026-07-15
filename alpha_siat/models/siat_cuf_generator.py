import logging
from datetime import datetime
from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SiatCufGenerator(models.AbstractModel):
    _name = "alpha.siat.cuf.generator"
    _description = "SIAT CUF Generator - Generador de Código Único de Factura"

    @api.model
    def completar_ceros(self, cadena, longitud):

        cadena_str = str(cadena)
        while len(cadena_str) < longitud:
            cadena_str = "0" + cadena_str

        _logger.info(f"   Completando ceros: '{cadena}' -> '{cadena_str}' (longitud: {len(cadena_str)})")
        return cadena_str

    @api.model
    def calcular_modulo_11(self, cadena, num_dig=1, lim_mult=9, x10=False):

        _logger.info(f"   Calculando Módulo 11 para cadena: {cadena}")
        _logger.info(f"   Longitud de cadena: {len(cadena)} caracteres")

        if not x10:
            num_dig = 1

        cadena_trabajo = cadena

        for n in range(1, num_dig + 1):
            suma = 0
            mult = 2

            for i in range(len(cadena_trabajo) - 1, -1, -1):
                digito = int(cadena_trabajo[i])
                suma += mult * digito
                _logger.debug(f"      Pos {i}: dígito={digito}, mult={mult}, suma parcial={suma}")

                mult += 1
                if mult > lim_mult:
                    mult = 2

            _logger.info(f"   Suma total: {suma}")

            if x10:
                dig = ((suma * 10) % 11) % 10
            else:
                dig = suma % 11

            _logger.info(f"   Dígito calculado: {dig}")

            if dig == 10:
                cadena_trabajo += "1"
                _logger.info(f"   Dígito era 10, se reemplaza por: 1")
            elif dig == 11:
                cadena_trabajo += "0"
                _logger.info(f"   Dígito era 11, se reemplaza por: 0")
            else:
                cadena_trabajo += str(dig)
                _logger.info(f"   Dígito verificador: {dig}")

        # Retornar solo los últimos num_dig dígitos
        resultado = cadena_trabajo[-num_dig:]
        _logger.info(f"   Módulo 11 resultado: {resultado}")
        return resultado

    @api.model
    def convertir_base16(self, cadena):
        """
        Convierte una cadena numérica a Base 16 (hexadecimal)

        :param cadena: Cadena numérica en base 10
        :return: Cadena en base 16 (hexadecimal en mayúsculas)
        """
        _logger.info(f"   Convirtiendo a Base 16: {cadena}")

        # Convertir a entero y luego a hexadecimal
        numero = int(cadena)
        hex_resultado = hex(numero)[2:].upper()  # [2:] para quitar el '0x'

        _logger.info(f"   Base 16 resultado: {hex_resultado}")
        return hex_resultado

    @api.model
    def generar_cuf(self, company_id=None, numero_factura=1, fecha_hora_emision=None):

        _logger.info("=" * 80)
        _logger.info("INICIANDO GENERACIÓN DE CUF (Código Único de Factura)")
        _logger.info("=" * 80)

        # Obtener la compañía
        if company_id:
            company = self.env['res.company'].browse(company_id)
        else:
            company = self.env.company

        if not company:
            raise UserError("No se pudo obtener la compañía para generar el CUF")

        _logger.info(f"Compañía: {company.name}")

        # Obtener configuración SIAT
        config = company.siat_config_id or self.env['alpha.siat.config'].search([], limit=1)
        if not config:
            raise UserError("No se encontró configuración SIAT. Configure primero el sistema.")

        _logger.info(f"Configuración SIAT: {config.name}")

        nit_raw = (company.vat or '').strip()
        if not nit_raw:
            raise UserError(f"La compañía '{company.name}' no tiene NIT configurado")

        nit_limpio = ''.join(filter(str.isdigit, nit_raw))
        nit = self.completar_ceros(nit_limpio, 13)

        if fecha_hora_emision:
            now = fecha_hora_emision
            _logger.info(f"Usando fecha/hora proporcionada: {now}")
        else:
            now = datetime.now()
            _logger.info(f"Usando fecha/hora actual: {now}")

        fecha_hora = now.strftime("%Y%m%d%H%M%S%f")[:-3]  # yyyyMMddHHmmssSSS
        _logger.info(f"Fecha/Hora formateada para CUF: {fecha_hora}")

        sucursal_raw = company.siat_codigo_sucursal or 0
        sucursal = self.completar_ceros(sucursal_raw, 4)


        modalidad = config.modalidad or '1'


        tipo_emision = '1'  # 1 = Online

        tipo_factura = '1'  # 1 = Factura con Derecho a Crédito Fiscal

        tipo_documento_sector_raw = 1  # 1 = Factura Compra Venta
        tipo_documento_sector = self.completar_ceros(tipo_documento_sector_raw, 2)


        numero_factura_formateado = self.completar_ceros(numero_factura, 10)


        pos_raw = company.siat_codigo_punto_venta or 0
        pos = self.completar_ceros(pos_raw, 4)


        cadena_sin_verificador = (
                nit +
                fecha_hora +
                sucursal +
                modalidad +
                tipo_emision +
                tipo_factura +
                tipo_documento_sector +
                numero_factura_formateado +
                pos
        )

        _logger.info(f"Cadena sin verificador: {cadena_sin_verificador} (longitud: {len(cadena_sin_verificador)})")

        if len(cadena_sin_verificador) != 53:
            raise UserError(f"ERROR: La cadena debe tener 53 caracteres, tiene {len(cadena_sin_verificador)}")


        digito_verificador = self.calcular_modulo_11(cadena_sin_verificador, num_dig=1, lim_mult=9, x10=False)

        _logger.info(f"Dígito verificador calculado: {digito_verificador}")

        cadena_con_verificador = cadena_sin_verificador + digito_verificador

        if len(cadena_con_verificador) != 54:
            raise UserError(
                f"ERROR: La cadena con verificador debe tener 54 caracteres, tiene {len(cadena_con_verificador)}")

        cadena_base16 = self.convertir_base16(cadena_con_verificador)

        _logger.info(f"Cadena en Base 16: {cadena_base16}")

        cufd_model = self.env['alpha.siat.cufd']
        try:
            cufd_codigo = cufd_model.get_or_fetch_cufd(company)

            cufd_record = cufd_model.search([
                ('company_id', '=', company.id),
                ('cufd', '=', cufd_codigo),
                ('state', '=', 'valid')
            ], limit=1, order='fecha_vigencia desc')

            if cufd_record and cufd_record.codigo_control:
                codigo_control = cufd_record.codigo_control
                _logger.info(f"Código de Control CUFD: {codigo_control}")
            else:
                _logger.warning("No se pudo obtener el código de control del CUFD")
                codigo_control = "CODIGOCONTROLTEMPORAL"
                _logger.info(f"Usando código temporal: {codigo_control}")

        except Exception as e:
            _logger.error(f"Error al obtener CUFD: {e}")
            codigo_control = "CODIGOCONTROLTEMPORAL"
            _logger.info(f"Usando código temporal: {codigo_control}")

        cuf_final = cadena_base16 + codigo_control

        _logger.info(f"\nCUF GENERADO: {cuf_final}")
        _logger.info(f"Longitud: {len(cuf_final)} caracteres")
        _logger.info("=" * 80)

        return {
            'cuf': cuf_final,
            'nit': nit,
            'fecha_hora': fecha_hora,
            'sucursal': sucursal,
            'modalidad': modalidad,
            'tipo_emision': tipo_emision,
            'tipo_factura': tipo_factura,
            'tipo_documento_sector': tipo_documento_sector,
            'numero_factura': numero_factura_formateado,
            'pos': pos,
            'digito_verificador': digito_verificador,
            'base16': cadena_base16,
            'codigo_control': codigo_control
        }